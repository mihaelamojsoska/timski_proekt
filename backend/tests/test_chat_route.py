"""Regression test for the SSE mid-stream failure fix in chatRoute.py.

Before this fix, any exception raised while iterating stream_groq_response()
(a Groq timeout, a 429, etc.) propagated out of the async generator after
HTTP 200 + headers were already sent - Starlette/uvicorn had no way to turn
that into a clean response, so the connection just died with no explanation,
and the partial reply that had already streamed to the client was never
saved (save_assistant_reply only ran after the loop completed normally).

Reproduced live with a real mid-stream 429 during development; this test
locks that fix in place going forward.
"""
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.database.models import ChatMessage, Conversation, Course, User
from backend.database.session import SessionLocal
from backend.main import app
from backend.models.searchResult import SearchResult
from backend.tests.conftest import auth_headers as make_auth_headers
from backend.tests.conftest import cleanup_test_data, register_and_login, unique_email

client = TestClient(app)
pytestmark = pytest.mark.bulk_register


@pytest.fixture
def auth_headers():
    email = "sse-regression-test@example.com"
    db = SessionLocal()
    db.query(User).filter(User.email == email).delete()
    db.commit()
    db.close()

    resp = client.post("/api/auth/register", json={"email": email, "password": "testpass123"})
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    yield headers

    # Delegates to conftest.py's cleanup_test_data rather than hand-rolling
    # deletes here - this fixture predates group chat, and its own manual
    # cleanup missed ConversationMember/ConversationInvite rows (a real gap
    # if this conversation ever picks up a member), which cleanup_test_data
    # already handles correctly in the right FK order.
    db = SessionLocal()
    cleanup_test_data(db, [email])
    db.close()


def test_mid_stream_failure_sends_error_frame_and_saves_partial_reply(auth_headers):
    async def fake_stream(*args, **kwargs):
        yield "Partial answer before "
        yield "it "
        raise HTTPException(status_code=429, detail="rate limited")

    with patch("backend.routes.chatRoute.stream_groq_response", fake_stream):
        with client.stream(
            "POST", "/api/chat", headers=auth_headers,
            json={"messages": [{"role": "user", "content": "test question"}], "search": False},
        ) as resp:
            body = b"".join(resp.iter_bytes()).decode()

    assert "event: error" in body
    assert "You're sending messages too fast" in body
    assert body.strip().endswith("data: [DONE]")

    db = SessionLocal()
    user = db.query(User).filter(User.email == "sse-regression-test@example.com").first()
    conv = db.query(Conversation).filter(Conversation.user_id == user.id).first()
    messages = db.query(ChatMessage).filter(ChatMessage.conversation_id == conv.id).order_by(ChatMessage.id).all()
    db.close()

    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].content == "Partial answer before it "


def test_mid_stream_generic_failure_uses_generic_message(auth_headers):
    async def fake_stream(*args, **kwargs):
        yield "Some text "
        raise RuntimeError("boom")

    with patch("backend.routes.chatRoute.stream_groq_response", fake_stream):
        with client.stream(
            "POST", "/api/chat", headers=auth_headers,
            json={"messages": [{"role": "user", "content": "another question"}], "search": False},
        ) as resp:
            body = b"".join(resp.iter_bytes()).decode()

    assert "event: error" in body
    assert "trouble responding" in body
    assert body.strip().endswith("data: [DONE]")


def test_mid_stream_413_rate_limit_uses_usage_limit_message(auth_headers):
    """Regression test: Groq returns 413 (not 429) for its per-minute TOKEN
    budget ("rate_limit_exceeded" error code, "request too large" message) -
    this used to fall through to the generic "had trouble responding"
    message, leaving a real production rate-limit failure looking like an
    unexplained bug instead of "try again in a bit"."""
    async def fake_stream(*args, **kwargs):
        raise HTTPException(
            status_code=413,
            detail='{"error":{"message":"Request too large...","type":"tokens","code":"rate_limit_exceeded"}}',
        )
        yield  # pragma: no cover - makes this an async generator function

    with patch("backend.routes.chatRoute.stream_groq_response", fake_stream):
        with client.stream(
            "POST", "/api/chat", headers=auth_headers,
            json={"messages": [{"role": "user", "content": "a question"}], "search": False},
        ) as resp:
            body = b"".join(resp.iter_bytes()).decode()

    assert "event: error" in body
    assert "usage limit" in body
    assert "trouble responding" not in body
    assert body.strip().endswith("data: [DONE]")


