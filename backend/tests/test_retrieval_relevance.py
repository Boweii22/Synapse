"""Regression test for a real failure mode found during benchmark analysis:
under the old `similarity * salience` ranking, a frequently-recalled generic
fact (e.g. name) could out-rank a topically relevant but less-reinforced
memory (e.g. location) for a location-specific query, simply by having much
higher salience despite unremarkable similarity to the query. This is
literally why the benchmark saw Synapse fail "Where do I currently live?"
even though the correct memory existed and was active.

Run with: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_retrieval_relevance.py -v -s
(real Qwen calls: embeddings)
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import SessionLocal
from app.memory.retrieval import retrieve_for_query
from app.memory.models import Memory, User
from app import qwen_client


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def user(db):
    u = User(label="test_retrieval_relevance_user")
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    db.delete(u)
    db.commit()


def test_relevant_memory_beats_highly_salient_irrelevant_one(db, user):
    """A heavily-reinforced generic fact (high salience, low relevance to this
    specific query) must not out-rank a genuinely relevant, less-reinforced
    memory for a topic-specific question."""
    now = datetime.now(timezone.utc)

    # Genuinely relevant to the query, but only stated once, never recalled --
    # low recall_count means lower salience than the heavily-reinforced fact below.
    location_embedding = qwen_client.embed_text("User lives in Berlin.")
    location = Memory(
        user_id=user.id,
        content="User lives in Berlin.",
        embedding=location_embedding,
        memory_type="semantic",
        importance_score=0.7,
        salience=0.7,
        recall_count=0,
        created_at=now - timedelta(days=3),
        last_recalled_at=now - timedelta(days=3),
    )
    db.add(location)

    # Not relevant to a location question at all, but recalled many times,
    # so its salience is much higher than the location memory's.
    name_embedding = qwen_client.embed_text("User's name is Alex.")
    name = Memory(
        user_id=user.id,
        content="User's name is Alex.",
        embedding=name_embedding,
        memory_type="semantic",
        importance_score=0.9,
        salience=1.5,  # already-boosted stored value; retrieval recomputes live anyway
        recall_count=20,
        created_at=now - timedelta(days=3),
        last_recalled_at=now - timedelta(hours=1),
    )
    db.add(name)
    db.commit()
    db.refresh(location)
    db.refresh(name)

    results = retrieve_for_query(db, user.id, "Where do I currently live?", top_k=2, now=now, bump=False)
    result_ids = [m.id for m in results]

    assert location.id in result_ids, "the genuinely relevant memory must be retrieved at all"
    assert result_ids.index(location.id) < result_ids.index(name.id), (
        "the relevant-but-less-salient memory must rank ABOVE the irrelevant-but-highly-salient one"
    )
