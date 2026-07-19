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
    """Returns up to top_k memories, re-ranked by relevance-gated salience.

    Ranking is two-stage rather than a flat `similarity * salience` product:
    1. Split candidates into "relevant" (cosine similarity >= relevance_floor,
       i.e. plausibly about the same topic as the query) and the rest.
    2. Rank the relevant group by salience alone -- once something clears the
       relevance bar, which one matters most should be decided by how salient
       it currently is, not further nudged by fine-grained similarity
       differences. This avoids a failure mode found via direct benchmark
       analysis: a frequently-recalled generic fact (name, allergy) could
       out-rank a topically relevant but less-reinforced memory under the old
       multiplicative scheme, simply by having much higher salience, even
       though its similarity to the query was unremarkable.
    3. If fewer than top_k candidates clear the relevance bar, backfill the
       remainder from the rest, ranked by similarity * salience as before, so
       a query with no strongly relevant memory still gets a reasonable
       best-effort answer instead of an empty context.

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

    relevant: list[tuple[Memory, float, float]] = []  # (memory, salience, combined)
    backfill: list[tuple[Memory, float, float]] = []
    for memory, distance in rows:
        similarity = 1.0 - float(distance)
        current_salience = compute_salience(
            memory.importance_score, memory.memory_type, memory.recall_count, memory.last_recalled_at, now
        )
        entry = (memory, current_salience, similarity * current_salience)
        if similarity >= _settings.retrieval_relevance_floor:
            relevant.append(entry)
        else:
            backfill.append(entry)

    relevant.sort(key=lambda e: e[1], reverse=True)   # by salience alone
    backfill.sort(key=lambda e: e[2], reverse=True)   # by similarity x salience

    top = relevant[:top_k]
    if len(top) < top_k:
        top += backfill[: top_k - len(top)]
    top = [(m, score) for m, _sal, score in top]

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
