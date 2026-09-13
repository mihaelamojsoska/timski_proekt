import json
from typing import List, Optional, Tuple

import httpx
from fastapi import HTTPException

from backend.models.message import Message
from config import GROQ_API_KEY

# llama-3.3-70b-versatile was retired from Groq's catalog - GET /openai/v1/models
# no longer lists it (confirmed 2026-08-20). openai/gpt-oss-120b is the closest
# replacement in size/capability among what's currently available.
GROQ_MODEL = "openai/gpt-oss-120b"
# Same model family as GROQ_MODEL (same 131072 context window), exactly half
# the price per token on both input and output (confirmed live against
# GET /openai/v1/models' pricing field) - used only for the two isolated
# single-source drafts in the answer-verification pipeline (see
# services/answer_verification.py), which are intermediate artifacts never
# shown to the student directly, not the final answer quality bar.
DRAFT_MODEL = "openai/gpt-oss-20b"

# Groq's per-minute token budget is charged against max_tokens itself, not
# against what the model actually generates - a request reserving 4096
# output tokens eats more than half of the free tier's entire 8000 TPM
# ceiling before a single prompt token is even counted, so it can 413
# ("rate_limit_exceeded") on its own, independent of context/history size.
# Confirmed against Groq's own docs (console.groq.com/docs/rate-limits) and
# real production 413s where the joined-context single-call fallback path -
# not the multi-call verification pipeline - was itself the request that hit
# the ceiling. 1800 is generous for a tutoring answer (~7000 characters)
# while leaving real headroom in the per-minute budget for prompt tokens.
_ANSWER_MAX_TOKENS = 1800

# Last-resort safety net for stream_groq_response's OWN token budget,
# independent of any upstream gate - this is the one call every path in this
# module eventually reduces to (the plain default path when verification
# isn't triggered, AND both fallback destinations in
# services/answer_verification.py when verification is triggered but a
# draft/the verify call itself fails), so it must never itself be the thing
# that blows through Groq's per-minute limit regardless of which caller
# reached it. answer_verification.py's own, tighter gate
# (_MAX_COMBINED_CONTEXT_CHARS_FOR_VERIFICATION) only ever protected the
# multi-call pipeline, never this path - this closes that gap.
#
# Set higher than that gate since this call carries none of the pipeline's
# extra overhead (no drafts re-embedded, no comparison notes) - just this
# constant's own reserved _ANSWER_MAX_TOKENS (1800) plus SYSTEM_PROMPT's own
# overhead (~700 tokens, generously estimated): 8000 - 1800 - 700 = 5500
# tokens of headroom, rounded down to ~5000 tokens (20000 chars) for margin.
_MAX_PLAIN_CALL_CONTEXT_CHARS = 20000


def _fit_to_token_budget(messages: List[Message], context: str) -> Tuple[List[Message], str]:
    """Trims context and/or conversation history so a single stream_groq_response
    call stays under _MAX_PLAIN_CALL_CONTEXT_CHARS - a no-op for the vast
    majority of requests, which are nowhere near this size. Trims context
    first (supplementary background, not the actual exchange) before ever
    touching history, and even then only drops the OLDEST messages, always
    keeping at least the single latest message so the model still has
    something to respond to."""
    history_chars = sum(len(m.content) for m in messages)
    if len(context) + history_chars <= _MAX_PLAIN_CALL_CONTEXT_CHARS:
        return messages, context

    context_budget = max(0, _MAX_PLAIN_CALL_CONTEXT_CHARS - history_chars)
    if len(context) > context_budget:
        context = (
            context[:context_budget] + "\n\n[...context truncated to fit this request's token budget]"
            if context_budget
            else ""
        )

    trimmed = list(messages)
    while len(trimmed) > 1 and (len(context) + sum(len(m.content) for m in trimmed)) > _MAX_PLAIN_CALL_CONTEXT_CHARS:
        trimmed.pop(0)
    return trimmed, context


