"""Regression test for a real bug found during benchmark verification:
consolidate_clusters/detect_and_retire_superseded used to ignore the
benchmark's simulated `now` and always stamp new consolidated memories with
the real wall clock. That made a consolidated summary of OLD facts look
*newer* than genuinely current facts when detect_and_retire_superseded sorts
by created_at -- so the correct fact could get retired as "superseded" by the
stale one instead of the reverse. This test proves the fix: even when a
consolidated memory is created for real (with unavoidably-real wall-clock
created_at), the CORRECT fact wins when created_at ordering is stated
explicitly via `now`.

Run with: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_consolidation_time.py -v -s
(real Qwen calls: embeddings + supersession detection)
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import SessionLocal
from app.memory.consolidation import detect_and_retire_superseded
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
    u = User(label="test_consolidation_time_user")
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    db.delete(u)
    db.commit()


def test_stale_fact_loses_even_when_inserted_after_correct_one(db, user):
    """Simulates the exact bug scenario: a stale fact (e.g. re-consolidated
    from old mentions) gets INSERTED into the DB after the correct fact (so
    its real row-creation order is later), but its *simulated* created_at
    (the `now` passed at insert time) correctly reflects that it describes
    older information. detect_and_retire_superseded must use that simulated
    timestamp for ordering, not real insertion order -- otherwise the correct
    fact would wrongly get retired as "superseded" by the stale one.
    """
    now = datetime.now(timezone.utc)

    correct_embedding = qwen_client.embed_text("User currently resides in Lisbon.")
    correct = Memory(
        user_id=user.id,
        content="User currently resides in Lisbon.",
        embedding=correct_embedding,
        memory_type="semantic",
        importance_score=0.85,
        salience=0.85,
        created_at=now - timedelta(days=5),  # simulated: stated 5 days ago
        last_recalled_at=now - timedelta(days=5),
    )
    db.add(correct)
    db.commit()
    db.refresh(correct)

    # Inserted SECOND (later real wall-clock row-creation order), but its
    # simulated created_at says it describes something from 20 days ago --
    # i.e. exactly what a buggy consolidation pass re-summarizing old mentions
    # would produce if it didn't honor simulated time.
    stale_embedding = qwen_client.embed_text("User currently resides in Berlin.")
    stale = Memory(
        user_id=user.id,
        content="User currently resides in Berlin.",
        embedding=stale_embedding,
        memory_type="consolidated",
        importance_score=0.85,
        salience=0.85,
        created_at=now - timedelta(days=20),  # simulated: describes older info
        last_recalled_at=now - timedelta(days=20),
    )
    db.add(stale)
    db.commit()
    db.refresh(stale)

    detect_and_retire_superseded(db, user.id, now=now)

    db.refresh(correct)
    db.refresh(stale)

    assert correct.is_active is True, "the genuinely current fact must NOT be retired"
    assert stale.is_active is False, "the stale fact must be the one retired"
    assert stale.pruned_reason == "superseded"
