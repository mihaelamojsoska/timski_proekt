"""Tests for backend/services/answer_verification.py - the gating logic
(should_verify) and the fallback matrix (build_verified_answer), which
decides what the student actually sees when one or both of the isolated
drafts, or the verify/merge call, fail.

No real Groq calls or real Course/SearchResult objects are used - the
ai/chat.py functions this module calls are monkeypatched directly (this
module imports them by name, so they're patched on the answer_verification
module's own namespace, not on ai.chat), and Course is a bare object with
just the .materials/.recordings attributes should_verify actually reads.
"""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.models.message import Message
from backend.services import answer_verification as av


def _course(materials=None, recordings=None):
    return SimpleNamespace(materials=materials or [], recordings=recordings or [])


SHORT_CONTEXT = "a short context block"
SHORT_HISTORY = [Message(role="user", content="a short question")]


# ---------------------------------------------------------------------------
# should_verify gating
# ---------------------------------------------------------------------------

def test_should_verify_true_when_search_results_and_course_materials_present():
    assert av.should_verify(["result"], _course(materials=["m"]), SHORT_CONTEXT, SHORT_HISTORY) is True


def test_should_verify_true_when_search_results_and_course_recordings_present():
    # Recordings alone (no materials) must also count - a naive
    # `course.materials or course.recordings` gate would evaluate this
    # correctly too, but see the DetachedInstanceError note in
    # _course_has_real_content for why it can't be written that way.
    assert av.should_verify(["result"], _course(recordings=["r"]), SHORT_CONTEXT, SHORT_HISTORY) is True


def test_should_verify_false_when_no_search_results():
    assert av.should_verify([], _course(materials=["m"]), SHORT_CONTEXT, SHORT_HISTORY) is False


def test_should_verify_false_when_course_is_none():
    assert av.should_verify(["result"], None, SHORT_CONTEXT, SHORT_HISTORY) is False


def test_should_verify_false_when_course_has_no_real_content():
    # A resolved course with zero materials and zero recordings would still
    # produce a non-empty formatted context block (just a header) - this
    # must not be enough to trigger the pipeline.
    assert av.should_verify(["result"], _course(), SHORT_CONTEXT, SHORT_HISTORY) is False


def test_should_verify_false_when_disabled_via_config(monkeypatch):
    monkeypatch.setattr(av, "ENABLE_ANSWER_VERIFICATION", False)
    assert av.should_verify(["result"], _course(materials=["m"]), SHORT_CONTEXT, SHORT_HISTORY) is False


def test_should_verify_false_when_combined_context_and_history_too_large():
    # Regression test for a real production crash: a course with 100+
    # recordings made format_course_context() large enough that stacking 4
    # extra Groq calls on top of it blew through the org's 8000 TPM limit,
    # failing every call in the pipeline - including the safety-net
    # fallback, since it reuses the same oversized context. Falling back to
    # the plain single-call path (unaffected by any of this) is safer than
    # attempting the multi-call pipeline at all in that case.
    huge_context = "x" * (av._MAX_COMBINED_CONTEXT_CHARS_FOR_VERIFICATION + 1)
    assert av.should_verify(["result"], _course(materials=["m"]), huge_context, SHORT_HISTORY) is False


def test_should_verify_false_when_history_alone_is_too_large():
    huge_history = [Message(role="user", content="x" * (av._MAX_COMBINED_CONTEXT_CHARS_FOR_VERIFICATION + 1))]
    assert av.should_verify(["result"], _course(materials=["m"]), SHORT_CONTEXT, huge_history) is False


def test_should_verify_true_right_at_the_size_boundary():
    exactly_at_limit = "x" * av._MAX_COMBINED_CONTEXT_CHARS_FOR_VERIFICATION
    assert av.should_verify(["result"], _course(materials=["m"]), exactly_at_limit, []) is True


# ---------------------------------------------------------------------------
# build_verified_answer fallback matrix
# ---------------------------------------------------------------------------

async def _drain(stream):
    return "".join([chunk async for chunk in stream])


@pytest.fixture(autouse=True)
def stub_context_formatters(monkeypatch):
    # Decouple these tests from format_search_context/format_course_context's
    # real field requirements - orchestration logic is what's under test here.
    monkeypatch.setattr(av, "format_search_context", lambda results: "SEARCH-CTX")
    monkeypatch.setattr(av, "format_course_context", lambda course: "COURSE-CTX")