SYSTEM_PROMPT = """You are LearnWise, an expert AI tutor. Your job is to help students understand technical topics clearly and accurately.

When answering:
1. Be concise but thorough — explain the WHY not just the WHAT
2. Use simple analogies for complex concepts
3. Include short, practical code examples when relevant
4. If search results or course materials are provided, use them as your primary source of truth and cite them
5. NEVER invent links, filenames, portals, or specific resources that were not actually given to you in the
   provided context. If you only have 3 materials, list exactly those 3 - do not pad the list with plausible-
   sounding extras "for completeness." It is fine to suggest general study strategies or well-known public
   resources you are confident actually exist, but never fabricate a URL or claim a specific resource exists
   ("the FINKI portal has X") when you have not actually been given it.
6. If a concept has a common mistake or gotcha, point it out
7. End responses with 1-2 follow-up questions the student might want to explore next
8. Respond in the language you are asked in, matching the student's own script. This school is in North
   Macedonia, so most non-English questions will be Macedonian - including Macedonian written in Latin/
   romanized letters (no diacritics), which is easy to mis-detect as Serbian, Croatian, or Bosnian since
   those languages share a lot of vocabulary in Latin script. If a question could plausibly be Macedonian
   given the context (a FINKI student, technical topics), treat it as Macedonian, not a neighboring language -
   and reply in Macedonian using the same script (Cyrillic or Latin) the student used, not the other one
9. Do not use emoji. Write in plain text - the tutor's voice should read as clear and professional, not decorated
10. When comparing things side by side (e.g. options, pros/cons, before/after), use a real markdown table
    (| col | col |) instead of trying to lay text out in columns with spacing or line breaks - plain text
    cannot actually render aligned columns, so it just looks broken. A markdown table is the only reliable
    way to present that kind of content
11. If you include a section comparing what different sources say (e.g. course materials vs. search
    results), give it its own heading, worded exactly `## Source comparison` (the app looks for this exact
    heading to render it as its own collapsible block). Never call this section "recap," "quick recap," or
    "summary" - those words are already used elsewhere in this app for a different feature, and reusing them
    here confuses students about which one they're looking at. Put this section, if present, as the very
    last part of your response, after the follow-up questions.

Format your responses with markdown (headers, code blocks, bullet points).
Always be encouraging and patient."""


async def _stream_groq_chat_completion(
    client: httpx.AsyncClient,
    *,
    model: str,
    messages: List[dict],
    temperature: float,
    max_tokens: int,
):
    """Shared low-level streaming call - extracted so stream_verify_response
    (the answer-verification pipeline's final streamed call, see
    services/answer_verification.py) doesn't duplicate this SSE-parsing loop
    a second time. stream_groq_response below is now a thin wrapper around
    this; its own external behavior/signature is unchanged."""
    async with client.stream(
            "POST",
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "stream": True,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
    ) as response:
        if response.status_code != 200:
            error = await response.aread()
            raise HTTPException(status_code=response.status_code, detail=error.decode())

        async for line in response.aiter_lines():
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                    if event.get("choices"):
                        delta = event["choices"][0].get("delta", {})
                        if delta.get("content"):
                            yield delta.get("content", "")
                except json.JSONDecodeError:
                    continue


async def stream_groq_response(messages: List[Message], context: str, subject: Optional[str]):
    """Stream a response from GROQ with optional search context injected."""

    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")

    messages, context = _fit_to_token_budget(messages, context)

    # Build the system prompt with context
    system = SYSTEM_PROMPT
    if subject:
        system += f"\n\nThe student is currently learning about: **{subject}**"
    if context:
        system += f"\n\n{context}"

    # Convert our messages to GROQ format
    groq_messages = [{"role": m.role, "content": m.content} for m in messages]
    # Add system message at the beginning
    groq_messages.insert(0, {"role": "system", "content": system})

    async with httpx.AsyncClient(timeout=60) as client:
        async for chunk in _stream_groq_chat_completion(
            client, model=GROQ_MODEL, messages=groq_messages, temperature=0.7, max_tokens=_ANSWER_MAX_TOKENS
        ):
            yield chunk