# ---------------------------------------------------- group-chat additions ----

def test_prompt_history_is_rebuilt_from_the_db_not_the_raw_request_payload():
    """Regression test for the group-chat concurrency fix: the messages sent
    to Groq must reflect what's actually saved in the conversation, not
    whatever (possibly stale) array the calling browser tab happened to send -
    see chat_service.py::get_message_history_for_model's docstring."""
    db = SessionLocal()
    email = unique_email("chat-rebuild")
    try:
        token = register_and_login(client, db, email)
        headers = make_auth_headers(token)

        async def first_turn(*args, **kwargs):
            yield "Hello there"

        with patch("backend.routes.chatRoute.stream_groq_response", first_turn):
            with client.stream(
                "POST", "/api/chat", headers=headers,
                json={"messages": [{"role": "user", "content": "Hi"}], "search": False},
            ) as resp:
                first_body = b"".join(resp.iter_bytes()).decode()

        conv_line = next(l for l in first_body.split("\n") if l.startswith("data: ") and '"id"' in l)
        conv_id = json.loads(conv_line[len("data: "):])["id"]

        seen_messages = []

        async def second_turn(messages, *args, **kwargs):
            seen_messages.extend(messages)
            yield "Second reply"

        # Deliberately send a request payload that OMITS the first turn's
        # history - simulating a stale client array - to prove the server
        # doesn't trust it.
        with patch("backend.routes.chatRoute.stream_groq_response", second_turn):
            with client.stream(
                "POST", "/api/chat", headers=headers,
                json={
                    "messages": [{"role": "user", "content": "New question"}],
                    "search": False,
                    "conversation_id": conv_id,
                },
            ) as resp:
                b"".join(resp.iter_bytes())

        assert [m.role for m in seen_messages] == ["user", "assistant", "user"]
        assert seen_messages[0].content == "Hi"
        assert seen_messages[1].content == "Hello there"
        assert seen_messages[2].content == "New question"
    finally:
        cleanup_test_data(db, [email])
        db.close()


def test_a_conversation_member_not_just_the_owner_can_chat():
    """POST /api/chat's resolve_conversation uses _get_member_conversation -
    an invited member (not just the owner) can post into a shared conversation."""
    db = SessionLocal()
    owner_email = unique_email("chat-member-owner")
    member_email = unique_email("chat-member-guest")
    try:
        owner_token = register_and_login(client, db, owner_email)
        member_token = register_and_login(client, db, member_email)

        async def first_turn(*args, **kwargs):
            yield "Hi there"

        with patch("backend.routes.chatRoute.stream_groq_response", first_turn):
            with client.stream(
                "POST", "/api/chat", headers=make_auth_headers(owner_token),
                json={"messages": [{"role": "user", "content": "Hello"}], "search": False},
            ) as resp:
                first_body = b"".join(resp.iter_bytes()).decode()
        conv_line = next(l for l in first_body.split("\n") if l.startswith("data: ") and '"id"' in l)
        conv_id = json.loads(conv_line[len("data: "):])["id"]

        invite_resp = client.post(
            f"/api/conversations/{conv_id}/invites", headers=make_auth_headers(owner_token)
        )
        assert invite_resp.status_code == 201, invite_resp.text
        token_str = invite_resp.json()["token"]
        accept_resp = client.post(
            f"/api/conversations/invites/{token_str}/accept", headers=make_auth_headers(member_token)
        )
        assert accept_resp.status_code == 200, accept_resp.text

        async def second_turn(*args, **kwargs):
            yield "Reply to the member"

        with patch("backend.routes.chatRoute.stream_groq_response", second_turn):
            with client.stream(
                "POST", "/api/chat", headers=make_auth_headers(member_token),
                json={
                    "messages": [{"role": "user", "content": "Hi from the member"}],
                    "search": False,
                    "conversation_id": conv_id,
                },
            ) as resp:
                body = b"".join(resp.iter_bytes()).decode()

        assert "event: error" not in body
        assert "Reply to the member" in body

        conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
        member_messages = [m for m in conv.messages if m.author_user_id is not None]
        assert any(m.content == "Hi from the member" for m in member_messages)
    finally:
        cleanup_test_data(db, [owner_email, member_email])
        db.close()


