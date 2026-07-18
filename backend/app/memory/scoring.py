"""Memory write path (CLAUDE.md section 3.2, build order step 3):
extraction -> importance scoring -> embedding -> insert.

Every score and embedding here comes from a real Qwen Cloud call in
app.qwen_client -- nothing here fabricates a number.
"""
import logging
import uuid
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

    Scoring and embedding are each batched into a single Qwen call across all
    candidates in the turn (instead of one call per candidate) -- a real
    latency/throughput win, not a change in what actually gets scored.
    """
    now = now or datetime.now(timezone.utc)
    candidates = qwen_client.extract_memory_candidates(user_message, assistant_message)
    if not candidates:
        logger.info("turn produced no memory candidates for user=%s", user_id)
        return []

    scores = qwen_client.score_importance_batch(candidates)
    embeddings = qwen_client.embed_texts(candidates)

    memories: list[Memory] = []
    for content, score, embedding in zip(candidates, scores, embeddings):
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
        db.add(memory)
        memories.append(memory)

    db.commit()
    for m in memories:
        db.refresh(m)
    return memories


def write_single_memory(db: Session, user_id: uuid.UUID, content: str, now: datetime | None = None) -> Memory:
    now = now or datetime.now(timezone.utc)
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
    db.add(memory)
    return memory