def _isolated_draft_system_prompt(source_label: str) -> str:
    return f"""You are LearnWise, an AI tutor. You are drafting one internal candidate answer that a
separate reviewer will cross-check - the student will not see this draft directly, only
the final reviewed answer, so skip tone, encouragement, and follow-up questions here.

Rules:
1. Answer using ONLY the {source_label} context block below. Do not use outside knowledge,
   general training knowledge, or facts you're confident are true but that are not present
   in this block - even well-known facts. If it isn't in the block, it doesn't go in the draft.
2. State plainly what the context does and does not cover. If it only partially answers the
   question, say so explicitly (e.g. "These materials cover X but do not mention Y").
   Do not fill the gap with an assumption.
3. Never invent a link, filename, or resource name that isn't literally present in the block.
4. Be direct and concise - bullet the concrete claims you can support.
5. Match the student's language and script (Macedonian Cyrillic vs. Latin, etc.) from the
   conversation."""


async def generate_isolated_draft(
    client: httpx.AsyncClient,
    messages: List[Message],
    context_block: str,
    source_label: str,
    subject: Optional[str],
) -> str:
    """One internal candidate answer grounded ONLY in context_block - never
    shown to the student directly, consumed by stream_verify_response to
    cross-check against the other source's draft (see
    services/answer_verification.py). Uses DRAFT_MODEL - this is an
    intermediate artifact, not the final answer quality bar. Takes a shared
    client so two of these can run concurrently via asyncio.gather without
    opening a separate connection pool each."""
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")

    system = _isolated_draft_system_prompt(source_label)
    if subject:
        system += f"\n\nThe student is currently learning about: **{subject}**"
    system += f"\n\n{context_block}"

    groq_messages = [{"role": m.role, "content": m.content} for m in messages]
    groq_messages.insert(0, {"role": "system", "content": system})

    resp = await client.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": DRAFT_MODEL,
            "messages": groq_messages,
            # Never shown to the student raw - terse is fine, and keeping
            # this (and the requested-tokens budget it counts against) small
            # matters on a tight per-minute token limit, see
            # answer_verification.py's size-gating comment for why.
            "max_tokens": 800,
            "temperature": 0.3,
        },
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    data = resp.json()
    return data["choices"][0]["message"]["content"]


async def generate_comparison_notes(
    client: httpx.AsyncClient,
    search_draft: str,
    course_draft: str,
    subject: Optional[str],
) -> str:
    """A short, explicit explanation of how the two isolated drafts relate -
    what each uniquely covers, where they agree, and where they conflict
    (and which one to trust more, and why) - the actual "reasoning between
    the two models" a student can read, not just the two raw drafts side by
    side with no comparison drawn between them. Shown in the "Thought for
    Xs" panel (see services/answer_verification.py), separate from the
    tutor-voiced final answer. Uses DRAFT_MODEL - short, internal-only text,
    not the final answer quality bar."""
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")

    prompt = f"""Two AI drafts were independently written to answer the same student question - one using
only live web search results, one using only this course's own materials. Compare them for a
curious student who wants to see how you reasoned, not just read the final answer.

[Web search draft]
{search_draft}

[Course materials draft]
{course_draft}

In 3-5 short bullet points (plain text, no markdown headers), cover:
- What each draft uniquely contributes that the other doesn't
- Where the two agree
- Where they conflict, and which one you'd trust more for this question and why

Be concise, specific, and factual - this is an internal comparison note, not a restatement of
either draft."""
    if subject:
        prompt += f"\n\nThe student is currently learning about: {subject}"

    resp = await client.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": DRAFT_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 300,
            "temperature": 0.3,
        },
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    data = resp.json()
    return data["choices"][0]["message"]["content"]