@pytest.fixture(autouse=True)
def stub_comparison_notes(monkeypatch):
    # Autouse so every test in this file is decoupled from a real Groq call,
    # not just the ones that explicitly care about comparison notes - only
    # reached once both drafts succeed, but that's most of the fallback-
    # matrix tests below.
    async def fake_generate_comparison_notes(client, search_draft, course_draft, subject):
        return "comparison notes"

    monkeypatch.setattr(av, "generate_comparison_notes", fake_generate_comparison_notes)


def _fake_gather_ok(monkeypatch, search_draft="search draft", course_draft="course draft"):
    async def fake_generate_isolated_draft(client, messages, context_block, source_label, subject):
        return search_draft if source_label == "web search results" else course_draft

    monkeypatch.setattr(av, "generate_isolated_draft", fake_generate_isolated_draft)


@pytest.mark.asyncio
async def test_both_drafts_and_verify_succeed_returns_reasoning_and_verified_stream(monkeypatch):
    _fake_gather_ok(monkeypatch)

    async def fake_stream_verify_response(client, messages, subject, search_draft, course_draft, search_context, course_context, **kwargs):
        assert search_draft == "search draft"
        assert course_draft == "course draft"
        yield "Verified "
        yield "answer"

    monkeypatch.setattr(av, "stream_verify_response", fake_stream_verify_response)

    stream, reasoning = await av.build_verified_answer([], "DSA", ["result"], _course(materials=["m"]))

    assert reasoning == {
        "searchDraft": "search draft",
        "courseDraft": "course draft",
        "comparisonNotes": "comparison notes",
        "cachedDraft": None,
        "cachedQuery": None,
    }
    assert await _drain(stream) == "Verified answer"


@pytest.mark.asyncio
async def test_course_draft_fails_falls_back_to_search_only_no_reasoning(monkeypatch):
    async def fake_generate_isolated_draft(client, messages, context_block, source_label, subject):
        if source_label == "web search results":
            return "search draft"
        raise HTTPException(status_code=502, detail="course draft failed")

    monkeypatch.setattr(av, "generate_isolated_draft", fake_generate_isolated_draft)

    captured = {}

    async def fake_stream_groq_response(messages, context, subject):
        captured["context"] = context
        yield "fallback answer"

    monkeypatch.setattr(av, "stream_groq_response", fake_stream_groq_response)

    stream, reasoning = await av.build_verified_answer([], None, ["result"], _course(materials=["m"]))

    assert reasoning is None
    assert await _drain(stream) == "fallback answer"
    # Scoped to search context only, not the joined context - the course
    # draft never succeeded, so nothing course-related should leak in.
    assert captured["context"] == "SEARCH-CTX"


@pytest.mark.asyncio
async def test_empty_string_draft_is_treated_as_a_failure_not_a_success(monkeypatch):
    # Regression test: Groq can return HTTP 200 with an empty completion (a
    # very sparse context leaves the model nothing to say but a stop token).
    # generate_isolated_draft doesn't raise in that case - it just returns
    # "" - so a plain `isinstance(x, str)` success check would wrongly treat
    # a hollow draft as real and feed it into the comparison/verify prompts
    # instead of correctly falling back to the other source.
    async def fake_generate_isolated_draft(client, messages, context_block, source_label, subject):
        if source_label == "web search results":
            return "search draft"
        return ""  # course draft comes back empty, not raised

    monkeypatch.setattr(av, "generate_isolated_draft", fake_generate_isolated_draft)

    captured = {}

    async def fake_stream_groq_response(messages, context, subject):
        captured["context"] = context
        yield "fallback answer"

    monkeypatch.setattr(av, "stream_groq_response", fake_stream_groq_response)

    stream, reasoning = await av.build_verified_answer([], None, ["result"], _course(materials=["m"]))

    assert reasoning is None
    assert await _drain(stream) == "fallback answer"
    assert captured["context"] == "SEARCH-CTX"


