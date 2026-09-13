import re
from datetime import timedelta
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.database.models import CachedSearch
from backend.models.searchResult import SearchResult
from backend.utils.time import utcnow
from backend.web_search.search import build_search_query, web_search

# Similarity threshold for the pg_trgm fuzzy-match fallback (0..1, higher = stricter).
# Tune empirically once real usage data comes in.
SIMILARITY_THRESHOLD = 0.35

# Looser threshold used only by find_related_cached_search() below - deliberately
# below SIMILARITY_THRESHOLD, since anything at or above that would already have
# been picked up as this turn's primary search result by get_or_search() itself.
RELATED_SIMILARITY_THRESHOLD = 0.15

# Study-content search results don't go stale on a clock the way news does, but we
# still refresh occasionally in case docs have moved/changed.
STALE_AFTER = timedelta(days=90)


def normalize_query(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace - used as the cache key."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def find_cached(db: Session, question: str, subject: Optional[str]) -> Optional[CachedSearch]:
    """Look up a cached entry for this question: exact normalized match first (cheap,
    index-only), then a pg_trgm similarity fallback for near-duplicate phrasing."""
    normalized = normalize_query(question)
    if not normalized:
        return None

    q = db.query(CachedSearch).filter(CachedSearch.normalized_query == normalized)
    q = q.filter(CachedSearch.subject == subject) if subject else q.filter(CachedSearch.subject.is_(None))
    exact = q.first()
    if exact:
        return exact

    similarity = func.similarity(CachedSearch.normalized_query, normalized)
    q = db.query(CachedSearch).filter(similarity >= SIMILARITY_THRESHOLD)
    q = q.filter(CachedSearch.subject == subject) if subject else q.filter(CachedSearch.subject.is_(None))
    return q.order_by(similarity.desc()).first()


def _serialize(results: List[SearchResult]) -> list:
    return [r.model_dump() for r in results]


def _to_search_results(raw: list) -> List[SearchResult]:
    return [SearchResult(**item) for item in raw]


def _record_hit(db: Session, entry: CachedSearch) -> None:
    entry.hit_count += 1
    entry.last_used_at = utcnow()
    db.commit()


def _create(
    db: Session, question: str, subject: Optional[str], raw_query: str, results: List[SearchResult]
) -> CachedSearch:
    entry = CachedSearch(
        subject=subject,
        normalized_query=normalize_query(question),
        raw_query=raw_query,
        results=_serialize(results),
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


async def get_or_search(
    db: Session, question: str, subject: Optional[str], num_results: int = 5
) -> Tuple[List[SearchResult], bool]:
    """Main entry point: return (results, from_cache). Cache hit -> bump hit_count/
    last_used_at (transparently re-searching if the entry is older than STALE_AFTER);
    cache miss -> live Tavily search, persist a new row, return fresh results."""
    entry = find_cached(db, question, subject)

    if entry:
        if utcnow() - entry.last_refreshed_at > STALE_AFTER:
            fresh_results = await web_search(entry.raw_query, num_results=num_results)
            if fresh_results:
                entry.results = _serialize(fresh_results)
                entry.last_refreshed_at = utcnow()
        _record_hit(db, entry)
        return _to_search_results(entry.results), True

    query = build_search_query(question, subject)
    results = await web_search(query, num_results=num_results)
    if results:
        _create(db, question, subject, query, results)
    return results, False


def find_related_cached_search(
    db: Session, question: str, subject: Optional[str]
) -> Optional[Tuple[str, List[SearchResult]]]:
    """Cheap, DB-only lookup (no live search call) for a previously cached
    search loosely related to this question - only meant to be called after
    get_or_search() already went live for THIS question (i.e. nothing at or
    above SIMILARITY_THRESHOLD matched, or that entry would already be this
    turn's primary search result). Used to offer an optional third "cached
    web search" source to cross-check against in the answer-verification
    pipeline (see services/answer_verification.py) - purely additive, never
    replaces the primary get_or_search() result, and costs nothing but a
    trigram similarity query since it never calls the live search API.

    Deliberately bounded ABOVE by SIMILARITY_THRESHOLD (not just below by
    RELATED_SIMILARITY_THRESHOLD): a live-search cache miss for this exact
    question makes get_or_search() persist a brand new row for it right
    before this function runs, and that new row is a perfect (similarity 1.0)
    self-match - without the upper bound this always "finds" the question
    itself as its own related source. The upper bound also just enforces
    what "related but not a near-duplicate" should mean in the first place.

    Returns (original_question, results) so the caller can label the card
    with what question it was originally cached for, or None when nothing
    clears even this looser bar. The label is the entry's normalized_query
    (lowercased, punctuation stripped) rather than raw_query - raw_query is
    the search-engine query actually sent to Tavily (subject + "documentation
    tutorial" appended, see web_search.py::build_search_query), not a
    question a student would recognize; the schema doesn't separately store
    the original verbatim question text."""
    normalized = normalize_query(question)
    if not normalized:
        return None

    similarity = func.similarity(CachedSearch.normalized_query, normalized)
    q = db.query(CachedSearch).filter(
        similarity >= RELATED_SIMILARITY_THRESHOLD, similarity < SIMILARITY_THRESHOLD
    )
    q = q.filter(CachedSearch.subject == subject) if subject else q.filter(CachedSearch.subject.is_(None))
    entry = q.order_by(similarity.desc()).first()
    if not entry:
        return None
    return entry.normalized_query, _to_search_results(entry.results)


async def get_or_search_many(
    db: Session, questions: List[str], subject: Optional[str], num_results: int = 3
) -> List[SearchResult]:
    """Cached replacement for web_search.explore_search(): runs get_or_search() per
    query and returns a deduplicated, flattened result list."""
    seen_urls = set()
    all_results: List[SearchResult] = []

    for question in questions:
        results, _ = await get_or_search(db, question, subject, num_results=num_results)
        for r in results:
            if r.url not in seen_urls:
                seen_urls.add(r.url)
                all_results.append(r)

    return all_results