_VERIFY_PREAMBLE = """You are producing the one final answer the student sees, based on independently-drafted
candidate answers to their question - each written using only one evidence source (live web
search results, this course's own materials, or occasionally a previously cached search on a
related question) - plus the raw source material each draft was based on.

Verification rules (apply before the tutoring rules below):
1. Include a claim only if it is directly supported by at least one of the raw context blocks
   below - check the actual source text, not just a draft's wording of it, since a draft can
   overstate or misremember what its source actually says.
2. If multiple sources support a claim, state it directly. If only one source covers it, keep
   the attribution clear and use a DIFFERENT phrase per source, so the student can tell which
   one it came from: "According to the course materials..." for the course context, "A recent
   search result notes..." for the live web search context, and "An earlier search on a related
   question found..." for the cached-search context (when present) - never reuse the live-search
   phrasing for the cached one, they are not the same source. If sources conflict, say so
   explicitly rather than silently picking one.
3. Drop any claim present in a draft that no context block actually supports - this includes
   claims that sound reasonable or like standard practice. Unsupported is unsupported.
4. If no source answers part of the question, say that plainly instead of guessing.
5. If a cached-search source is present and it conflicts with the live web search or course
   materials, prefer the live search / course materials and note that the cached information
   may be out of date - it was captured at an earlier point in time.
"""

# Composed, not rewritten from scratch - guarantees the final answer's tone/
# format stays in lockstep with SYSTEM_PROMPT's tutoring rules as that
# prompt evolves, instead of a second copy to keep in sync by hand.
VERIFY_SYSTEM_PROMPT = _VERIFY_PREAMBLE + "\n" + SYSTEM_PROMPT


async def stream_verify_response(
    client: httpx.AsyncClient,
    messages: List[Message],
    subject: Optional[str],
    search_draft: str,
    course_draft: str,
    search_context: str,
    course_context: str,
    cached_draft: Optional[str] = None,
    cached_context: Optional[str] = None,
    cached_query: Optional[str] = None,
):
    """Streams the final, cross-checked answer - the one the student actually
    sees. Sees all isolated drafts AND the raw context blocks they were each
    built from (not just the drafts' own wording of them), so it can catch a
    draft overstating what its own source actually says - see
    services/answer_verification.py for how the drafts get here.

    cached_draft/cached_context/cached_query are optional: only set when a
    previously cached search on a loosely related question was cheaply
    available (no extra live search call - see
    services/search_cache.py::find_related_cached_search) and worth cross-
    checking as a third source alongside the two always-present ones."""
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")

    latest_user_msg = next((m.content for m in reversed(messages) if m.role == "user"), "")

    system = VERIFY_SYSTEM_PROMPT
    if subject:
        system += f"\n\nThe student is currently learning about: **{subject}**"
    system += f"""

Student question: {latest_user_msg}

[Search context]
{search_context}

[Course context]
{course_context}

[Search-only draft]
{search_draft}

[Course-only draft]
{course_draft}"""

    if cached_draft and cached_context:
        system += f"""

[Cached search context - from a previous, related question: "{cached_query}"]
{cached_context}

[Cached-search draft]
{cached_draft}"""

    groq_messages = [{"role": m.role, "content": m.content} for m in messages]
    groq_messages.insert(0, {"role": "system", "content": system})

    async for chunk in _stream_groq_chat_completion(
        client, model=GROQ_MODEL, messages=groq_messages, temperature=0.5, max_tokens=_ANSWER_MAX_TOKENS
    ):
        yield chunk


async def _request_quiz_json(quiz_prompt: str) -> dict:
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": quiz_prompt}],
                "max_tokens": 2000,
                "temperature": 0.5,
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        # Strip any accidental markdown fences
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(status_code=502, detail="Quiz generation returned an unexpected response - please try again.")
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=502, detail="Quiz generation returned an unexpected response - please try again.")
        return parsed


_QUIZ_JSON_FORMAT = """Respond ONLY with a valid JSON object in exactly this format, no markdown, no extra text:
{
  "topic": "short topic title",
  "questions": [
    {
      "question": "Question text here?",
      "options": ["A) option", "B) option", "C) option", "D) option"],
      "answer": "A",
      "explanation": "Brief explanation of why this is correct."
    }
  ]
}"""


