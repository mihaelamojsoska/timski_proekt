"""Tests for backend/ai/chat.py - prompt construction, course-context
threading through generate_quiz/generate_summary/generate_explore_queries/
generate_followups/stream_groq_response, and two regression guards:

1. GROQ_MODEL must never silently revert to a retired model - this project
   already broke in production once (llama-3.3-70b-versatile was pulled from
   Groq's catalog, see the comment above GROQ_MODEL in chat.py).
2. SYSTEM_PROMPT must keep the anti-fabrication rule - found via manual
   testing that the AI padded a real 3-item materials list with 2 invented
   ones; the fix was purely a prompt change, easy to silently lose in a
   future edit without a test catching it.

No real network calls are made - httpx.AsyncClient.post/.stream are
monkeypatched at the class level for each test.
"""
import json

import httpx
import pytest
from fastapi import HTTPException

from backend.ai import chat as ai_chat
from backend.models.message import Message


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", lines=None):
        self.status_code = status_code
        self._json_data = json_data
        self.text = text
        self._lines = lines or []

    def json(self):
        return self._json_data

    async def aread(self):
        return self.text.encode()

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCM:
    """Mimics the async context manager httpx.AsyncClient.stream() returns."""

    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc_info):
        return False


def _groq_completion_payload(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture(autouse=True)
def fake_groq_key(monkeypatch):
    # Every function under test bails early with a 500 if this is falsy.
    monkeypatch.setattr(ai_chat, "GROQ_API_KEY", "test-key")


def test_system_prompt_forbids_fabricated_resources():
    assert "NEVER invent" in ai_chat.SYSTEM_PROMPT
    assert "fabricate" in ai_chat.SYSTEM_PROMPT.lower()


def test_groq_model_is_not_the_retired_model():
    assert ai_chat.GROQ_MODEL != "llama-3.3-70b-versatile"
    assert ai_chat.GROQ_MODEL


@pytest.mark.asyncio
async def test_generate_quiz_sends_configured_model_and_course_context(monkeypatch):
    captured = {}

    async def fake_post(self, url, headers=None, json=None):
        captured["json"] = json
        return _FakeResponse(200, _groq_completion_payload(
            '{"topic": "T", "questions": []}'
        ))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await ai_chat.generate_quiz(
        [Message(role="user", content="teach me recursion")],
        subject="DSA",
        course_context="## Course Context: Test Course\n- Recursion",
    )

    assert result == {"topic": "T", "questions": []}
    assert captured["json"]["model"] == ai_chat.GROQ_MODEL
    prompt = captured["json"]["messages"][0]["content"]
    assert "## Course Context: Test Course" in prompt
    assert "DSA" in prompt


@pytest.mark.asyncio
async def test_generate_quiz_from_topic_sends_bare_topic_prompt(monkeypatch):
    captured = {}

    async def fake_post(self, url, headers=None, json=None):
        captured["json"] = json
        return _FakeResponse(200, _groq_completion_payload(
            '{"topic": "Recursion", "questions": []}'
        ))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await ai_chat.generate_quiz_from_topic("Recursion", subject="DSA")

    assert result == {"topic": "Recursion", "questions": []}
    prompt = captured["json"]["messages"][0]["content"]
    assert "TOPIC: Recursion" in prompt
    assert "DSA" in prompt


@pytest.mark.asyncio
async def test_generate_quiz_strips_markdown_fences(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(200, _groq_completion_payload(
            '```json\n{"topic": "T", "questions": []}\n```'
        ))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await ai_chat.generate_quiz([Message(role="user", content="hi")], subject=None)
    assert result == {"topic": "T", "questions": []}


@pytest.mark.asyncio
async def test_generate_quiz_raises_on_groq_error(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(429, text="rate limited")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(HTTPException) as exc_info:
        await ai_chat.generate_quiz([Message(role="user", content="hi")], subject=None)
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_generate_summary_includes_course_context(monkeypatch):
    captured = {}

    async def fake_post(self, url, headers=None, json=None):
        captured["json"] = json
        return _FakeResponse(200, _groq_completion_payload("A summary"))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await ai_chat.generate_summary(
        [Message(role="user", content="hi")], subject=None, course_context="COURSE-MARKER"
    )
    assert result == {"summary": "A summary"}
    assert "COURSE-MARKER" in captured["json"]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_generate_explore_queries_includes_course_context_and_caps_at_3(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):
        assert "COURSE-MARKER" in json["messages"][0]["content"]
        return _FakeResponse(200, _groq_completion_payload('["q1", "q2", "q3", "q4"]'))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    queries = await ai_chat.generate_explore_queries(
        [Message(role="user", content="hi")], subject=None, course_context="COURSE-MARKER"
    )
    assert queries == ["q1", "q2", "q3"]


@pytest.mark.asyncio
async def test_generate_followups_returns_empty_list_on_malformed_json(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(200, _groq_completion_payload("not valid json"))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    questions = await ai_chat.generate_followups([Message(role="user", content="hi")], subject=None)
    assert questions == []


# ---------------------------------------------------------------------------
# _fit_to_token_budget - the plain path's own last-resort size safety net,
# independent of services/answer_verification.py's gate (which only ever
# protected the multi-call verification pipeline, never this path - see this
# function's own docstring).
# ---------------------------------------------------------------------------

def test_fit_to_token_budget_is_a_noop_under_budget():
    messages = [Message(role="user", content="a short question")]
    trimmed_messages, trimmed_context = ai_chat._fit_to_token_budget(messages, "a short context block")
    assert trimmed_messages == messages
    assert trimmed_context == "a short context block"


def test_fit_to_token_budget_truncates_oversized_context_before_touching_history():
    messages = [Message(role="user", content="a short question")]
    huge_context = "x" * (ai_chat._MAX_PLAIN_CALL_CONTEXT_CHARS + 5000)
    trimmed_messages, trimmed_context = ai_chat._fit_to_token_budget(messages, huge_context)
    assert trimmed_messages == messages  # history untouched - context alone was the problem
    assert len(trimmed_context) < len(huge_context)
    assert "truncated" in trimmed_context


def test_fit_to_token_budget_drops_oldest_history_when_context_alone_cant_fix_it():
    # No context at all - the oversized history itself must be trimmed.
    messages = [
        Message(role="user", content="x" * (ai_chat._MAX_PLAIN_CALL_CONTEXT_CHARS // 2)),
        Message(role="assistant", content="y" * (ai_chat._MAX_PLAIN_CALL_CONTEXT_CHARS // 2)),
        Message(role="user", content="the latest question"),
    ]
    trimmed_messages, trimmed_context = ai_chat._fit_to_token_budget(messages, "")
    assert trimmed_context == ""
    # The oldest message(s) were dropped, but the latest is always kept.
    assert trimmed_messages[-1].content == "the latest question"
    assert len(trimmed_messages) < len(messages)


def test_fit_to_token_budget_always_keeps_at_least_the_latest_message():
    # Even a single message larger than the whole budget must survive -
    # there has to be something to send the model, however oversized.
    messages = [Message(role="user", content="x" * (ai_chat._MAX_PLAIN_CALL_CONTEXT_CHARS * 3))]
    trimmed_messages, _ = ai_chat._fit_to_token_budget(messages, "")
    assert len(trimmed_messages) == 1


@pytest.mark.asyncio
async def test_stream_groq_response_applies_the_budget_fit_before_sending(monkeypatch):
    captured = {}
    sse_lines = ["data: [DONE]"]

    def fake_stream(self, method, url, headers=None, json=None):
        captured["json"] = json
        return _FakeStreamCM(_FakeResponse(200, lines=sse_lines))

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)

    huge_context = "x" * (ai_chat._MAX_PLAIN_CALL_CONTEXT_CHARS + 5000)
    async for _ in ai_chat.stream_groq_response(
        [Message(role="user", content="hi")], context=huge_context, subject=None
    ):
        pass

    system_message = captured["json"]["messages"][0]["content"]
    assert "truncated" in system_message
    assert len(system_message) < len(huge_context)


@pytest.mark.asyncio
async def test_stream_groq_response_injects_course_context_and_uses_configured_model(monkeypatch):
    captured = {}
    sse_lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": "Hello "}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "world"}}]}),
        "data: [DONE]",
    ]

    def fake_stream(self, method, url, headers=None, json=None):
        captured["json"] = json
        return _FakeStreamCM(_FakeResponse(200, lines=sse_lines))

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)

    chunks = []
    async for chunk in ai_chat.stream_groq_response(
        [Message(role="user", content="hi")], context="COURSE-MARKER", subject="DSA"
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "Hello world"
    assert captured["json"]["model"] == ai_chat.GROQ_MODEL
    system_message = captured["json"]["messages"][0]["content"]
    assert "COURSE-MARKER" in system_message
    assert "DSA" in system_message


@pytest.mark.asyncio
async def test_stream_groq_response_raises_on_non_200(monkeypatch):
    def fake_stream(self, method, url, headers=None, json=None):
        return _FakeStreamCM(_FakeResponse(429, text="rate limited"))

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)

    with pytest.raises(HTTPException) as exc_info:
        async for _ in ai_chat.stream_groq_response(
            [Message(role="user", content="hi")], context="", subject=None
        ):
            pass
    assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# Dual-source answer verification (see services/answer_verification.py) -
# the isolated single-source draft call and the final verify/merge call.
# ---------------------------------------------------------------------------

def test_draft_model_is_configured_and_distinct_from_the_main_model():
    # Regression guard: the whole point of DRAFT_MODEL is to be a cheaper/
    # faster sibling used only for the two intermediate drafts - if it's
    # ever silently set equal to GROQ_MODEL (or emptied), the pipeline still
    # "works" but the cost-saving the model choice was for silently vanishes.
    assert ai_chat.DRAFT_MODEL
    assert ai_chat.DRAFT_MODEL != ai_chat.GROQ_MODEL


def test_answer_max_tokens_is_deliberately_bounded():
    # Regression guard for a real production incident: Groq charges a
    # request's *reserved* max_tokens against its per-minute token budget
    # regardless of actual output length, so raising this back toward the
    # old 4096 risks reintroducing the 413 rate-limit crash this value was
    # lowered to fix (see this constant's own docstring in ai/chat.py).
    # Bounded on both sides: also flags an accidental further cut that would
    # make ordinary long answers truncate even more aggressively than the
    # already-accepted tradeoff.
    assert 1000 <= ai_chat._ANSWER_MAX_TOKENS <= 2500
    assert ai_chat._ANSWER_MAX_TOKENS == 1800


def test_verify_system_prompt_composes_rather_than_rewrites_system_prompt():
    # Must contain SYSTEM_PROMPT verbatim, not a hand-copied second version -
    # otherwise the two drift out of sync the next time SYSTEM_PROMPT changes.
    assert ai_chat.SYSTEM_PROMPT in ai_chat.VERIFY_SYSTEM_PROMPT
    assert "NEVER invent" in ai_chat.VERIFY_SYSTEM_PROMPT


def test_verify_system_prompt_instructs_dropping_unsupported_claims():
    prompt = ai_chat.VERIFY_SYSTEM_PROMPT.lower()
    assert "neither context block" in prompt or "unsupported is unsupported" in prompt


def test_isolated_draft_prompt_forbids_outside_knowledge():
    prompt = ai_chat._isolated_draft_system_prompt("this course's materials").lower()
    assert "only" in prompt
    assert "outside knowledge" in prompt or "training knowledge" in prompt


@pytest.mark.asyncio
async def test_generate_isolated_draft_uses_draft_model_and_only_given_context(monkeypatch):
    captured = {}

    async def fake_post(self, url, headers=None, json=None):
        captured["json"] = json
        return _FakeResponse(200, _groq_completion_payload("Draft answer"))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with httpx.AsyncClient() as client:
        result = await ai_chat.generate_isolated_draft(
            client,
            [Message(role="user", content="what is a hash table?")],
            context_block="SEARCH-CONTEXT-MARKER",
            source_label="web search results",
            subject="DSA",
        )

    assert result == "Draft answer"
    assert captured["json"]["model"] == ai_chat.DRAFT_MODEL
    system_message = captured["json"]["messages"][0]["content"]
    assert "SEARCH-CONTEXT-MARKER" in system_message
    assert "web search results" in system_message
    assert "DSA" in system_message


@pytest.mark.asyncio
async def test_generate_isolated_draft_raises_on_groq_error(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(429, text="rate limited")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with httpx.AsyncClient() as client:
        with pytest.raises(HTTPException) as exc_info:
            await ai_chat.generate_isolated_draft(
                client, [Message(role="user", content="hi")], "ctx", "web search results", None
            )
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_generate_comparison_notes_uses_draft_model_and_includes_both_drafts(monkeypatch):
    captured = {}

    async def fake_post(self, url, headers=None, json=None):
        captured["json"] = json
        return _FakeResponse(200, _groq_completion_payload("- They agree on X\n- They conflict on Y"))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with httpx.AsyncClient() as client:
        result = await ai_chat.generate_comparison_notes(
            client,
            search_draft="SEARCH-DRAFT-MARKER",
            course_draft="COURSE-DRAFT-MARKER",
            subject="DSA",
        )

    assert result == "- They agree on X\n- They conflict on Y"
    assert captured["json"]["model"] == ai_chat.DRAFT_MODEL
    prompt = captured["json"]["messages"][0]["content"]
    assert "SEARCH-DRAFT-MARKER" in prompt
    assert "COURSE-DRAFT-MARKER" in prompt
    assert "DSA" in prompt


@pytest.mark.asyncio
async def test_generate_comparison_notes_raises_on_groq_error(monkeypatch):
    async def fake_post(self, url, headers=None, json=None):
        return _FakeResponse(429, text="rate limited")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    async with httpx.AsyncClient() as client:
        with pytest.raises(HTTPException) as exc_info:
            await ai_chat.generate_comparison_notes(client, "sd", "cd", None)
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_stream_verify_response_includes_both_drafts_and_both_contexts(monkeypatch):
    captured = {}
    sse_lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": "Final "}}]}),
        "data: " + json.dumps({"choices": [{"delta": {"content": "answer"}}]}),
        "data: [DONE]",
    ]

    def fake_stream(self, method, url, headers=None, json=None):
        captured["json"] = json
        return _FakeStreamCM(_FakeResponse(200, lines=sse_lines))

    monkeypatch.setattr(httpx.AsyncClient, "stream", fake_stream)

    async with httpx.AsyncClient() as client:
        chunks = []
        async for chunk in ai_chat.stream_verify_response(
            client,
            [Message(role="user", content="what is a hash table?")],
            subject="DSA",
            search_draft="SEARCH-DRAFT-MARKER",
            course_draft="COURSE-DRAFT-MARKER",
            search_context="SEARCH-CTX-MARKER",
            course_context="COURSE-CTX-MARKER",
        ):
            chunks.append(chunk)

    assert "".join(chunks) == "Final answer"
    assert captured["json"]["model"] == ai_chat.GROQ_MODEL
    system_message = captured["json"]["messages"][0]["content"]
    for marker in (
        "SEARCH-DRAFT-MARKER",
        "COURSE-DRAFT-MARKER",
        "SEARCH-CTX-MARKER",
        "COURSE-CTX-MARKER",
        "what is a hash table?",
    ):
        assert marker in system_message
