# Synapse -- Project Documentation

**Track:** Track 1 -- MemoryAgent, Global AI Hackathon Series with Qwen Cloud
**Deadline:** 20 Jul 2026, 10:00pm GMT+1

## What Synapse is

Synapse is a personal AI assistant with long-term memory that actually
forgets. Almost every memory-agent submission to this track will embed every
message and retrieve top-k by cosine similarity forever -- that's a search
index, not memory. Synapse instead scores importance at write time, decays
salience over time at a rate that depends on whether a memory is episodic or
semantic, consolidates repeating episodic patterns into single semantic
memories during a periodic "sleep" pass, and retires memories that get
directly contradicted by newer information (e.g. a city move). All three
things the track brief explicitly asks for -- efficient storage/retrieval,
timely forgetting of outdated information, and recalling critical memories
within a limited context window -- map directly onto specific, real,
runnable code paths listed below.

## Feature -> judging criteria mapping

| Feature | Where it lives | Track brief requirement | Judging angle |
|---|---|---|---|
| Importance-scored memory writes (real Qwen structured-output call, logged reasoning) | `backend/app/memory/scoring.py`, `backend/app/qwen_client.py::score_importance` | Efficient storage | Technical depth -- not every message becomes a memory |
| Salience decay formula, per-memory-type half-life | `backend/app/memory/decay.py` | Recalling critical memories in limited context | Innovation -- decay math is the centerpiece nobody else builds |
| Consolidation ("sleep pass"): clusters repeat episodic mentions into one semantic memory | `backend/app/memory/consolidation.py::consolidate_clusters` | Efficient storage + limited context | Technical depth |
| Supersession detection: retires directly-contradicted facts (Berlin->Lisbon) | `backend/app/memory/consolidation.py::detect_and_retire_superseded` | **Timely forgetting of outdated information** (quoted directly from the brief) | Innovation |
| Retrieval re-ranked by similarity x salience, not similarity alone | `backend/app/memory/retrieval.py` | Recalling critical memories in limited context | Technical depth |
| Benchmark: identical conversation log/models, Synapse vs naive baseline, LLM-judged recall accuracy + memory count + token cost over time, charted | `backend/benchmark/` | All three, quantified | This is the single most important artifact -- "trust me, it's smart" vs "here's the number" |
| Memory timeline UI: live salience, decay/prune/consolidation indicators, benchmark toggle | `frontend/src/components/MemoryTimeline.jsx` | Recalling critical memories (demo-visible) | Lets judges *see* the mechanism, not just hear about it |
| Real Alibaba Cloud deployment (ECS + Docker, RDS-upgradeable) | `docker-compose.prod.yml`, `docs/ALIBABA_DEPLOYMENT.md` | Submission requirement | Proof of deployment |

## Build status (as-built vs planned)

This section is kept honest and current -- see CLAUDE.md's non-negotiables:
nothing here should claim a capability that isn't backed by a real, runnable
code path.

- [x] Postgres + pgvector schema, verified locally with a real vector
      insert/cosine-distance round trip (`backend/app/db/schema.sql`)
- [x] Qwen client wrapper for chat, embeddings, and every structured-output
      call the memory engine needs (`backend/app/qwen_client.py`), with an
      isolation test suite (`backend/tests/test_qwen_client.py`) ready to run
      against a real API key
- [x] Memory write path: extraction -> importance scoring -> embedding -> insert
      (`backend/app/memory/scoring.py`)
- [x] Retrieval path: embed -> cosine search -> salience re-rank -> bump recall stats
      (`backend/app/memory/retrieval.py`)
- [x] `/chat` endpoint, wired end-to-end (`backend/app/main.py`)
- [x] Decay job, verified against a real Postgres instance with backdated
      timestamps (no wall-clock waiting needed) --
      `backend/tests/test_decay.py`, 4/4 passing
- [x] Consolidation + supersession detection job (`backend/app/memory/consolidation.py`)
- [x] Naive baseline agent, same models, no decay/consolidation/pruning
      (`backend/benchmark/naive_agent.py`)
- [x] Benchmark harness: 163-turn / 44-simulated-day synthetic conversation
      log with two deliberate contradictions, LLM-judged recall scoring, chart
      generation (`backend/benchmark/`)
- [x] Frontend: chat view + memory timeline view with live salience, decay/
      prune/consolidation indicators, and a benchmark-chart toggle
      (`frontend/src/`)
- [ ] **Live Qwen API verification**: every Qwen-dependent code path above is
      written and structurally tested, but end-to-end verification against
      the real DashScope API is pending a valid `QWEN_API_KEY` in `.env`
- [ ] **Full benchmark run**: the harness is complete and import-verified;
      running it end to end (and thus generating `benchmark_results.png` with
      real numbers) is pending the live API key above
- [ ] **Alibaba Cloud deployment**: `docker-compose.prod.yml`,
      `frontend/Dockerfile`, and the full walkthrough in
      `docs/ALIBABA_DEPLOYMENT.md` are ready; actually provisioning the ECS
      instance (and optionally RDS) requires an Alibaba Cloud account, which
      hasn't been created yet
- [ ] **Demo video**: not recorded yet -- depends on the live deployment and
      a completed benchmark run above being in place first, so the video shows
      real numbers and a real recall-across-sessions demo rather than a mockup

## Benchmark methodology (disclosed)

`backend/benchmark/run_benchmark.py` runs Synapse and the naive baseline
through the identical synthetic conversation (`backend/benchmark/conversation_log.py`)
at identical simulated timestamps (dates are backdated via the `now` parameter
threaded through the write/retrieval/decay functions, rather than waiting real
wall-clock days). At each of 9 checkpoint days it asks both agents 7 fixed
recall questions -- including two deliberate contradictions (a city move and a
programming-language switch) -- and scores each reply with Qwen itself as an
LLM judge (`qwen_client.judge_recall`), which is disclosed here as the scoring
method rather than a hidden implementation detail. No benchmark numbers are
included in this document until the harness has actually been run against the
real API -- see the build status above.
