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


def cluster_episodic_memories(memories: list[Memory]) -> list[list[Memory]]:
    """Group episodic memories whose embeddings are similar above the configured
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


def consolidate_clusters(db: Session, user_id: uuid.UUID) -> list[Memory]:
    """Find repeating episodic clusters and merge each into one consolidated
    semantic memory. Returns the newly created consolidated Memory rows."""
    now = datetime.now(timezone.utc)
    episodic = _active_memories(db, user_id, memory_type="episodic")
    clusters = cluster_episodic_memories(episodic)

    created: list[Memory] = []
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
        )
        db.add(consolidated)

        for m in cluster:
            m.is_active = False
            m.pruned_at = now
            m.pruned_reason = "consolidated"

        logger.info(
            "consolidated %d episodic memories into one for user=%s: %r",
            len(cluster), user_id, consolidated_text,
        )
        created.append(consolidated)

    if created:
        db.commit()
        for m in created:
            db.refresh(m)
    return created


def detect_and_retire_superseded(db: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """Compare active semantic/consolidated memories pairwise (gated by embedding
    similarity to keep this cheap) and ask Qwen whether the newer one supersedes
    the older. Retires (soft-deletes) any memory found to be superseded."""
    now = datetime.now(timezone.utc)
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


def run_consolidation_pass(db: Session, user_id: uuid.UUID) -> dict:
    """The full 'sleep' pass for one user: consolidate repeating episodic
    clusters, then detect and retire superseded facts."""
    consolidated = consolidate_clusters(db, user_id)
    retired = detect_and_retire_superseded(db, user_id)
    return {"consolidated_count": len(consolidated), "retired_count": len(retired)}
