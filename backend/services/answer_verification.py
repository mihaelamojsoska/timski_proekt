"""Cross-checks a live-search answer against a course-context answer before
replying, when a chat question has both available - orchestration layer on
top of the raw Groq calls in ai/chat.py, the same relationship
chat_service.py already has to that module.

Root problem this addresses: routes/chatRoute.py used to just concatenate
search context and course context into one string and send it to Groq in a
single call, with nothing catching it if the model blended or embellished
across the two sources. This module instead generates two isolated draft
answers (one per source, see ai/chat.py::generate_isolated_draft) and a
verify/merge call (ai/chat.py::stream_verify_response) that keeps only
claims actually backed by the raw source text, dropping anything neither
source supports.

Only triggered when both sources are genuinely available for a given
question (see should_verify) - every other question is unaffected, at zero
added cost or latency.
"""
import asyncio
import logging
from typing import AsyncIterator, List, Optional, Tuple

import httpx

from backend.ai.chat import (
    generate_comparison_notes,
    generate_isolated_draft,
    stream_groq_response,
    stream_verify_response,
)
from backend.database.models import Course
from backend.models.message import Message
from backend.models.searchResult import SearchResult
from backend.services.course_context import format_course_context
from backend.web_search.search import format_search_context
from config import ENABLE_ANSWER_VERIFICATION

logger = logging.getLogger(__name__)

# Per-draft timeout - these use DRAFT_MODEL (small/fast), so a generous
# safety margin still keeps the whole gather well under the verify call's
# own budget below.
_DRAFT_TIMEOUT_SECONDS = 20
# How long to wait for the verify/merge call's FIRST chunk before giving up
# on it and falling back to a joined-context single call (see
# _verify_stream_with_fallback) - not a total-response timeout, since once
# streaming has actually started there's no clean way to abandon it (bytes
# are already on the wire to the client).
_VERIFY_FIRST_CHUNK_TIMEOUT_SECONDS = 25

# Rough chars-per-token estimate (no tokenizer available cheaply here) used
# only to keep this pipeline off of Groq's per-minute token budget on tight
# tiers - real-world crash: a course with 100+ recordings makes
# format_course_context() genuinely large, and running 4-5 extra Groq calls
# (2-3 drafts + comparison notes + verify) on top of an already-large context
# blew straight through an org's 8000 TPM limit, failing every call in the
# pipeline including the safety-net fallback (which reuses the exact same
# context). Skipping verification above this size falls back to the plain
# single-call path instead - unaffected by any of this, and the same path
# every other question already takes (and which now has its own independent
# size safety net too - see ai/chat.py::_fit_to_token_budget - so this gate
# is no longer the only thing standing between an oversized request and a
# 413, just the one that avoids wasting the drafts/comparison calls first).
#
# The verify call is the binding constraint (GROQ_MODEL's own separate 8000
# TPM ceiling): its request = this gated context/history + its own reserved
# max_tokens (ai/chat.py::_ANSWER_MAX_TOKENS, 1800 - Groq charges the full
# reserved amount against TPM regardless of actual output length) + system
# prompt overhead (~1000 tokens, generously estimated) + up to 3 full drafts
# re-embedded (each capped at 800 output tokens, so up to ~2400 tokens worst
# case). That leaves roughly 8000 - 1800 - 1000 - 2400 = 2800 tokens of
# headroom for context+history+the optional third source combined - this
# constant is set at ~2500 tokens (10000 chars) to stay under that with a
# margin for the char-per-token estimate being approximate.
_CHARS_PER_TOKEN_ESTIMATE = 4
_MAX_COMBINED_CONTEXT_CHARS_FOR_VERIFICATION = 2500 * _CHARS_PER_TOKEN_ESTIMATE


def _course_has_real_content(course: Optional[Course]) -> bool:
    """format_course_context() always returns a non-empty header
    ("## Course Context: {name}") even for a course with zero materials and
    zero recordings, so a truthiness check on the formatted string would
    wrongly gate in a course-only draft that can only ever say "not
    covered." Check the actual underlying content instead.

    Deliberately checks both relationships as separate statements rather
    than `course.materials or course.recordings` - that `or` would
    short-circuit and never touch `.recordings` when `.materials` is
    already truthy, leaving it lazy/unloaded. chatRoute.py's request-scoped
    db session is closed by the time this course object is touched again
    inside its own event_stream() generator, so an unloaded relationship
    accessed there raises DetachedInstanceError instead of a query - both
    need to be loaded now, while the session is still open, regardless of
    which one turns out to matter for this check's own answer."""
    if not course:
        return False
    has_materials = bool(course.materials)
    has_recordings = bool(course.recordings)
    return has_materials or has_recordings


