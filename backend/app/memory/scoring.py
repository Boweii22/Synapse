"""Memory write path (CLAUDE.md section 3.2, build order step 3):
extraction -> importance scoring -> embedding -> insert.

Every score and embedding here comes from a real Qwen Cloud call in
app.qwen_client -- nothing here fabricates a number.
"""
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import qwen_client
from app.memory.decay import initial_salience
from app.memory.models import Memory

logger = logging.getLogger("synapse.scoring")


def extract_and_write_turn(
    db: Session,
    user_id: uuid.UUID,
    user_message: str,
    assistant_message: str,
    now: datetime | None = None,
) -> list[Memory]:
    """Given one chat turn, extract candidate memories, score + embed + insert each.

    `now` lets the benchmark harness backdate created_at/last_recalled_at to
    simulate a multi-day conversation without wall-clock waiting; production
    callers omit it and get the real current time.

    Candidates' Qwen calls (score + embed) run concurrently across threads --
    they're independent, I/O-bound network calls. The SQLAlchemy `db` session
    itself is not thread-safe, so all `db.add`/`commit` stays on the calling
    thread; threads only build plain, unattached Memory objects.
    """
    now = now or datetime.now(timezone.utc)
    candidates = qwen_client.extract_memory_candidates(user_message, assistant_message)
    if not candidates:
        logger.info("turn produced no memory candidates for user=%s", user_id)
        return []

    if len(candidates) == 1:
        memories = [_score_and_build_memory(user_id, candidates[0], now)]
    else:
        with ThreadPoolExecutor(max_workers=min(4, len(candidates))) as executor:
            memories = list(executor.map(lambda c: _score_and_build_memory(user_id, c, now), candidates))

    for m in memories:
        db.add(m)
    db.commit()
    for m in memories:
        db.refresh(m)
    return memories


def _score_and_build_memory(user_id: uuid.UUID, content: str, now: datetime) -> Memory:
    """Runs the two Qwen calls for one candidate and builds an unattached Memory
    object. Safe to call from any thread -- touches no SQLAlchemy session."""
    score = qwen_client.score_importance(content)
    embedding = qwen_client.embed_text(content)

    memory = Memory(
        user_id=user_id,
        content=content,
        embedding=embedding,
        memory_type=score["memory_type"],
        importance_score=score["importance"],
        reasoning=score.get("reasoning"),
        salience=initial_salience(score["importance"]),
        created_at=now,
        last_recalled_at=now,
    )
    logger.info(
        "wrote memory user=%s type=%s importance=%.2f reasoning=%r content=%r",
        user_id, memory.memory_type, memory.importance_score, memory.reasoning, content,
    )
    return memory


def write_single_memory(db: Session, user_id: uuid.UUID, content: str, now: datetime | None = None) -> Memory:
    now = now or datetime.now(timezone.utc)
    memory = _score_and_build_memory(user_id, content, now)
    db.add(memory)
    return memory
