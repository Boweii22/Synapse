"""The naive baseline (CLAUDE.md section 5): same Qwen chat + embedding models as
Synapse, but deliberately dumb memory strategy -- store every turn verbatim,
retrieve top-k by raw cosine similarity, never score importance, never decay,
never consolidate, never prune. This is the "vector DB as search index" approach
almost every other submission will ship; Synapse's benchmark exists to beat it.

Uses its own table (naive_memories) in the same Postgres instance so the
comparison runs against identical infrastructure -- only the memory strategy differs.
"""
import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Text, create_engine, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app import qwen_client
from app.config import get_settings

_settings = get_settings()


class NaiveBase(DeclarativeBase):
    pass


class NaiveMemory(NaiveBase):
    __tablename__ = "naive_memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(_settings.embedding_dim), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


_engine = create_engine(_settings.database_url, pool_pre_ping=True)
NaiveSession = sessionmaker(bind=_engine)


def ensure_schema() -> None:
    NaiveBase.metadata.create_all(_engine)


def reset_user(user_id: uuid.UUID) -> None:
    """Wipe this user's naive memories so repeated benchmark runs start clean."""
    db = NaiveSession()
    try:
        db.query(NaiveMemory).filter(NaiveMemory.user_id == user_id).delete()
        db.commit()
    finally:
        db.close()


class NaiveAgent:
    def __init__(self, user_id: uuid.UUID, top_k: int):
        self.user_id = user_id
        self.top_k = top_k

    def _write_raw(self, db, text: str, now: datetime) -> None:
        embedding = qwen_client.embed_text(text)
        db.add(NaiveMemory(user_id=self.user_id, content=text, embedding=embedding, created_at=now))

    def write_turn(self, user_message: str, assistant_message: str, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        db = NaiveSession()
        try:
            self._write_raw(db, f"User said: {user_message}", now)
            self._write_raw(db, f"Assistant replied: {assistant_message}", now)
            db.commit()
        finally:
            db.close()

    def retrieve(self, query: str) -> list[NaiveMemory]:
        db = NaiveSession()
        try:
            query_embedding = qwen_client.embed_text(query)
            distance_col = NaiveMemory.embedding.cosine_distance(query_embedding)
            stmt = (
                select(NaiveMemory)
                .where(NaiveMemory.user_id == self.user_id)
                .order_by(distance_col)
                .limit(self.top_k)
            )
            return list(db.execute(stmt).scalars().all())
        finally:
            db.close()

    def active_memory_count(self) -> int:
        db = NaiveSession()
        try:
            return db.execute(
                select(func.count()).select_from(NaiveMemory).where(NaiveMemory.user_id == self.user_id)
            ).scalar_one()
        finally:
            db.close()

    @staticmethod
    def _system_prompt(recalled: list[NaiveMemory]) -> str:
        block = "\n".join(f"- {m.content}" for m in recalled) or "(none)"
        return (
            "You are a personal AI assistant. Below are the raw retrieved snippets most "
            "textually similar to the user's message, pulled from everything ever said in "
            "past conversations. Use them if relevant to answer.\n\n" + block
        )

    def chat(self, message: str, now: datetime | None = None) -> tuple[str, list[NaiveMemory]]:
        recalled = self.retrieve(message)
        reply = qwen_client.chat([
            {"role": "system", "content": self._system_prompt(recalled)},
            {"role": "user", "content": message},
        ])
        self.write_turn(message, reply, now=now)
        return reply, recalled

    def ask_readonly(self, question: str) -> tuple[str, list[NaiveMemory]]:
        """Like chat(), but does not write the Q&A back into memory -- used for
        benchmark evaluation probes so grading doesn't pollute the naive store."""
        recalled = self.retrieve(question)
        reply = qwen_client.chat([
            {"role": "system", "content": self._system_prompt(recalled)},
            {"role": "user", "content": question},
        ])
        return reply, recalled
