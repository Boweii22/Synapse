"""Retrieval path (CLAUDE.md section 3.6, build order step 4):
embed query -> cosine-similarity search -> salience re-rank -> bump recall stats.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import qwen_client
from app.config import get_settings
from app.memory.decay import compute_salience
from app.memory.models import Memory

logger = logging.getLogger("synapse.retrieval")

_settings = get_settings()


def retrieve_for_query(
    db: Session,
    user_id: uuid.UUID,
    query_text: str,
    top_n: int | None = None,
    top_k: int | None = None,
    now: datetime | None = None,
    bump: bool = True,
) -> list[Memory]:
    """Returns up to top_k memories, re-ranked by similarity x current salience.

    `now` lets the benchmark harness simulate a specific point in a multi-day
    conversation; production callers omit it and get the real current time.
    `bump` controls whether recall_count/last_recalled_at/salience get updated
    as a side effect -- the benchmark harness passes bump=False for evaluation
    probe questions so grading itself doesn't reinforce memories and distort
    the organic decay/consolidation comparison.
    """
    top_n = top_n or _settings.retrieval_top_n
    top_k = top_k or _settings.retrieval_top_k
    now = now or datetime.now(timezone.utc)

    query_embedding = qwen_client.embed_text(query_text)

    distance_col = Memory.embedding.cosine_distance(query_embedding)
    stmt = (
        select(Memory, distance_col.label("distance"))
        .where(Memory.user_id == user_id, Memory.is_active.is_(True))
        .order_by(distance_col)
        .limit(top_n)
    )
    rows = db.execute(stmt).all()
    if not rows:
        return []

    scored: list[tuple[Memory, float]] = []
    for memory, distance in rows:
        similarity = 1.0 - float(distance)
        current_salience = compute_salience(
            memory.importance_score, memory.memory_type, memory.recall_count, memory.last_recalled_at, now
        )
        scored.append((memory, similarity * current_salience))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    top = scored[:top_k]

    if bump:
        for memory, _rank_score in top:
            memory.recall_count += 1
            memory.last_recalled_at = now
            memory.salience = compute_salience(
                memory.importance_score, memory.memory_type, memory.recall_count, memory.last_recalled_at, now
            )
        db.commit()

    logger.info(
        "retrieved %d/%d candidates for user=%s query=%r -> ids=%s",
        len(top), len(rows), user_id, query_text, [str(m.id) for m, _ in top],
    )
    return [m for m, _ in top]
