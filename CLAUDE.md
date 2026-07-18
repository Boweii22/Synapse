# Project: Synapse — A Memory Agent That Actually Forgets

**Hackathon:** Global AI Hackathon Series with Qwen Cloud
**Track:** Track 1 — MemoryAgent
**Deadline:** 20 Jul 2026 @ 10:00pm GMT+1

This file is the spec. Read it fully before writing any code. Build in the order
listed under "Build Order." Nothing in this project should be hardcoded, mocked,
faked, or simulated in the final submission — every claim we make in the demo
video and write-up must be backed by a real, runnable code path. If something
can't be done for real in the time available, cut it from scope rather than
fake it.

---

## 1. The Core Idea (read this first, it's the whole point)

Almost every "AI memory agent" submitted to this track will do the same thing:
embed every message, dump it in a vector DB, retrieve top-k by cosine similarity
at query time. That is not memory. That is a search index. It never forgets
anything, it treats a passing comment about the weather with the same weight
as "I'm allergic to penicillin," and it gets slower and dumber as it grows
because retrieval gets noisier with more near-duplicate junk in the index.

The actual track brief asks for three specific things:
1. Efficient storage and retrieval
2. **Timely forgetting of outdated information**
3. Recalling critical memories within limited context windows

Item 2 is the one nobody builds, because naive vector storage has no concept
of "outdated." We are going to build it for real, with actual decay math,
actual consolidation, and an actual before/after benchmark proving it works
better than the naive approach. This is our whole competitive edge: we're not
claiming to be smarter, we're proving it with numbers on a chart.

**Product framing:** Synapse is a personal AI assistant with long-term memory
across sessions — the kind of assistant you'd actually want, that remembers
your ongoing projects, recurring preferences, and unresolved threads over
weeks of use, without needing you to repeat yourself, and without slowly
turning into a bloated, confused mess of stale trivia.

---

## 2. Architecture Overview

```
┌─────────────────┐      ┌──────────────────────┐      ┌─────────────────────┐
│   Web Frontend   │◄────►│   FastAPI Backend     │◄────►│  Qwen Cloud (DashScope)│
│  (chat + memory  │      │  (Alibaba Cloud ECS)  │      │  - qwen-max (chat)    │
│   timeline UI)   │      │                       │      │  - qwen-max (scoring) │
└─────────────────┘      │  ┌─────────────────┐  │      │  - text-embedding-v3  │
                          │  │  Memory Engine   │  │      └─────────────────────┘
                          │  │  - salience calc │  │
                          │  │  - decay job     │  │      ┌─────────────────────┐
                          │  │  - consolidation │  │◄────►│   Postgres + pgvector │
                          │  │  - retrieval     │  │      │  (Alibaba Cloud       │
                          │  └─────────────────┘  │      │   RDS or self-hosted) │
                          └──────────────────────┘      └─────────────────────┘
```