# ------------------------------------------ dual-source answer verification ----

def test_thinking_events_emitted_around_the_verification_pipeline():
    """When both live search and course context are available (see
    services/answer_verification.py::should_verify), the route should emit
    an `event: thinking` status before the drafts run and another right
    before the verify/merge stream starts, so the "Generating..." placeholder
    reflects the actual (longer) pipeline instead of sitting on generic text
    for 2-3x as long as a normal single-call answer."""
    db = SessionLocal()
    email = unique_email("chat-thinking-events")
    course = Course(slug=f"thinking-test-course-{email}", name="Thinking Test Course")
    db.add(course)
    db.commit()
    db.refresh(course)
    try:
        token = register_and_login(client, db, email)
        headers = make_auth_headers(token)

        async def fake_verified_stream():
            yield "Verified answer"

        async def fake_build_verified_answer(*args, **kwargs):
            # Both awaited in chatRoute.py - must be real coroutine
            # functions, not MagicMock(return_value=...), which can't be
            # awaited.
            return fake_verified_stream(), {"searchDraft": "sd", "courseDraft": "cd"}

        async def fake_get_or_search(*args, **kwargs):
            return [SearchResult(title="T", url="https://example.com", snippet="s")], False

        with patch("backend.services.answer_verification.should_verify", return_value=True), \
             patch("backend.services.answer_verification.build_verified_answer", fake_build_verified_answer), \
             patch("backend.routes.chatRoute.get_or_search", fake_get_or_search):
            with client.stream(
                "POST", "/api/chat", headers=headers,
                json={
                    "messages": [{"role": "user", "content": "test question"}],
                    "search": True,
                    "course_id": course.id,
                },
            ) as resp:
                body = b"".join(resp.iter_bytes()).decode()

        thinking_lines = [
            json.loads(l[len("data: "):])["status"]
            for l in body.split("\n")
            if l.startswith("data: ") and '"status"' in l
        ]
        assert thinking_lines == [
            "Checking web search results and course materials…",
            "Cross-checking both sources…",
        ]
        assert "event: reasoning" in body
        assert "Verified answer" in body
    finally:
        cleanup_test_data(db, [email])
        db.delete(course)
        db.commit()
        db.close()


def test_related_cached_search_looked_up_only_when_verifying_and_not_already_cached():
    """The cheap third-source lookup (find_related_cached_search - see
    services/search_cache.py) should only run when the verification pipeline
    is actually going to use it: verification enabled AND this turn's own
    search already went live (search_from_cache False) - reusing a cache hit
    for THIS question means there's nothing new that lookup could add."""
    db = SessionLocal()
    email = unique_email("chat-related-cache-lookup")
    course = Course(slug=f"related-cache-course-{email}", name="Related Cache Course")
    db.add(course)
    db.commit()
    db.refresh(course)
    try:
        token = register_and_login(client, db, email)
        headers = make_auth_headers(token)

        async def fake_verified_stream():
            yield "Verified answer"

        captured = {}

        async def fake_build_verified_answer(model_messages, subject, search_results, course, related_cached=None):
            captured["related_cached"] = related_cached
            return fake_verified_stream(), {"searchDraft": "sd", "courseDraft": "cd"}

        lookup_calls = []

        def fake_find_related_cached_search(db, question, subject):
            lookup_calls.append(question)
            return ("a related question", [SearchResult(title="T", url="https://example.com", snippet="s")])

        async def fake_get_or_search_live(*args, **kwargs):
            return [SearchResult(title="T", url="https://example.com", snippet="s")], False

        with patch("backend.services.answer_verification.should_verify", return_value=True), \
             patch("backend.services.answer_verification.build_verified_answer", fake_build_verified_answer), \
             patch("backend.routes.chatRoute.get_or_search", fake_get_or_search_live), \
             patch("backend.routes.chatRoute.find_related_cached_search", fake_find_related_cached_search):
            with client.stream(
                "POST", "/api/chat", headers=headers,
                json={
                    "messages": [{"role": "user", "content": "a live-search question"}],
                    "search": True,
                    "course_id": course.id,
                },
            ) as resp:
                b"".join(resp.iter_bytes())

        assert lookup_calls == ["a live-search question"]
        assert captured["related_cached"] == (
            "a related question", [SearchResult(title="T", url="https://example.com", snippet="s")]
        )
    finally:
        cleanup_test_data(db, [email])
        db.delete(course)
        db.commit()
        db.close()


