"""Salience decay formula and the decay/pruning job (CLAUDE.md sections 3.3, 3.5).

    salience(t) = importance_score * recall_boost(recall_count) * exp(-lambda * hours_since_last_recall)
    recall_boost(n) = 1 + log(1 + n)

lambda is derived from a per-memory-type half-life in app.config, not a magic
number: lambda = ln(2) / half_life_hours.
"""
import logging
import math
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.memory.models import Memory

logger = logging.getLogger("synapse.decay")

_settings = get_settings()

_HALFLIFE_HOURS = {
    "semantic": _settings.decay_halflife_hours_semantic,
    "episodic": _settings.decay_halflife_hours_episodic,
    "consolidated": _settings.decay_halflife_hours_consolidated,
}


def lambda_for_type(memory_type: str) -> float:
    half_life = _HALFLIFE_HOURS.get(memory_type)
    if half_life is None:
        raise ValueError(f"no configured decay half-life for memory_type={memory_type!r}")
    return math.log(2) / half_life


def recall_boost(recall_count: int) -> float:
    return 1.0 + math.log(1 + max(0, recall_count))


def hours_since(then: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    return max(0.0, (now - then).total_seconds() / 3600.0)


def compute_salience(
    importance_score: float,
    memory_type: str,
    recall_count: int,
    last_recalled_at: datetime,
    now: datetime | None = None,
) -> float:
    lam = lambda_for_type(memory_type)
    hours = hours_since(last_recalled_at, now)
    return importance_score * recall_boost(recall_count) * math.exp(-lam * hours)


def initial_salience(importance_score: float) -> float:
    """At write time recall_count=0 and hours_since_last_recall=0, so salience
    collapses to the importance score itself."""
    return importance_score


def recompute_all_salience(db: Session, now: datetime | None = None) -> int:
    """Recompute salience for every active memory. Returns count updated."""
    now = now or datetime.now(timezone.utc)
    memories = db.execute(select(Memory).where(Memory.is_active.is_(True))).scalars().all()
    for m in memories:
        m.salience = compute_salience(m.importance_score, m.memory_type, m.recall_count, m.last_recalled_at, now)
    db.commit()
    logger.info("recomputed salience for %d active memories", len(memories))
    return len(memories)


def prune_below_floor(db: Session, floor: float | None = None, now: datetime | None = None) -> int:
    """Mark any active memory whose current salience is below the floor as pruned.
    Soft-delete only (is_active=false) -- rows are kept for the benchmark comparison."""
    floor = floor if floor is not None else _settings.prune_salience_floor
    now = now or datetime.now(timezone.utc)
    memories = db.execute(select(Memory).where(Memory.is_active.is_(True))).scalars().all()
    pruned = 0
    for m in memories:
        if m.salience < floor:
            m.is_active = False
            m.pruned_at = now
            m.pruned_reason = "decayed_below_threshold"
            pruned += 1
            logger.info("pruned memory id=%s salience=%.4f < floor=%.4f content=%r", m.id, m.salience, floor, m.content)
    db.commit()
    return pruned


def run_decay_and_prune(db: Session, now: datetime | None = None) -> dict:
    """The nightly decay job: recompute salience for all active memories, then
    prune anything that fell below the floor."""
    now = now or datetime.now(timezone.utc)
    recomputed = recompute_all_salience(db, now)
    pruned = prune_below_floor(db, now=now)
    return {"recomputed": recomputed, "pruned": pruned}