Everything runs on Alibaba Cloud (required for the "Proof of Alibaba Cloud
Deployment" submission requirement) — FastAPI backend on ECS, Postgres with
pgvector either as ApsaraDB RDS for PostgreSQL or self-hosted on the same ECS
instance if RDS setup eats too much time. Either is a legitimate "real
deployment," but RDS is more impressive if time allows.

---

## 3. The Memory Model (the actual innovation — build this carefully)

### 3.1 Memory record schema

Every stored memory is a row, not just a raw chat log line:

```sql
CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    content TEXT NOT NULL,              -- the memory itself, in natural language
    embedding VECTOR(1024) NOT NULL,     -- from Qwen text-embedding-v3
    memory_type TEXT NOT NULL,           -- 'episodic' | 'semantic' | 'consolidated'
    importance_score FLOAT NOT NULL,     -- 0-1, set by Qwen at write time (see 3.2)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_recalled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recall_count INT NOT NULL DEFAULT 0,
    salience FLOAT NOT NULL,             -- computed, decays over time (see 3.3)
    source_memory_ids UUID[] DEFAULT NULL, -- populated when this is a consolidation of others
    is_active BOOLEAN NOT NULL DEFAULT true, -- false = pruned (soft delete, keep for the demo/benchmark)
    pruned_at TIMESTAMPTZ DEFAULT NULL,
    pruned_reason TEXT DEFAULT NULL      -- 'decayed_below_threshold' | 'superseded' | 'consolidated'
);
CREATE INDEX ON memories USING ivfflat (embedding vector_cosine_ops);
```

Never hardcode a fixed set of "memory categories" or a canned list of example
memories anywhere in the codebase — the schema and scoring must work for
arbitrary user input, and this should be provable by testing it with a
conversation script that mentions things never seen in development.

### 3.2 Importance scoring at write time

When a new memory candidate is extracted from a conversation turn, call Qwen
(qwen-max) with a structured-output prompt that scores it on:
- **Explicit importance signal** (did the user say "remember this," "don't
  forget," etc. — weight this high but don't require it)
- **Decision-relevance** (is this the kind of fact that should change how the
  assistant behaves later — an ongoing project, a stated preference, a
  constraint, an unresolved task — vs. a passing remark)
- **Specificity** (concrete facts score higher than vague chit-chat)

This must be a real API call returning a real structured score, not a
keyword-matching heuristic. Prompt Qwen to return strict JSON:
`{"importance": 0.0-1.0, "memory_type": "episodic"|"semantic", "reasoning": "..."}`.
Log the reasoning — it's genuinely useful for the demo ("look, it explains
why it thinks this matters").

### 3.3 Salience decay — the actual math

This is the centerpiece. Salience is recomputed lazily (at retrieval time and
in the nightly decay job) using a formula that combines:

```
salience(t) = importance_score
              × recall_boost(recall_count)
              × exp(-λ × hours_since_last_recall)
```

Where:
- `recall_boost(n) = 1 + log(1 + n)` — memories that get recalled again get
  reinforced (this mimics spaced-repetition / use-it-or-lose-it), diminishing
  returns via log so one memory can't dominate forever
- `λ` (decay rate) is **not a single global constant** — it should differ by
  memory_type. Semantic facts (stable preferences, "I'm vegetarian") decay
  slowly. Episodic details (what you talked about on a specific Tuesday)
  decay faster unless reinforced. Pick sane starting half-lives (e.g.
  semantic ≈ 30 days, episodic ≈ 3 days) and expose them as config, not
  magic numbers buried in code.

### 3.4 Consolidation (the "sleep" pass)

A background job (run on a schedule, or triggered after N new memories are
written — your choice, but it must actually run, not be a no-op placeholder):
1. Cluster memories by embedding similarity above a threshold.
2. For clusters of episodic memories that repeat a pattern (e.g. five
   separate mentions of working on "the Synapse project"), call Qwen to
   generate ONE consolidated semantic memory summarizing the pattern, tag it
   `memory_type = 'consolidated'`, link `source_memory_ids`, and mark the
   originals `is_active = false` with `pruned_reason = 'consolidated'`.
2. For memories that are directly superseded (e.g. "I live in Berlin" then
   later "I just moved to Lisbon"), detect the contradiction via Qwen and
   retire the old one rather than let both sit in the index confusing
   retrieval — this is "timely forgetting of outdated information," literally
   quoting the brief.

### 3.5 Pruning

A separate lightweight job (can run in the same pass) marks `is_active =
false` for any memory whose computed salience drops below a configurable
floor. Do **not** hard-delete rows — keep them soft-deleted so the benchmark
(section 5) can compare "what if we'd kept everything" vs. "what we actually
kept."

### 3.6 Retrieval

At query time:
1. Embed the incoming query (Qwen text-embedding-v3).
2. Pull top-N by cosine similarity from `is_active = true` memories only.
3. Re-rank the candidates by `similarity × current_salience`, not similarity
   alone — this is what makes retrieval recall *what matters*, not just
   what's textually similar.
4. Take the top-K after re-ranking, inject into the Qwen chat context, bump
   `recall_count` and `last_recalled_at` on whatever got used.

---

## 4. Chat Agent

- Backend endpoint `POST /chat` takes `{user_id, message}`, runs retrieval
  (3.6), builds a system prompt with the recalled memories injected, calls
  Qwen-max for the actual reply, and — as a separate async step — extracts
  new memory candidates from the turn and writes them via the pipeline in
  3.2. Extraction should also be a real Qwen call ("does this turn contain
  anything worth remembering long-term? Extract as discrete memory
  candidates"), not string matching.
- Support real multi-session continuity: a session is just a `user_id` with
  no session token expiry — the point of the whole project is that memory
  persists *across* sessions, so design so that closing and reopening the
  chat, or waiting days, provably still recalls the same things.

---

## 5. The Benchmark (do not skip this — it's your strongest evidence)

Build a second, deliberately naive baseline agent using the same Qwen model
but "store everything, retrieve top-k by cosine similarity, never decay,
never consolidate, never prune." Same embedding model, same chat model —
the only difference is the memory strategy, so the comparison is fair.

Then build a benchmark script that:
1. Feeds both agents the same synthetic but realistic multi-session
   conversation log (aim for 150-300 turns across a simulated 30+ "days,"
   with a mix of trivia, real preferences, project updates, and a few
   deliberate contradictions/updates like the Berlin→Lisbon example).
2. At intervals, asks both agents the same recall questions about things
   said earlier (including things said 100+ turns ago) and scores answer
   accuracy (can use Qwen itself as a judge, or manual scoring against an
   answer key — an LLM judge is fine and worth disclosing as such).
3. Tracks and logs, per turn: number of active memories stored, average
   context tokens spent on injected memory, and recall accuracy.

Output this as an actual chart (matplotlib is fine, export PNG, or render it
live in the frontend) showing:
- Memory count over time: naive baseline grows linearly forever; Synapse
  flattens/plateaus due to consolidation+pruning.
- Token cost per query over time: naive baseline grows as index grows;
  Synapse stays roughly flat.
- Recall accuracy over time on the seeded facts, especially on
  contradiction/update questions ("where do I live now?") — Synapse should
  answer with the current fact; the naive baseline is likely to sometimes
  surface the stale one since it never retired it.

This chart is the single most important artifact for the "Innovation &
AI Creativity" and "Technical Depth" judging criteria — it's the difference
between "trust me, it's smart" and "here's the number."

---

## 6. Frontend

Two views, kept simple but real (no fake data anywhere):

1. **Chat view** — normal chat interface talking to Synapse.
2. **Memory timeline view** — a real-time visualization of the user's
   memory store: list/graph of active memories with their current salience,
   a visual indicator of recently decayed/pruned/consolidated items, and a
   toggle to show the benchmark chart from section 5. This is what makes
   the judges *see* the mechanism working instead of just hearing about it
   in the video narration.

Keep the frontend a plain React SPA (or Next.js if preferred) calling the
FastAPI backend directly. No need for a native mobile client for this track.

---

## 7. Repo Layout

```
synapse/
├── CLAUDE.md                    <- this file
├── backend/
│   ├── app/
│   │   ├── main.py               <- FastAPI app, /chat, /memories, /benchmark endpoints
│   │   ├── memory/
│   │   │   ├── scoring.py        <- importance scoring (Qwen calls)
│   │   │   ├── decay.py          <- salience formula + decay job
│   │   │   ├── consolidation.py  <- clustering + consolidation job
│   │   │   ├── retrieval.py      <- embed + re-rank retrieval
│   │   │   └── models.py         <- SQLAlchemy models matching schema in 3.1
│   │   ├── qwen_client.py        <- thin wrapper over DashScope API
│   │   └── config.py             <- decay half-lives, thresholds, all as env-configurable
│   ├── benchmark/
│   │   ├── naive_agent.py        <- the baseline for comparison
│   │   ├── conversation_log.py   <- synthetic 30-day conversation generator
│   │   └── run_benchmark.py      <- produces the chart(s) in section 5
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/ (chat view + memory timeline view)
│   └── package.json
├── docs/
│   ├── ARCHITECTURE.md           <- diagram + explanation (submission requirement)
│   ├── TECH_STACK.md             <- why Qwen Cloud, why pgvector, deploy notes
│   └── PROJECT_DOCUMENTATION.md  <- full write-up, status as-built vs planned
├── scripts/
│   └── dev-up.sh                 <- local orchestration
├── .env.example
├── docker-compose.yml
└── LICENSE                       <- MIT, must be visible in repo About section
```

---

## 8. Build Order

1. Postgres schema + pgvector setup, confirm embeddings can be written/queried locally.
2. Qwen client wrapper — chat, embeddings, structured-output scoring calls. Test each in isolation with real API calls before wiring into the pipeline.
3. Memory write path: extraction → importance scoring → embedding → insert.
4. Retrieval path: embed query → similarity search → salience re-rank → inject into chat.
5. `/chat` endpoint end-to-end, manually verify multi-turn recall works.
6. Decay job (3.3) — verify salience actually drops over simulated time (you can fast-forward `created_at`/`last_recalled_at` in a test to avoid waiting real days).
7. Consolidation + pruning job (3.4, 3.5) — verify with a deliberately repetitive/contradictory test conversation that it merges and retires correctly.
8. Naive baseline agent (section 5) — deliberately simple, same models, no decay/consolidation.
9. Benchmark script + chart generation — this is high priority, don't leave it to the last hours.
10. Frontend chat view, then memory timeline view with live salience + benchmark chart.
11. Deploy backend + Postgres to Alibaba Cloud. Confirm and screenshot/link the actual deployment (ECS console, RDS instance, or equivalent) for the submission's "Proof of Alibaba Cloud Deployment" requirement.
12. Architecture diagram (docs/ARCHITECTURE.md) — real diagram of the system in section 2, not a stock image.
13. Record the 3-minute demo video: show a real multi-session conversation recalling something from days earlier, show the memory timeline UI, show the benchmark chart, narrate the decay/consolidation mechanism plainly.
14. Write docs/PROJECT_DOCUMENTATION.md and the submission text description, explicitly mapping features to each judging criterion.

---

## 9. Non-Negotiables

- No hardcoded example memories, canned responses, or fake benchmark numbers anywhere in the final code or demo. If the decay job doesn't work yet, don't fake its output — fix it or cut the claim.
- Every Qwen call must be a real API call against Qwen Cloud, using a real `QWEN_API_KEY`.
- The benchmark comparison must run both agents through the identical conversation log — no cherry-picking.
- Config values (decay half-lives, pruning threshold, re-rank weights) live in `config.py` / env vars, not magic numbers scattered in logic files.
- Deployment must be real and verifiable — a reviewer should be able to hit a live endpoint or see clear proof in the repo.

## 10. Submission Checklist (map back to Devpost requirements)

- [ ] Public repo, MIT LICENSE visible in About section
- [ ] Proof-of-Alibaba-Cloud-deployment link to a specific code/config file
- [ ] Architecture diagram in docs/
- [ ] 3-minute demo video, public on YouTube/Vimeo
- [ ] Text description of features/functionality
- [ ] Track identified: Track 1 — MemoryAgent
- [ ] (Optional) blog/social post about the build journey for the Blog Post Prize
