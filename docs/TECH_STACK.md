# Tech Stack & Rationale

## Qwen Cloud (DashScope)

- **qwen-max** for chat replies, memory extraction, importance scoring,
  contradiction detection, and consolidation summarization. One model across
  all of these keeps the comparison in the benchmark fair (Synapse and the
  naive baseline use exactly the same chat model) and keeps the codebase to a
  single client wrapper (`backend/app/qwen_client.py`).
- **text-embedding-v3** for all embeddings, at 1024 dimensions (matching the
  `VECTOR(1024)` column in the schema). Accessed through DashScope's
  OpenAI-compatible endpoint (`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`),
  which means the standard `openai` Python SDK works unmodified -- just a
  different `base_url` and API key -- rather than needing a bespoke DashScope
  SDK integration.
- Every call in `qwen_client.py` is a real network request with retries
  (`tenacity`) and no offline/mock fallback -- a missing or invalid
  `QWEN_API_KEY` fails loudly rather than silently degrading to fake output,
  per CLAUDE.md's non-negotiables.

## Postgres + pgvector

- A single database serves both the structured memory metadata (importance,
  salience, recall stats, soft-delete/pruning state) and the embedding vectors
  side by side in one `memories` table (`backend/app/db/schema.sql`) -- no
  separate vector-DB service to keep in sync.
- `ivfflat` index with cosine distance ops for the similarity search in
  `retrieval.py`; pgvector's SQLAlchemy integration (`pgvector.sqlalchemy.Vector`)
  gives typed `.cosine_distance()` comparisons directly in ORM queries.
- Runs either self-hosted in a Docker container on the same Alibaba Cloud ECS
  instance as the backend (simplest, used for local dev via
  `docker-compose.yml`), or as ApsaraDB RDS for PostgreSQL for a more
  "production-grade" deployment -- see `docs/ALIBABA_DEPLOYMENT.md` for both paths.

## FastAPI + SQLAlchemy

- FastAPI for the `/chat`, `/memories`, `/benchmark` endpoints
  (`backend/app/main.py`) -- async-friendly, and its `BackgroundTasks` hook is
  used to run memory extraction/consolidation after the chat reply is sent, so
  the user doesn't wait on it.
- SQLAlchemy 2.0 (typed `Mapped[...]` models in `backend/app/memory/models.py`)
  over raw SQL for the application code, while the initial schema itself
  (`backend/app/db/schema.sql`) is plain SQL so it can be applied identically
  whether via Docker's auto-init, a manual `psql` run against RDS, or a future
  migration tool.

## React + Vite (plain SPA, no Next.js)

- CLAUDE.md explicitly allows either; a plain SPA avoids SSR/routing
  complexity that adds no value for a two-view (chat + memory timeline) app on
  a hackathon timeline.
- Talks to the FastAPI backend directly over `fetch` (`frontend/src/api.js`),
  no BFF layer.

## Alibaba Cloud

- ECS hosts the FastAPI backend (and, in the simplest deployment path,
  self-hosted Postgres too) via Docker Compose -- see
  `docker-compose.prod.yml` and `docs/ALIBABA_DEPLOYMENT.md` for the exact
  commands and security group configuration.
- ApsaraDB RDS for PostgreSQL is the documented upgrade path if there's time,
  since it supports the `vector` extension and offloads the database from the
  compute instance.

## matplotlib + tiktoken (benchmark only)

- `matplotlib` renders the three-panel benchmark comparison chart
  (`backend/benchmark/run_benchmark.py::_render_chart`) to a static PNG served
  by the backend and displayed in the frontend's memory timeline view.
- `tiktoken` gives a real (not hand-waved) token count for the "context tokens
  spent on injected memory" metric -- disclosed as an approximation of Qwen's
  actual tokenizer, since `tiktoken` is OpenAI's tokenizer, but a consistent
  and real one applied identically to both agents.