def should_verify(
    search_results: List[SearchResult],
    course: Optional[Course],
    context: str,
    model_messages: List[Message],
) -> bool:
    """Gate for the whole pipeline: only worth the extra Groq calls when
    there are genuinely two independent sources to cross-check. No question-
    complexity heuristic - that would need either another LLM call (defeats
    the point) or a fragile heuristic that misfires exactly on the short,
    tricky questions where hallucination-guarding matters most.

    Also backs off for an already-large request (big course context and/or
    a long conversation) - `context` here is the same combined search+course
    context string chatRoute.py already built for the plain single-call
    path, reused rather than reformatted a second time. This exists because
    a course with 100+ recordings makes format_course_context() genuinely
    large, and stacking 4 extra Groq calls on top of that blew straight
    through a real account's 8000 TPM limit - see the size constants above."""
    if not (ENABLE_ANSWER_VERIFICATION and bool(search_results) and _course_has_real_content(course)):
        return False
    history_chars = sum(len(m.content) for m in model_messages)
    if len(context) + history_chars > _MAX_COMBINED_CONTEXT_CHARS_FOR_VERIFICATION:
        logger.info(
            "Skipping answer verification for an oversized request (context=%d chars, history=%d chars) - "
            "falling back to the plain single-call path to avoid a token-budget failure",
            len(context), history_chars,
        )
        return False
    return True


async def _verify_stream_with_fallback(
    messages: List[Message],
    subject: Optional[str],
    search_draft: str,
    course_draft: str,
    search_context: str,
    course_context: str,
    fallback_context: str,
    cached_draft: Optional[str] = None,
    cached_context: Optional[str] = None,
    cached_query: Optional[str] = None,
) -> AsyncIterator[str]:
    """Wraps stream_verify_response with a first-chunk timeout/failure
    fallback. If the verify call can't even start, fall back to a plain
    joined-context single call - safe to do since nothing has reached the
    client yet. If it fails AFTER the first chunk, that's left to propagate
    to chatRoute.py's existing outer try/except (event: error + partial-
    reply save) instead of being caught here - there's no clean way to
    retroactively fall back once bytes are already on the wire."""
    async with httpx.AsyncClient(timeout=60) as client:
        gen = stream_verify_response(
            client, messages, subject, search_draft, course_draft, search_context, course_context,
            cached_draft=cached_draft, cached_context=cached_context, cached_query=cached_query,
        )
        try:
            first_chunk = await asyncio.wait_for(gen.__anext__(), timeout=_VERIFY_FIRST_CHUNK_TIMEOUT_SECONDS)
        except StopAsyncIteration:
            return
        except Exception:
            logger.warning("Verify/merge call failed to start - falling back to joined-context answer", exc_info=True)
            async for chunk in stream_groq_response(messages, fallback_context, subject):
                yield chunk
            return

        yield first_chunk
        async for chunk in gen:
            yield chunk


def _latest_user_only(messages: List[Message]) -> List[Message]:
    """Isolated drafts don't need multi-turn history to answer THIS question
    using only the given context - they're never shown to the student
    directly, so conversational continuity doesn't matter for them the way
    it does for the final verify/merge answer. Trimming to just the latest
    user message is the single biggest lever for cutting this pipeline's
    token footprint: sending the full history to both drafts was otherwise
    duplicating it twice on top of what the verify call (which does need
    it) already sends - see the size-gating constants above for why this
    matters on a tight Groq tier."""
    for m in reversed(messages):
        if m.role == "user":
            return [m]
    return messages


def _cached_source_fits_budget(
    search_context: str, course_context: str, model_messages: List[Message], related_context: str
) -> bool:
    """Whether adding the optional third source's context would still keep
    this turn's verify call under the same budget should_verify() already
    checked without it. Checked again here (not just once in should_verify)
    because find_related_cached_search() runs AFTER should_verify() passes,
    in chatRoute.py - its context was never counted in that first check, and
    it can be sizeable on its own (up to 5 formatted search results)."""
    history_chars = sum(len(m.content) for m in model_messages)
    total = len(search_context) + len(course_context) + history_chars + len(related_context)
    return total <= _MAX_COMBINED_CONTEXT_CHARS_FOR_VERIFICATION