@pytest.mark.asyncio
async def test_search_draft_fails_falls_back_to_course_only_no_reasoning(monkeypatch):
    async def fake_generate_isolated_draft(client, messages, context_block, source_label, subject):
        if source_label == "this course's materials":
            return "course draft"
        raise HTTPException(status_code=502, detail="search draft failed")

    monkeypatch.setattr(av, "generate_isolated_draft", fake_generate_isolated_draft)

    captured = {}

    async def fake_stream_groq_response(messages, context, subject):
        captured["context"] = context
        yield "fallback answer"

    monkeypatch.setattr(av, "stream_groq_response", fake_stream_groq_response)

    stream, reasoning = await av.build_verified_answer([], None, ["result"], _course(materials=["m"]))

    assert reasoning is None
    assert await _drain(stream) == "fallback answer"
    assert captured["context"] == "COURSE-CTX"


@pytest.mark.asyncio
async def test_both_drafts_fail_falls_back_to_joined_context_no_reasoning(monkeypatch):
    async def fake_generate_isolated_draft(client, messages, context_block, source_label, subject):
        raise HTTPException(status_code=502, detail="draft failed")

    monkeypatch.setattr(av, "generate_isolated_draft", fake_generate_isolated_draft)

    captured = {}

    async def fake_stream_groq_response(messages, context, subject):
        captured["context"] = context
        yield "fallback answer"

    monkeypatch.setattr(av, "stream_groq_response", fake_stream_groq_response)

    stream, reasoning = await av.build_verified_answer([], None, ["result"], _course(materials=["m"]))

    assert reasoning is None
    assert await _drain(stream) == "fallback answer"
    # Both sources joined - this is exactly today's pre-feature behavior.
    assert captured["context"] == "SEARCH-CTX\n\nCOURSE-CTX"


@pytest.mark.asyncio
async def test_verify_fails_before_first_chunk_falls_back_but_still_returns_reasoning(monkeypatch):
    # Both drafts are real, so the reasoning panel is worth showing even
    # though the merge step itself couldn't be reached - but the ANSWER text
    # must never be a raw, off-voice draft, so it falls back to the joined
    # single call instead.
    _fake_gather_ok(monkeypatch)

    async def fake_stream_verify_response(client, messages, subject, search_draft, course_draft, search_context, course_context, **kwargs):
        raise HTTPException(status_code=502, detail="verify unreachable")
        yield  # pragma: no cover - makes this an async generator function

    monkeypatch.setattr(av, "stream_verify_response", fake_stream_verify_response)

    captured = {}

    async def fake_stream_groq_response(messages, context, subject):
        captured["context"] = context
        yield "joined fallback answer"

    monkeypatch.setattr(av, "stream_groq_response", fake_stream_groq_response)

    stream, reasoning = await av.build_verified_answer([], None, ["result"], _course(materials=["m"]))

    assert reasoning == {
        "searchDraft": "search draft",
        "courseDraft": "course draft",
        "comparisonNotes": "comparison notes",
        "cachedDraft": None,
        "cachedQuery": None,
    }
    assert await _drain(stream) == "joined fallback answer"
    assert captured["context"] == "SEARCH-CTX\n\nCOURSE-CTX"


@pytest.mark.asyncio
async def test_verify_fails_after_first_chunk_propagates_instead_of_silently_falling_back(monkeypatch):
    # Once bytes are already on the wire, silently restarting with a
    # from-scratch fallback would look like two concatenated answers to the
    # student - this must propagate to chatRoute.py's own error handling
    # instead of being swallowed here.
    _fake_gather_ok(monkeypatch)

    async def fake_stream_verify_response(client, messages, subject, search_draft, course_draft, search_context, course_context, **kwargs):
        yield "partial "
        raise HTTPException(status_code=502, detail="verify died mid-stream")

    monkeypatch.setattr(av, "stream_verify_response", fake_stream_verify_response)

    stream, reasoning = await av.build_verified_answer([], None, ["result"], _course(materials=["m"]))
    assert reasoning == {
        "searchDraft": "search draft",
        "courseDraft": "course draft",
        "comparisonNotes": "comparison notes",
        "cachedDraft": None,
        "cachedQuery": None,
    }

    with pytest.raises(HTTPException):
        await _drain(stream)


