"""Consolidation ("sleep pass") and supersession detection (CLAUDE.md section 3.4).

Two things happen here, both driven by real Qwen calls:
1. Clusters of repeating episodic memories get merged into one consolidated
   semantic memory; the originals are soft-deleted with pruned_reason='consolidated'.
2. Memories that are directly contradicted/replaced by a newer one are retired
   with pruned_reason='superseded' -- this is the "timely forgetting of
   outdated information" the track brief asks for.
"""
import logging
import uuid
from datetime import datetime, timezone

import numpy as np
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import qwen_client
from app.config import get_settings
from app.memory.decay import initial_salience
from app.memory.models import Memory

logger = logging.getLogger("synapse.consolidation")

_settings = get_settings()


def _active_memories(db: Session, user_id: uuid.UUID, memory_type: str | None = None) -> list[Memory]:
    stmt = select(Memory).where(Memory.user_id == user_id, Memory.is_active.is_(True))
    if memory_type is not None:
        stmt = stmt.where(Memory.memory_type == memory_type)
    return list(db.execute(stmt).scalars().all())


def cluster_memories_by_similarity(memories: list[Memory]) -> list[list[Memory]]:
    """Group memories whose embeddings are similar above the configured
    threshold, using agglomerative clustering over cosine distance. Returns only
    clusters that meet the minimum cluster size."""
    if len(memories) < _settings.consolidation_min_cluster_size:
        return []

    embeddings = np.array([m.embedding for m in memories])
    similarity = cosine_similarity(embeddings)
    distance = np.clip(1.0 - similarity, 0.0, None)
    np.fill_diagonal(distance, 0.0)

    clustering = AgglomerativeClustering(
        metric="precomputed",
        linkage="average",
        distance_threshold=1.0 - _settings.consolidation_similarity_threshold,
        n_clusters=None,
    )
    labels = clustering.fit_predict(distance)

    groups: dict[int, list[Memory]] = {}
    for label, memory in zip(labels, memories):
        groups.setdefault(int(label), []).append(memory)

    return [g for g in groups.values() if len(g) >= _settings.consolidation_min_cluster_size]


def consolidate_clusters(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> list[Memory]:
    """Find repeating memories -- both episodic (repeated event mentions) and
    semantic (the same stated fact/preference re-extracted on separate turns,
    worded slightly differently each time) -- and merge each cluster into one
    consolidated memory. Returns the newly created consolidated Memory rows.

    Deduping semantic repeats here (not just episodic ones) matters: without
    it, near-duplicate semantic memories never merge, and the supersession
    pairwise-comparison pass below has to keep re-scanning an ever-growing
    pool of them on every single consolidation trigger.

    `now` lets the benchmark harness backdate the consolidated memory's
    created_at/last_recalled_at to the simulated conversation date instead of
    the real wall clock -- without this, a consolidated summary of old,
    simulated-months-ago facts gets stamped with today's real timestamp,
    which both makes it look artificially fresh (undecayed) and, worse, makes
    it sort as "newer" than genuinely current facts in
    detect_and_retire_superseded below, potentially causing the correct fact
    to be retired as "superseded" by the stale one instead of the reverse.
    """
    now = now or datetime.now(timezone.utc)
    created: list[Memory] = []

    for source_type in ("episodic", "semantic"):
        candidates = _active_memories(db, user_id, memory_type=source_type)
        clusters = cluster_memories_by_similarity(candidates)

        for cluster in clusters:
            contents = [m.content for m in cluster]
            result = qwen_client.consolidate_cluster(contents)
            consolidated_text = result["consolidated_memory"]

            score = qwen_client.score_importance(consolidated_text)
            embedding = qwen_client.embed_text(consolidated_text)

            consolidated = Memory(
                user_id=user_id,
                content=consolidated_text,
                embedding=embedding,
                memory_type="consolidated",
                importance_score=score["importance"],
                reasoning=result.get("reasoning") or score.get("reasoning"),
                source_memory_ids=[m.id for m in cluster],
                salience=initial_salience(score["importance"]),
                created_at=now,
                last_recalled_at=now,
            )
            db.add(consolidated)

            for m in cluster:
                m.is_active = False
                m.pruned_at = now
                m.pruned_reason = "consolidated"

            logger.info(
                "consolidated %d %s memories into one for user=%s: %r",
                len(cluster), source_type, user_id, consolidated_text,
            )
            created.append(consolidated)

    if created:
        db.commit()
        for m in created:
            db.refresh(m)
    return created


def detect_and_retire_superseded(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> list[uuid.UUID]:
    """Compare active semantic/consolidated memories pairwise (gated by embedding
    similarity to keep this cheap) and ask Qwen whether the newer one supersedes
    the older. Retires (soft-deletes) any memory found to be superseded.

    `now` lets the benchmark harness stamp pruned_at with the simulated date;
    ordering "older" vs "newer" itself is based on each row's own created_at,
    which is why consolidate_clusters above must also honor the simulated
    `now` -- otherwise a stale fact re-summarized "today" would always sort as
    the newer of the pair, regardless of which one is actually current.
    """
    now = now or datetime.now(timezone.utc)
    candidates = [
        m for m in _active_memories(db, user_id) if m.memory_type in ("semantic", "consolidated")
    ]
    candidates.sort(key=lambda m: m.created_at)
    if len(candidates) < 2:
        return []

    embeddings = np.array([m.embedding for m in candidates])
    similarity = cosine_similarity(embeddings)

    retired_ids: set[uuid.UUID] = set()
    for i, older in enumerate(candidates):
        if older.id in retired_ids:
            continue
        for j in range(i + 1, len(candidates)):
            newer = candidates[j]
            if newer.id in retired_ids or older.id in retired_ids:
                continue
            if similarity[i, j] < _settings.supersession_similarity_gate:
                continue
            result = qwen_client.detect_supersession(older.content, newer.content)
            if result.get("supersedes"):
                older.is_active = False
                older.pruned_at = now
                older.pruned_reason = "superseded"
                retired_ids.add(older.id)
                logger.info(
                    "retired memory id=%s (%r) superseded by id=%s (%r): %s",
                    older.id, older.content, newer.id, newer.content, result.get("reasoning"),
                )
                break

    if retired_ids:
        db.commit()
    return list(retired_ids)


def run_consolidation_pass(db: Session, user_id: uuid.UUID, now: datetime | None = None) -> dict:
    """The full 'sleep' pass for one user: consolidate repeating episodic
    clusters, then detect and retire superseded facts."""
    consolidated = consolidate_clusters(db, user_id, now=now)
    retired = detect_and_retire_superseded(db, user_id, now=now)
    return {"consolidated_count": len(consolidated), "retired_count": len(retired)}