def test_related_cached_search_not_looked_up_when_this_turns_search_was_itself_cached():
    db = SessionLocal()
    email = unique_email("chat-related-cache-skip")
    course = Course(slug=f"related-cache-skip-course-{email}", name="Related Cache Skip Course")
    db.add(course)
    db.commit()
    db.refresh(course)
    try:
        token = register_and_login(client, db, email)
        headers = make_auth_headers(token)

        async def fake_verified_stream():
            yield "Verified answer"

        async def fake_build_verified_answer(model_messages, subject, search_results, course, related_cached=None):
            return fake_verified_stream(), {"searchDraft": "sd", "courseDraft": "cd"}

        lookup_calls = []

        def fake_find_related_cached_search(db, question, subject):
            lookup_calls.append(question)
            return None

        async def fake_get_or_search_cached(*args, **kwargs):
            return [SearchResult(title="T", url="https://example.com", snippet="s")], True

        with patch("backend.services.answer_verification.should_verify", return_value=True), \
             patch("backend.services.answer_verification.build_verified_answer", fake_build_verified_answer), \
             patch("backend.routes.chatRoute.get_or_search", fake_get_or_search_cached), \
             patch("backend.routes.chatRoute.find_related_cached_search", fake_find_related_cached_search):
            with client.stream(
                "POST", "/api/chat", headers=headers,
                json={
                    "messages": [{"role": "user", "content": "a cached-search question"}],
                    "search": True,
                    "course_id": course.id,
                },
            ) as resp:
                b"".join(resp.iter_bytes())

        assert lookup_calls == []
    finally:
        cleanup_test_data(db, [email])
        db.delete(course)
        db.commit()
        db.close()


# --------------------------------------------------------- search cache meta ----

def test_search_meta_event_reflects_cache_hit(auth_headers):
    """get_or_search returns (results, from_cache) - chatRoute.py used to
    discard the from_cache flag entirely (`search_results, _ = ...`), leaving
    students unable to tell a cached search from a fresh live one. It's now
    forwarded as a separate `event: searchMeta` frame alongside `event:
    sources` (see SourcesSidebar's "From cached search" pill)."""
    async def fake_stream(*args, **kwargs):
        yield "An answer"

    async def fake_cached_search(*args, **kwargs):
        return [SearchResult(title="T", url="https://example.com", snippet="s")], True

    with patch("backend.routes.chatRoute.stream_groq_response", fake_stream), \
         patch("backend.routes.chatRoute.get_or_search", fake_cached_search):
        with client.stream(
            "POST", "/api/chat", headers=auth_headers,
            json={"messages": [{"role": "user", "content": "cached question"}], "search": True},
        ) as resp:
            body = b"".join(resp.iter_bytes()).decode()

    assert "event: searchMeta" in body
    meta_line = next(l for l in body.split("\n") if l.startswith("data: ") and "fromCache" in l)
    assert json.loads(meta_line[len("data: "):]) == {"fromCache": True}


def test_search_meta_event_absent_when_search_disabled(auth_headers):
    async def fake_stream(*args, **kwargs):
        yield "An answer"

    with patch("backend.routes.chatRoute.stream_groq_response", fake_stream):
        with client.stream(
            "POST", "/api/chat", headers=auth_headers,
            json={"messages": [{"role": "user", "content": "no search here"}], "search": False},
        ) as resp:
            body = b"".join(resp.iter_bytes()).decode()

    assert "event: searchMeta" not in body