@pytest.mark.asyncio
async def test_comparison_notes_failure_is_non_fatal_drafts_still_shown(monkeypatch):
    # The comparison-notes call is a nice-to-have on top of two drafts that
    # already succeeded - if it fails, the reasoning panel should just omit
    # it rather than losing the two real drafts too.
    _fake_gather_ok(monkeypatch)

    async def failing_comparison_notes(client, search_draft, course_draft, subject):
        raise HTTPException(status_code=502, detail="comparison notes failed")

    monkeypatch.setattr(av, "generate_comparison_notes", failing_comparison_notes)

    async def fake_stream_verify_response(client, messages, subject, search_draft, course_draft, search_context, course_context, **kwargs):
        yield "Verified answer"

    monkeypatch.setattr(av, "stream_verify_response", fake_stream_verify_response)

    stream, reasoning = await av.build_verified_answer([], None, ["result"], _course(materials=["m"]))

    assert reasoning == {"searchDraft": "search draft", "courseDraft": "course draft", "comparisonNotes": None, "cachedDraft": None, "cachedQuery": None}
    assert await _drain(stream) == "Verified answer"


@pytest.mark.asyncio
async def test_related_cached_search_becomes_a_third_draft_in_reasoning(monkeypatch):
    # The "third source" feature: a cheaply-found, loosely related prior
    # cached search becomes its own isolated draft and shows up in the
    # reasoning payload alongside the two always-present drafts, without
    # affecting the fallback matrix (it's purely additive).
    async def fake_generate_isolated_draft(client, messages, context_block, source_label, subject):
        if source_label == "web search results":
            return "search draft"
        if source_label == "this course's materials":
            return "course draft"
        return "cached draft"

    monkeypatch.setattr(av, "generate_isolated_draft", fake_generate_isolated_draft)

    captured = {}

    async def fake_stream_verify_response(client, messages, subject, search_draft, course_draft, search_context, course_context, **kwargs):
        captured.update(kwargs)
        yield "Verified answer"

    monkeypatch.setattr(av, "stream_verify_response", fake_stream_verify_response)

    related_cached = ("what is a related question", ["fake result"])
    stream, reasoning = await av.build_verified_answer(
        [], None, ["result"], _course(materials=["m"]), related_cached
    )

    assert reasoning == {
        "searchDraft": "search draft",
        "courseDraft": "course draft",
        "comparisonNotes": "comparison notes",
        "cachedDraft": "cached draft",
        "cachedQuery": "what is a related question",
    }
    assert await _drain(stream) == "Verified answer"
    assert captured["cached_draft"] == "cached draft"
    assert captured["cached_context"] == "SEARCH-CTX"
    assert captured["cached_query"] == "what is a related question"


@pytest.mark.asyncio
async def test_related_cached_draft_failure_is_non_fatal_other_drafts_unaffected(monkeypatch):
    _fake_gather_ok(monkeypatch)

    async def fake_generate_isolated_draft(client, messages, context_block, source_label, subject):
        if source_label == "web search results":
            return "search draft"
        if source_label == "this course's materials":
            return "course draft"
        raise HTTPException(status_code=502, detail="cached draft failed")

    monkeypatch.setattr(av, "generate_isolated_draft", fake_generate_isolated_draft)

    async def fake_stream_verify_response(client, messages, subject, search_draft, course_draft, search_context, course_context, **kwargs):
        assert kwargs["cached_draft"] is None
        yield "Verified answer"

    monkeypatch.setattr(av, "stream_verify_response", fake_stream_verify_response)

    related_cached = ("what is a related question", ["fake result"])
    stream, reasoning = await av.build_verified_answer(
        [], None, ["result"], _course(materials=["m"]), related_cached
    )

    assert reasoning["cachedDraft"] is None
    assert reasoning["cachedQuery"] is None
    assert await _drain(stream) == "Verified answer"


def test_cached_source_fits_budget_true_under_the_limit():
    assert av._cached_source_fits_budget("s", "c", [], "cached-context") is True


def test_cached_source_fits_budget_false_when_it_would_push_over_the_limit():
    huge = "x" * av._MAX_COMBINED_CONTEXT_CHARS_FOR_VERIFICATION
    assert av._cached_source_fits_budget(huge, "", [], "even one more char") is False


