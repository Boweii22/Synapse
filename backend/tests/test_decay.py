"""Verifies the salience decay + pruning job (CLAUDE.md section 3.3/3.5,
build order step 6) against a real Postgres instance, by backdating
created_at/last_recalled_at instead of waiting real days.

Run with: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_decay.py -v
(requires `docker compose up -d postgres` to be running first; no Qwen calls
are made -- decay math only touches numeric columns already on the row).
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.memory.decay import compute_salience, recall_boost, run_decay_and_prune
from app.memory.models import Memory, User


@pytest.fixture
def db():
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def user(db):
    u = User(label="test_decay_user")
    db.add(u)
    db.commit()
    db.refresh(u)
    yield u
    db.delete(u)
    db.commit()


def _make_memory(db, user, memory_type, importance, hours_ago, recall_count=0):
    now = datetime.now(timezone.utc)
    m = Memory(
        user_id=user.id,
        content=f"test memory ({memory_type}, {hours_ago}h ago)",
        embedding=[0.001] * 1024,
        memory_type=memory_type,
        importance_score=importance,
        salience=importance,
        recall_count=recall_count,
        created_at=now - timedelta(hours=hours_ago),
        last_recalled_at=now - timedelta(hours=hours_ago),
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def test_salience_drops_as_time_passes(db, user):
    fresh = _make_memory(db, user, "episodic", importance=0.8, hours_ago=0)
    old = _make_memory(db, user, "episodic", importance=0.8, hours_ago=200)  # well past 3-day half-life

    now = datetime.now(timezone.utc)
    fresh_salience = compute_salience(fresh.importance_score, fresh.memory_type, fresh.recall_count, fresh.last_recalled_at, now)
    old_salience = compute_salience(old.importance_score, old.memory_type, old.recall_count, old.last_recalled_at, now)

    assert fresh_salience == pytest.approx(0.8, rel=1e-6)
    assert old_salience < fresh_salience
    assert old_salience < 0.8 * 0.25  # more than two 3-day half-lives have passed


def test_episodic_decays_faster_than_semantic(db, user):
    episodic = _make_memory(db, user, "episodic", importance=0.8, hours_ago=72)   # exactly one episodic half-life
    semantic = _make_memory(db, user, "semantic", importance=0.8, hours_ago=72)   # far short of semantic half-life

    now = datetime.now(timezone.utc)
    episodic_salience = compute_salience(episodic.importance_score, episodic.memory_type, episodic.recall_count, episodic.last_recalled_at, now)
    semantic_salience = compute_salience(semantic.importance_score, semantic.memory_type, semantic.recall_count, semantic.last_recalled_at, now)

    assert episodic_salience == pytest.approx(0.4, rel=0.05)  # one half-life => ~half the importance
    assert semantic_salience > episodic_salience


def test_recall_boost_reinforces_but_diminishes():
    boost_0 = recall_boost(0)
    boost_1 = recall_boost(1)
    boost_5 = recall_boost(5)
    boost_20 = recall_boost(20)

    assert boost_0 == pytest.approx(1.0)
    assert boost_1 > boost_0
    assert boost_5 > boost_1
    # diminishing returns: the jump from 5->20 recalls is smaller than 0->1 relative to scale
    assert (boost_20 - boost_5) < (boost_1 - boost_0) * 10


def test_decay_job_recomputes_and_prunes(db, user):
    stale = _make_memory(db, user, "episodic", importance=0.2, hours_ago=500)  # will land below floor
    healthy = _make_memory(db, user, "semantic", importance=0.9, hours_ago=1)

    result = run_decay_and_prune(db)
    assert result["recomputed"] >= 2

    db.refresh(stale)
    db.refresh(healthy)

    assert stale.is_active is False
    assert stale.pruned_reason == "decayed_below_threshold"
    assert stale.pruned_at is not None

    assert healthy.is_active is True
    assert healthy.salience > 0.5

    # cleanup (fixture only deletes the user row via cascade, but be explicit for clarity)
    db.execute(select(Memory).where(Memory.user_id == user.id))
