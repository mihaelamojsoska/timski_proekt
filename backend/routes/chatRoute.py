import json
import logging
from typing import Optional

from fastapi import HTTPException, APIRouter, Depends
from sqlalchemy.orm import Session

from backend.ai.chat import stream_groq_response, generate_quiz, generate_explore_queries, \
    generate_summary, generate_followups  # Changed import
from backend.database.models import Course, User
from backend.database.session import get_db
from backend.middleware.auth import get_current_user
from backend.models.QuizRequest import QuizRequest
from backend.models.askMoreRequest import AskMoreRequest
from backend.models.chatRequest import ChatRequest
from backend.models.exploreRequest import ExploreRequest
from backend.models.summaryRequest import SummaryRequest
from backend.services.chat_service import (
    get_message_history_for_model,
    resolve_conversation,
    save_assistant_reply,
    save_user_message,
)
from backend.services import answer_verification
from backend.services.chat_state import start_generating, stop_generating
from backend.services.course_context import format_course_context
from backend.services.search_cache import find_related_cached_search, get_or_search, get_or_search_many
from backend.web_search.search import format_search_context
from config import GROQ_API_KEY, TAVILY_API_KEY
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_course(db: Session, course_id: Optional[int]) -> Optional[Course]:
    """Look up a course by id, or None for a missing/invalid course_id."""
    if not course_id:
        return None
    return db.query(Course).filter(Course.id == course_id).first()


def _get_course_context(db: Session, course_id: Optional[int]) -> str:
    """Look up a course by id (if given) and format it into a context block.
    Silently returns "" for a missing/invalid course_id - course context is
    optional enrichment, not something that should ever 400/404 the request."""
    return format_course_context(_get_course(db, course_id))