@pytest.mark.asyncio
async def test_cached_source_skipped_when_it_would_exceed_the_verification_budget(monkeypatch):
    # Regression test: find_related_cached_search() runs AFTER should_verify()
    # already passed, so its context was never counted in that first size
    # check - without a second check here, a combined context that's right
    # at the edge could tip over budget only once the third source is added.
    _fake_gather_ok(monkeypatch)
    draft_labels_called = []

    async def fake_generate_isolated_draft(client, messages, context_block, source_label, subject):
        draft_labels_called.append(source_label)
        if source_label == "web search results":
            return "search draft"
        if source_label == "this course's materials":
            return "course draft"
        return "cached draft"  # would only be reached if wrongly not skipped

    monkeypatch.setattr(av, "generate_isolated_draft", fake_generate_isolated_draft)

    async def fake_stream_verify_response(client, messages, subject, search_draft, course_draft, search_context, course_context, **kwargs):
        yield "Verified answer"

    monkeypatch.setattr(av, "stream_verify_response", fake_stream_verify_response)

    # stub_context_formatters (autouse) normally ignores its input and always
    # returns "SEARCH-CTX"/"COURSE-CTX" - overridden here so the related
    # (third-source) results specifically format to an oversized context,
    # while search/course results still format to the short stub strings.
    huge_related_results = ["oversized fake result"]

    def fake_format_search_context(results):
        if results is huge_related_results:
            return "x" * av._MAX_COMBINED_CONTEXT_CHARS_FOR_VERIFICATION
        return "SEARCH-CTX"

    monkeypatch.setattr(av, "format_search_context", fake_format_search_context)

    stream, reasoning = await av.build_verified_answer(
        [], None, ["result"], _course(materials=["m"]), ("a related question", huge_related_results)
    )
    await _drain(stream)

    assert reasoning["cachedDraft"] is None
    assert reasoning["cachedQuery"] is None
    assert not any("previously cached search" in label for label in draft_labels_called)


@pytest.mark.asyncio
async def test_cached_draft_call_never_made_when_a_primary_draft_fails(monkeypatch):
    # Regression test: the third source's Groq call must not fire at all
    # until the two always-present drafts are confirmed to have succeeded -
    # otherwise it's spent and thrown away in the fallback branches below.
    draft_labels_called = []

    async def fake_generate_isolated_draft(client, messages, context_block, source_label, subject):
        draft_labels_called.append(source_label)
        if source_label == "web search results":
            return "search draft"
        raise HTTPException(status_code=502, detail="course draft failed")

    monkeypatch.setattr(av, "generate_isolated_draft", fake_generate_isolated_draft)

    async def fake_stream_groq_response(messages, context, subject):
        yield "fallback answer"

    monkeypatch.setattr(av, "stream_groq_response", fake_stream_groq_response)

    related_cached = ("a related question", ["fake result"])
    stream, reasoning = await av.build_verified_answer(
        [], None, ["result"], _course(materials=["m"]), related_cached
    )
    await _drain(stream)

    assert reasoning is None
    # Only the two primary drafts were ever attempted - never the cached one.
    assert draft_labels_called == ["web search results", "this course's materials"]


@pytest.mark.asyncio
async def test_drafts_receive_only_the_latest_user_message_not_full_history(monkeypatch):
    # Regression test for the real production crash: sending the full
    # conversation history to BOTH isolated drafts was duplicating it twice
    # on top of what the verify call already sends, and was the single
    # biggest contributor to blowing through an org's 8000 TPM limit on a
    # long conversation. Drafts are never shown to the student directly, so
    # they don't need conversational continuity - just the latest question.
    captured_messages = []

    async def fake_generate_isolated_draft(client, messages, context_block, source_label, subject):
        captured_messages.append(messages)
        return "search draft" if source_label == "web search results" else "course draft"

    monkeypatch.setattr(av, "generate_isolated_draft", fake_generate_isolated_draft)

    async def fake_stream_verify_response(client, messages, subject, search_draft, course_draft, search_context, course_context, **kwargs):
        # The verify call, unlike the drafts, SHOULD still get full history -
        # that's the actual reply the student sees, continuity matters there.
        assert len(messages) == 3
        yield "Verified answer"

    monkeypatch.setattr(av, "stream_verify_response", fake_stream_verify_response)

    full_history = [
        Message(role="user", content="first question"),
        Message(role="assistant", content="first answer"),
        Message(role="user", content="second question"),
    ]

    stream, _ = await av.build_verified_answer(full_history, None, ["result"], _course(materials=["m"]))
    await _drain(stream)

    assert len(captured_messages) == 2
    for messages in captured_messages:
        assert len(messages) == 1
        assert messages[0].content == "second question"
        assert messages[0].role == "user"
