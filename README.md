# Synapse

A personal AI assistant with long-term memory that actually forgets. Built for the **Global AI Hackathon Series with Qwen Cloud** (**Track 1: MemoryAgent**).

Almost every "memory agent" does the same thing: embed every message, dump it in a vector DB, retrieve top-k by cosine similarity forever. That's a search index, not memory — it never forgets anything, weighs a passing comment about the weather the same as "I'm allergic to penicillin," and gets noisier and slower the longer you use it. Synapse instead scores importance at write time, decays salience over time at a rate that depends on whether a memory is episodic or semantic, consolidates repeating episodic patterns into single semantic memories, and retires memories that get directly contradicted by newer information — and proves all of it works with a real benchmark against a naive baseline, not just a claim.

### Why forgetting is the hard part

It sounds backwards: shouldn't an AI assistant that remembers *more* be better? In practice, no — and this is the part almost nobody builds.

Think about how your own memory works. You don't recall every sentence anyone's ever said to you with equal weight — you remember your allergies, your family, stable facts about your life, and you let a random Tuesday's small talk fade. That selective forgetting is what makes memory *useful*. Remove it, and you get three concrete failure modes:

1. **It gets slower and dumber, not smarter, the longer you use it.** Every "lol nice," every passing comment, gets stored forever with the same weight as a real fact. Eventually the assistant has to search a mountain of accumulated noise to find the one thing that matters — more storage, worse recall.
2. **It can confidently give you the wrong answer.** Tell it "I live in Berlin," then months later "I just moved to Lisbon" — a system with no concept of contradiction now has *both* facts sitting there with similar relevance, and may resurface the stale one. This isn't hypothetical: it's exactly what our benchmark measures, and exactly where the naive baseline fails and Synapse doesn't.
3. **It gets more expensive and less accurate over time**, mechanically — every stored memory adds tokens to the context window and noise to retrieval, so an ever-growing pile of unforgotten trivia makes every future query slower and costlier to answer well.

Synapse's decay + consolidation + contradiction-detection pipeline exists to solve exactly this: keep what still matters, merge what's repetitive, retire what's been overtaken by newer information — so the assistant gets *more* useful the longer you use it, not more cluttered.

- Scores every memory's importance with a real Qwen call at write time, with the reasoning logged
- Decays salience over time — stable facts fade slowly, one-off details fade fast unless reinforced
- Consolidates repeating episodic mentions into one semantic memory during a periodic "sleep" pass
- Detects when a new memory contradicts an old one (e.g. a city move) and retires the outdated one automatically
- Re-ranks retrieval by similarity × current salience, not similarity alone
- Ships a controlled benchmark: an identical conversation run through Synapse and a naive "store everything, never forget" baseline, using the same models, charted side by side

## Repo layout

| Folder | Purpose |
|---|---|
| `backend/app/` | FastAPI backend — `/chat`, `/memories`, `/benchmark` endpoints, the memory engine (scoring, decay, consolidation, retrieval), the Qwen client |
| `backend/benchmark/` | The naive baseline agent, the synthetic 44-day conversation log, and the benchmark runner that produces the comparison chart |
| `backend/tests/` | Isolation tests for the Qwen client and the decay/pruning math |
| `frontend/` | React (Vite) chat UI + live memory timeline view |
| `docs/` | Architecture diagram, tech stack rationale, full project write-up, Alibaba Cloud deployment guide |
| `docker-compose.yml` / `docker-compose.prod.yml` | Local dev stack / production stack (adds the built frontend container) |
| `CLAUDE.md` | The original project spec this was built against |

## Prerequisites

- Docker (Postgres + pgvector, backend, frontend all run in containers)
- A Qwen Cloud API key (`QWEN_API_KEY`) — see `docs/TECH_STACK.md` for where to get one and the base-URL/model-name gotchas we ran into
- Node.js (only if you want to run the frontend outside Docker for development)

## Running it locally

```bash
cp .env.example .env
# edit .env: fill in QWEN_API_KEY (and QWEN_BASE_URL if your workspace uses a
# non-default endpoint -- see docs/TECH_STACK.md)

docker compose up -d postgres
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173`. Chat with it, then check the Memory Timeline tab to watch salience, decay, and consolidation happen in real time.

To run the full benchmark and generate the comparison chart:

```bash
cd backend
python -m benchmark.run_benchmark          # full run (163 turns, several hours of real API calls)
python -m benchmark.run_benchmark --quick   # 30-turn smoke test
```

## Deployment

Deployed live on Alibaba Cloud ECS — see `docs/ALIBABA_DEPLOYMENT.md` for the full walkthrough and `docker-compose.prod.yml` for the deployment config (the "Proof of Alibaba Cloud Deployment" submission requirement).

## Status

MVP complete and verified end-to-end with real Qwen Cloud API calls throughout: memory write/scoring, decay, consolidation (including a live-caught contradiction retirement during benchmark testing), retrieval re-ranking, and a full 163-turn/44-day benchmark run against the naive baseline. Deployed and reachable on Alibaba Cloud ECS. See `docs/PROJECT_DOCUMENTATION.md` → "Build status" for the detailed as-built-vs-planned breakdown.

## License

MIT — see `LICENSE`.