async def generate_quiz(messages: List[Message], subject: Optional[str], course_context: Optional[str] = None):
    """Generate a multiple-choice quiz based on the conversation."""
    # Summarise the conversation topic for the quiz prompt
    conversation = "\n".join(
        f"{m.role.upper()}: {m.content}" for m in messages[-10:]  # last 10 msgs
    )

    quiz_prompt = f"""Based on this tutoring conversation, generate a quiz with 5 multiple-choice questions.

CONVERSATION:
{conversation}

{"The topic is: " + subject if subject else ""}
{course_context if course_context else ""}

{_QUIZ_JSON_FORMAT}"""

    return await _request_quiz_json(quiz_prompt)


async def generate_quiz_from_topic(topic: str, subject: Optional[str] = None):
    """Generate a multiple-choice quiz for a bare topic, with no conversation."""
    quiz_prompt = f"""Generate a quiz with 5 multiple-choice questions about this topic.

TOPIC: {topic}
{"The subject is: " + subject if subject else ""}

{_QUIZ_JSON_FORMAT}"""

    return await _request_quiz_json(quiz_prompt)

async def generate_summary(messages: List[Message], subject: Optional[str], course_context: Optional[str] = None):
    """Summarize the entire conversation into a concise study recap."""
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")

    conversation = "\n".join(f"{m.role.upper()}: {m.content}" for m in messages)

    summary_prompt = f"""Summarize this tutoring conversation into a concise study recap.

CONVERSATION:
{conversation}

{"The topic is: " + subject if subject else ""}
{course_context if course_context else ""}

Write a clear, well-organized summary covering:
1. The main concepts discussed
2. Key takeaways the student should remember
3. Any important gotchas or common mistakes mentioned

Use markdown with short headers and bullet points. Keep it concise — aim for something a student could review in under a minute."""

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": summary_prompt}],
                "max_tokens": 800,
                "temperature": 0.4,
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        data = resp.json()
        return {"summary": data["choices"][0]["message"]["content"]}


async def generate_explore_queries(
    messages: List[Message], subject: Optional[str], course_context: Optional[str] = None
) -> List[str]:
    """Ask Groq for 3 focused search queries related to the conversation topic."""
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")

    conversation = "\n".join(f"{m.role.upper()}: {m.content}" for m in messages[-10:])

    query_prompt = f"""Based on this tutoring conversation, suggest 3 short, specific web search queries
that would help the student explore related topics, deeper resources, or adjacent concepts.

CONVERSATION:
{conversation}

{"The topic is: " + subject if subject else ""}
{course_context if course_context else ""}

Respond ONLY with a valid JSON array of exactly 3 strings, no markdown, no extra text.
Example: ["FastAPI background tasks vs Celery", "Python async context managers", "uvicorn worker tuning"]"""

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": query_prompt}],
                "max_tokens": 200,
                "temperature": 0.6,
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            queries = json.loads(raw)
            if isinstance(queries, list):
                return [str(q) for q in queries[:3]]
        except json.JSONDecodeError:
            pass
        return []

async def generate_followups(
    messages: List[Message], subject: Optional[str], course_context: Optional[str] = None
) -> List[str]:
    """Suggest 4 smart follow-up questions based on the conversation so far."""
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")

    conversation = "\n".join(f"{m.role.upper()}: {m.content}" for m in messages[-10:])

    followup_prompt = f"""Based on this tutoring conversation, suggest 4 natural follow-up questions
the student might want to ask next. They should deepen understanding, explore edge cases,
or connect to related concepts — not just repeat what was already covered.

CONVERSATION:
{conversation}

{"The topic is: " + subject if subject else ""}
{course_context if course_context else ""}

Respond ONLY with a valid JSON array of exactly 4 short question strings, no markdown, no extra text.
Example: ["What happens if the await fails?", "How does this compare to threading?", "When should I avoid this pattern?", "Can you show a real-world example?"]"""

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": followup_prompt}],
                "max_tokens": 300,
                "temperature": 0.7,
            },
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        data = resp.json()
        raw = data["choices"][0]["message"]["content"]
        raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            questions = json.loads(raw)
            if isinstance(questions, list):
                return [str(q) for q in questions[:4]]
        except json.JSONDecodeError:
            pass
        return []