async def build_verified_answer(
    model_messages: List[Message],
    subject: Optional[str],
    search_results: List[SearchResult],
    course: Optional[Course],
    related_cached: Optional[Tuple[str, List[SearchResult]]] = None,
) -> Tuple[AsyncIterator[str], Optional[dict]]:
    """Only call this when should_verify(...) is True. Returns (answer
    stream, reasoning payload or None) - the reasoning payload is decided
    up front (as soon as the two always-present drafts succeed) since it's
    just the raw drafts, independent of whether the verify/merge call itself
    later succeeds.

    related_cached is optional: (original_question, results) for a
    previously cached search loosely related to this one - see
    services/search_cache.py::find_related_cached_search. When present AND
    it still fits the token budget alongside the two always-present sources
    (see _cached_source_fits_budget), it becomes a third isolated draft/
    source to cross-check against - purely additive: its own Groq call is
    deliberately only launched AFTER the two always-present drafts are
    already confirmed to have succeeded (see below), specifically so a
    primary-draft failure never pays for a third-source call it's about to
    throw away in the fallback branches."""
    search_context = format_search_context(search_results)
    course_context = format_course_context(course)
    fallback_context = "\n\n".join(c for c in (search_context, course_context) if c)

    draft_messages = _latest_user_only(model_messages)

    related_query: Optional[str] = None
    related_context: Optional[str] = None
    if related_cached:
        candidate_query, related_results = related_cached
        candidate_context = format_search_context(related_results)
        if _cached_source_fits_budget(search_context, course_context, model_messages, candidate_context):
            related_query, related_context = candidate_query, candidate_context
        else:
            logger.info(
                "Skipping the optional cached third source - adding it would exceed the verification token budget"
            )

    async with httpx.AsyncClient(timeout=60) as client:
        search_draft, course_draft = await asyncio.gather(
            asyncio.wait_for(
                generate_isolated_draft(client, draft_messages, search_context, "web search results", subject),
                timeout=_DRAFT_TIMEOUT_SECONDS,
            ),
            asyncio.wait_for(
                generate_isolated_draft(client, draft_messages, course_context, "this course's materials", subject),
                timeout=_DRAFT_TIMEOUT_SECONDS,
            ),
            return_exceptions=True,
        )

        # Groq can return HTTP 200 with an empty completion (e.g. a very
        # sparse context block leaves the model nothing to say but a stop
        # token) - `isinstance(x, str)` alone would count that as a real
        # draft and feed an empty section into the comparison/verify prompts
        # instead of correctly falling back to the other source the way an
        # actual exception does.
        search_ok = isinstance(search_draft, str) and bool(search_draft.strip())
        course_ok = isinstance(course_draft, str) and bool(course_draft.strip())

        if not search_ok and not course_ok:
            logger.warning("Both isolated drafts failed (%r, %r) - falling back to joined-context answer", search_draft, course_draft)
            return stream_groq_response(model_messages, fallback_context, subject), None

        if not course_ok:
            logger.warning("Course draft failed (%r) - falling back to search-only answer", course_draft)
            return stream_groq_response(model_messages, search_context, subject), None

        if not search_ok:
            logger.warning("Search draft failed (%r) - falling back to course-only answer", search_draft)
            return stream_groq_response(model_messages, course_context, subject), None

        # Both always-present drafts are real - now, and only now, spend the
        # optional third source's Groq call (run alongside the comparison
        # note, since both are independent DRAFT_MODEL calls) - deferred
        # until this point so a primary-draft failure above never pays for
        # a third-source draft it would've just discarded anyway.
        comparison_task = asyncio.wait_for(
            generate_comparison_notes(client, search_draft, course_draft, subject),
            timeout=_DRAFT_TIMEOUT_SECONDS,
        )
        cached_draft = None
        if related_context:
            cached_task = asyncio.wait_for(
                generate_isolated_draft(
                    client, draft_messages, related_context,
                    f'a previously cached search on a related question ("{related_query}")', subject,
                ),
                timeout=_DRAFT_TIMEOUT_SECONDS,
            )
            comparison_notes, cached_draft = await asyncio.gather(
                comparison_task, cached_task, return_exceptions=True
            )
        else:
            try:
                comparison_notes = await comparison_task
            except Exception as exc:
                comparison_notes = exc

        # Deliberately stays a two-way comparison (search vs. course) even
        # when a cached draft is also present - that draft gets its own card
        # instead (see frontend), not folded into this note. Non-fatal: the
        # reasoning panel just omits it if this one call fails, since the
        # drafts themselves are still worth showing either way.
        if isinstance(comparison_notes, Exception):
            logger.warning("Comparison-notes generation failed - reasoning panel will omit it", exc_info=comparison_notes)
            comparison_notes = None

        cached_ok = isinstance(cached_draft, str) and bool(cached_draft.strip())
        if related_context and not cached_ok:
            logger.warning("Cached-search draft failed (%r) - omitting it, no fallback needed", cached_draft)

    reasoning = {
        "searchDraft": search_draft,
        "courseDraft": course_draft,
        "comparisonNotes": comparison_notes,
        "cachedDraft": cached_draft if cached_ok else None,
        "cachedQuery": related_query if cached_ok else None,
    }
    stream = _verify_stream_with_fallback(
        model_messages, subject, search_draft, course_draft, search_context, course_context, fallback_context,
        cached_draft=cached_draft if cached_ok else None,
        cached_context=related_context if cached_ok else None,
        cached_query=related_query if cached_ok else None,
    )
    return stream, reasoning
