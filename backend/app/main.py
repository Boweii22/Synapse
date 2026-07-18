"""FastAPI app: /chat, /memories, /benchmark endpoints (CLAUDE.md section 4)."""
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import qwen_client
from app.config import get_settings
from app.db.session import SessionLocal, get_db
from app.memory import consolidation, decay
from app.memory.models import ChatTurn, Memory, User
from app.memory.retrieval import retrieve_for_query
from app.memory.scoring import extract_and_write_turn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("synapse.main")

_settings = get_settings()

app = FastAPI(title="Synapse Memory Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _settings.cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- schemas ----------

class CreateUserResponse(BaseModel):
    user_id: uuid.UUID


class ChatRequest(BaseModel):
    user_id: uuid.UUID
    message: str


class RecalledMemoryOut(BaseModel):
    id: uuid.UUID
    content: str
    memory_type: str
    salience: float


class ChatResponse(BaseModel):
    user_id: uuid.UUID
    reply: str
    recalled_memories: list[RecalledMemoryOut]


class MemoryOut(BaseModel):
    id: uuid.UUID
    content: str
    memory_type: str
    importance_score: float
    salience: float
    recall_count: int
    created_at: datetime
    last_recalled_at: datetime
    is_active: bool
    pruned_at: datetime | None
    pruned_reason: str | None
    source_memory_ids: list[uuid.UUID] | None

    model_config = {"from_attributes": True}


class JobResult(BaseModel):
    detail: dict


# ---------- users ----------

@app.post("/users", response_model=CreateUserResponse)
def create_user(db: Session = Depends(get_db)):
    user = User()
    db.add(user)
    db.commit()
    db.refresh(user)
    return CreateUserResponse(user_id=user.id)


def _get_or_create_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


# ---------- chat ----------

SYSTEM_PROMPT_TEMPLATE = """You are Synapse, a personal AI assistant with long-term \
memory across sessions. Use the memories below (if any are relevant) to inform your \
reply -- they are real facts recalled from prior conversations with this user, ranked \
by how salient they currently are. Do not mention the mechanics of your memory system \
unless the user asks about it directly.

Recalled memories:
{memories_block}
"""


def _build_system_prompt(recalled: list[Memory]) -> str:
    if not recalled:
        block = "(none relevant to this message)"
    else:
        block = "\n".join(f"- [{m.memory_type}] {m.content}" for m in recalled)
    return SYSTEM_PROMPT_TEMPLATE.format(memories_block=block)


def _background_write_and_maybe_consolidate(user_id: uuid.UUID, user_message: str, assistant_message: str) -> None:
    db = SessionLocal()
    try:
        extract_and_write_turn(db, user_id, user_message, assistant_message)

        active_count = db.execute(
            select(Memory).where(Memory.user_id == user_id, Memory.is_active.is_(True))
        ).scalars().all()
        if len(active_count) and len(active_count) % _settings.consolidation_trigger_every_n_writes == 0:
            logger.info("triggering consolidation pass for user=%s at %d active memories", user_id, len(active_count))
            consolidation.run_consolidation_pass(db, user_id)
            decay.run_decay_and_prune(db)
    except Exception:
        logger.exception("background memory write/consolidation failed for user=%s", user_id)
    finally:
        db.close()


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    _get_or_create_user(db, req.user_id)

    recalled = retrieve_for_query(db, req.user_id, req.message)

    system_prompt = _build_system_prompt(recalled)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": req.message},
    ]
    reply = qwen_client.chat(messages)

    db.add(ChatTurn(user_id=req.user_id, role="user", content=req.message, recalled_memory_ids=[m.id for m in recalled]))
    db.add(ChatTurn(user_id=req.user_id, role="assistant", content=reply))
    db.commit()

    background_tasks.add_task(_background_write_and_maybe_consolidate, req.user_id, req.message, reply)

    return ChatResponse(
        user_id=req.user_id,
        reply=reply,
        recalled_memories=[
            RecalledMemoryOut(id=m.id, content=m.content, memory_type=m.memory_type, salience=m.salience)
            for m in recalled
        ],
    )


# ---------- memories (timeline view) ----------

@app.get("/memories/{user_id}", response_model=list[MemoryOut])
def list_memories(user_id: uuid.UUID, include_inactive: bool = True, db: Session = Depends(get_db)):
    stmt = select(Memory).where(Memory.user_id == user_id)
    if not include_inactive:
        stmt = stmt.where(Memory.is_active.is_(True))
    stmt = stmt.order_by(Memory.is_active.desc(), Memory.salience.desc())
    memories = db.execute(stmt).scalars().all()

    now = datetime.now(timezone.utc)
    out = []
    for m in memories:
        live_salience = (
            decay.compute_salience(m.importance_score, m.memory_type, m.recall_count, m.last_recalled_at, now)
            if m.is_active
            else m.salience
        )
        out.append(MemoryOut.model_validate({**m.__dict__, "salience": live_salience}))
    return out


@app.post("/memories/{user_id}/run-decay", response_model=JobResult)
def run_decay(user_id: uuid.UUID, db: Session = Depends(get_db)):
    result = decay.run_decay_and_prune(db)
    return JobResult(detail=result)


@app.post("/memories/{user_id}/run-consolidation", response_model=JobResult)
def run_consolidation(user_id: uuid.UUID, db: Session = Depends(get_db)):
    result = consolidation.run_consolidation_pass(db, user_id)
    return JobResult(detail=result)


# ---------- benchmark ----------

_BENCHMARK_DIR = Path(__file__).resolve().parent.parent / "benchmark" / "output"


@app.get("/benchmark/chart")
def benchmark_chart():
    chart_path = _BENCHMARK_DIR / "benchmark_results.png"
    if not chart_path.exists():
        raise HTTPException(status_code=404, detail="Benchmark hasn't been run yet -- run backend/benchmark/run_benchmark.py")
    return FileResponse(chart_path)


@app.get("/benchmark/data")
def benchmark_data():
    data_path = _BENCHMARK_DIR / "benchmark_results.json"
    if not data_path.exists():
        raise HTTPException(status_code=404, detail="Benchmark hasn't been run yet -- run backend/benchmark/run_benchmark.py")
    return FileResponse(data_path)


@app.get("/health")
def health():
    return {"status": "ok"}
