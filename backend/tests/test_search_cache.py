"""Tests for backend/services/search_cache.py.

Requires a real Postgres database with the pg_trgm extension enabled (run
`alembic upgrade head` first) - the fuzzy-match tests use `func.similarity()`,
which is Postgres-specific and has no SQLite equivalent.
"""
import pytest

from backend.database.models import CachedSearch
from backend.database.session import SessionLocal
from backend.models.searchResult import SearchResult
from backend.services import search_cache as sc


@pytest.fixture
def db():
    session = SessionLocal()
    session.query(CachedSearch).delete()
    session.commit()
    yield session
    session.query(CachedSearch).delete()
    session.commit()
    session.close()


def test_normalize_query_strips_punctuation_and_case():
    assert sc.normalize_query("What is  Recursion??") == "what is recursion"
    assert sc.normalize_query("  RECURSION!  ") == "recursion"


def test_find_cached_returns_none_when_empty(db):
    assert sc.find_cached(db, "anything", None) is None


def test_exact_and_fuzzy_match(db):
    results = [SearchResult(title="Recursion", url="https://example.com/r", snippet="...")]
    entry = sc._create(db, "What is recursion?", "Structural Programming", "recursion docs", results)

    exact = sc.find_cached(db, "What is recursion?", "Structural Programming")
    assert exact is not None and exact.id == entry.id

    normalized_variant = sc.find_cached(db, "what is recursion", "Structural Programming")
    assert normalized_variant is not None and normalized_variant.id == entry.id

    fuzzy_variant = sc.find_cached(db, "what is a recursion", "Structural Programming")
    assert fuzzy_variant is not None and fuzzy_variant.id == entry.id


def test_subject_scoping(db):
    results = [SearchResult(title="Recursion", url="https://example.com/r", snippet="...")]
    sc._create(db, "What is recursion?", "Structural Programming", "recursion docs", results)

    assert sc.find_cached(db, "What is recursion?", "Other Subject") is None
    assert sc.find_cached(db, "What is recursion?", None) is None


def test_record_hit_increments_count(db):
    results = [SearchResult(title="Recursion", url="https://example.com/r", snippet="...")]
    entry = sc._create(db, "What is recursion?", None, "recursion docs", results)
    assert entry.hit_count == 1

    sc._record_hit(db, entry)
    db.refresh(entry)
    assert entry.hit_count == 2


@pytest.mark.asyncio
async def test_get_or_search_reuses_cache_on_second_call(db, monkeypatch):
    call_count = {"n": 0}

    async def fake_web_search(query, num_results=5):
        call_count["n"] += 1
        return [SearchResult(title="T", url="https://example.com", snippet="s")]

    monkeypatch.setattr(sc, "web_search", fake_web_search)

    results1, from_cache1 = await sc.get_or_search(db, "What is a binary search tree?", "DSA")
    results2, from_cache2 = await sc.get_or_search(db, "What is a binary search tree?", "DSA")

    assert from_cache1 is False
    assert from_cache2 is True
    assert call_count["n"] == 1  # second call must NOT hit the (fake) live search again
    assert db.query(CachedSearch).count() == 1


# ---------------------------------- find_related_cached_search (third source) ----

def test_find_related_cached_search_returns_none_when_nothing_cached(db):
    assert sc.find_related_cached_search(db, "anything", None) is None


def test_find_related_cached_search_returns_none_for_unrelated_question(db):
    # Below even the loose bar - genuinely unrelated topics must not surface
    # as a false "related" third source.
    results = [SearchResult(title="Recursion", url="https://example.com/r", snippet="...")]
    sc._create(db, "What is recursion in programming?", None, "recursion docs", results)

    assert sc.find_related_cached_search(db, "How do I bake sourdough bread?", None) is None


def test_find_related_cached_search_finds_a_loosely_related_prior_question(db):
    # Shares enough trigram overlap ("programming"/"course") to clear
    # RELATED_SIMILARITY_THRESHOLD (measured ~0.18) without being similar
    # enough to count as a near-duplicate of the current question (that
    # would instead be find_cached's job, and is excluded by the upper
    # bound - see test_find_related_cached_search_excludes_a_near_duplicate_of_itself).
    results = [SearchResult(title="Python", url="https://example.com/py", snippet="...")]
    sc._create(db, "What programming language is easiest to learn?", "Intro to CS", "python docs", results)

    found = sc.find_related_cached_search(db, "How does this course teach programming concepts?", "Intro to CS")

    assert found is not None
    original_question, found_results = found
    assert original_question == "what programming language is easiest to learn"
    assert found_results[0].title == "Python"


def test_find_related_cached_search_excludes_a_near_duplicate_of_itself(db):
    # Regression test for a real bug caught live: get_or_search() persists a
    # brand new row for the CURRENT question right before chatRoute.py calls
    # find_related_cached_search() for that same question - without an upper
    # similarity bound, that fresh row is a perfect self-match and always
    # "finds itself" as its own related third source.
    results = [SearchResult(title="Async", url="https://example.com/a", snippet="...")]
    sc._create(db, "How does async await work?", None, "async docs", results)

    assert sc.find_related_cached_search(db, "How does async await work?", None) is None


def test_find_related_cached_search_respects_subject_scoping(db):
    results = [SearchResult(title="Python", url="https://example.com/py", snippet="...")]
    sc._create(db, "What programming language is easiest to learn?", "Intro to CS", "python docs", results)

    # Same pair as test_find_related_cached_search_finds_a_loosely_related_prior_question
    # (confirmed to clear the similarity bounds in that test) - mismatched
    # subject alone must be enough to exclude it here.
    assert sc.find_related_cached_search(db, "How does this course teach programming concepts?", "Other Subject") is None