@router.post("/api/chat")
async def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Main chat endpoint. Optionally searches the web for context before answering.
    Streams the response back as Server-Sent Events (SSE), and persists both the
    user message and the AI reply to the owning conversation.
    """
    if not GROQ_API_KEY:
        raise HTTPException(status_code=500, detail="GROQ_API_KEY not set")

    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # Get the latest user message for search + persistence
    latest_user_msg = next(
        (m.content for m in reversed(request.messages) if m.role == "user"), ""
    )

    # Resolve (or create) the conversation this exchange belongs to
    conversation = resolve_conversation(db, request, current_user, latest_user_msg)

    if latest_user_msg:
        save_user_message(db, conversation, latest_user_msg, current_user.id)

    # Rebuilt from the DB, not request.messages - see get_message_history_for_model's
    # docstring for why (a stale client-side transcript is a real risk once
    # more than one member can post into the same conversation).
    model_messages = get_message_history_for_model(db, conversation)

    # Capture plain values before the request-scoped DB session closes.
    # (The `db` session from Depends(get_db) is closed as soon as this function
    # returns the StreamingResponse - it does NOT stay open for the duration of
    # the stream. Touching `conversation.*` or `db` inside event_stream() below
    # would raise a DetachedInstanceError, so we only use plain vars there and
    # open a brand new session for the final save.)
    conv_id = conversation.id
    conv_title = conversation.title
    conv_issue_no = conversation.issue_no

    # Web search for context - served from the cache when a similar question was
    # already searched before, otherwise a live Tavily call (see services/search_cache.py)
    search_results = []
    search_from_cache = False
    if request.search and TAVILY_API_KEY and latest_user_msg:
        search_results, search_from_cache = await get_or_search(db, latest_user_msg, request.subject)

    # Compose the search-cache context with the optional course-syllabus context
    # (see backend/services/course_context.py) - both are plain context blocks,
    # concatenated the same way format_search_context's own sections are.
    course = _get_course(db, request.course_id)
    course_context = format_course_context(course)
    context = "\n\n".join(c for c in (format_search_context(search_results), course_context) if c)

    # Gated on both sources genuinely being available for THIS question - see
    # services/answer_verification.py. Decided here (course still attached to
    # the open db session) rather than inside event_stream(), since that
    # generator runs after the session closes below.
    use_verification = answer_verification.should_verify(search_results, course, context, model_messages)

    # Optional third source for the verification pipeline: a previously
    # cached search loosely related to this question, found cheaply (no live
    # search call - see find_related_cached_search's docstring). Only worth
    # checking when this turn's own search already went live (search_from_cache
    # False) - otherwise that same cache entry already IS search_results
    # above, so there'd be nothing new to add.
    related_cached = None
    if use_verification and not search_from_cache and latest_user_msg:
        related_cached = find_related_cached_search(db, latest_user_msg, request.subject)

    async def event_stream():
        # First let the UI know which conversation this belongs to (important
        # when a new one was just created, so the frontend can select it)
        conv_payload = json.dumps({"id": conv_id, "title": conv_title, "issue_no": conv_issue_no})
        yield f"event: conversation\ndata: {conv_payload}\n\n"

        # Then emit the search sources so the UI can show them, plus whether
        # they came from the search cache (see services/search_cache.py) or a
        # fresh live Tavily call - a separate event rather than folding into
        # the sources payload above so the existing plain-array shape (and
        # everything already parsing it) doesn't need to change.
        if search_results:
            sources_payload = json.dumps([
                {"title": r.title, "url": r.url} for r in search_results
            ])
            yield f"event: sources\ndata: {sources_payload}\n\n"
            yield f"event: searchMeta\ndata: {json.dumps({'fromCache': search_from_cache})}\n\n"

        # Then stream the AI response, accumulating the full text so we can save it.
        # This whole block is wrapped in try/except: by the time we're here, the
        # HTTP 200 + headers have already been sent (StreamingResponse consumes
        # this generator after starting the response), so a raw exception here
        # can't become a clean HTTP error - it just kills the connection with no
        # explanation and silently drops whatever the user's message was left
        # without a reply. Instead we emit an `event: error` frame the frontend
        # can render, and still persist whatever partial text was generated.
        full_response = ""
        start_generating(conv_id)  # advisory only - lets other members' polling show "generating"
        try:
            if use_verification:
                # Two drafts + a verify call take noticeably longer than the
                # single-call path below - these fill the "Generating..."
                # placeholder with what's actually happening instead of a
                # generic spinner sitting still for 2-3x as long. Timed at
                # the two real await boundaries below, not on a fake clock:
                # the first shows while both drafts are being generated
                # concurrently, the second right as the verify call starts.
                yield f"event: thinking\ndata: {json.dumps({'status': 'Checking web search results and course materials…'})}\n\n"
                chunk_stream, reasoning = await answer_verification.build_verified_answer(
                    model_messages, request.subject, search_results, course, related_cached
                )
                if reasoning:
                    yield f"event: reasoning\ndata: {json.dumps(reasoning)}\n\n"
                    yield f"event: thinking\ndata: {json.dumps({'status': 'Cross-checking both sources…'})}\n\n"
            else:
                chunk_stream = stream_groq_response(model_messages, context, request.subject)

            async for chunk in chunk_stream:
                full_response += chunk
                yield f"data: {json.dumps(chunk)}\n\n"
        except Exception as exc:
            logger.exception("Groq streaming failed for conversation %s", conv_id)
            detail_text = str(exc.detail) if isinstance(exc, HTTPException) else ""
            # Groq returns 429 for "too many requests", but also uses 413
            # ("request too large") for hitting its per-minute TOKEN budget
            # (see its "rate_limit_exceeded" error code) - both are the same
            # user-facing situation (wait a bit, try again), so both get the
            # same message instead of 413 falling through to the generic one.
            if isinstance(exc, HTTPException) and exc.status_code == 429:
                message = "You're sending messages too fast - please wait a moment and try again."
            elif isinstance(exc, HTTPException) and (
                exc.status_code == 413 or "rate_limit" in detail_text.lower()
            ):
                message = "The AI tutor is at its usage limit for the moment - please wait about a minute and try again."
            else:
                message = "The AI tutor had trouble responding. Please try again."
            yield f"event: error\ndata: {json.dumps({'message': message})}\n\n"
        finally:
            stop_generating(conv_id)
            if full_response:
                save_assistant_reply(conv_id, full_response)

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.post("/api/quiz")
async def quiz(
    request: QuizRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a quiz from the current conversation."""
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages to base quiz on")
    course_context = _get_course_context(db, request.course_id)
    result = await generate_quiz(request.messages, request.subject, course_context)
    return result

@router.post("/api/summary")
async def summary(
    request: SummaryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a study summary from the conversation."""
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages to summarize")
    course_context = _get_course_context(db, request.course_id)
    result = await generate_summary(request.messages, request.subject, course_context)
    return result


@router.post("/api/explore")
async def explore(
    request: ExploreRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Find related links based on the conversation topic."""
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages to explore from")
    if not TAVILY_API_KEY:
        raise HTTPException(status_code=500, detail="TAVILY_API_KEY not set")

    course_context = _get_course_context(db, request.course_id)
    queries = await generate_explore_queries(request.messages, request.subject, course_context)
    if not queries:
        raise HTTPException(status_code=500, detail="Could not generate explore queries")

    results = await get_or_search_many(db, queries, request.subject, num_results=3)
    return {
        "queries": queries,
        "links": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results[:9]]
    }

@router.post("/api/ask-more")
async def ask_more(
    request: AskMoreRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Suggest follow-up questions based on the conversation."""
    if not request.messages:
        raise HTTPException(status_code=400, detail="No messages to base follow-ups on")
    course_context = _get_course_context(db, request.course_id)
    questions = await generate_followups(request.messages, request.subject, course_context)
    if not questions:
        raise HTTPException(status_code=500, detail="Could not generate follow-up questions")
    return {"questions": questions}