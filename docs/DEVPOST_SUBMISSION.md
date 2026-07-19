# Devpost submission text — Synapse

Track: Track 1 — MemoryAgent

---

## Tagline (short description)

A memory agent that actually forgets — real salience decay, consolidation,
and contradiction detection, proven against a naive baseline with real
benchmark numbers, not just a demo.

---

## Inspiration

Every "AI memory agent" looks the same: embed every message, dump it in a
vector DB, retrieve top-k by cosine similarity forever. That's not memory,
it's a search index — it never forgets, it treats "nice weather today" the
same as "I'm allergic to penicillin," and it gets noisier and slower as it
grows. The track brief explicitly asks for three things: efficient storage
and retrieval, **timely forgetting of outdated information**, and recalling
critical memories within a limited context window. Almost nobody builds the
second one, because naive vector storage has no concept of "outdated." We
built it for real, with actual decay math, actual consolidation, and an
actual before/after benchmark proving it works better than the naive
approach.

## What it does

Synapse is a personal AI assistant with long-term memory that persists
across sessions. Every memory it writes is scored for importance by Qwen at
write time, then decays over time using a real formula —
`salience(t) = importance × recall_boost(recall_count) × e^(−λ·hours_since_recall)`
— with a decay rate that differs by memory type (stable preferences and
facts decay slowly; one-off episodic details decay fast unless reinforced).
A background consolidation pass clusters repeated episodic mentions into a
single semantic memory, and separately detects and retires memories that get
directly contradicted by newer information (e.g. a city move) — this is the
"timely forgetting" the brief asks for, verbatim. Retrieval re-ranks
candidates by relevance and current salience, not similarity alone, so what
gets recalled is what still matters, not just what's textually similar. A
memory timeline UI shows this happening live: active memories, salience
tiers, decay projections, and a real-time feed of what just got
decayed/pruned/consolidated.

## How we built it

FastAPI backend, Postgres + pgvector for storage, React frontend, every LLM
call (chat, embeddings, importance scoring, extraction, contradiction
detection, consolidation, and the benchmark's LLM judge) going to real Qwen
Cloud endpoints — no mocked or hardcoded model output anywhere. We built a
second, deliberately naive baseline agent — identical chat model, identical
embedding model, the only difference being "store everything forever, never
decay, never consolidate, never prune" — and ran both through the identical
synthetic 110-turn, simulated-multi-day conversation (including two
deliberate contradictions) to produce a real, charted before/after
comparison rather than asserting the approach works. Deployed live on
Alibaba Cloud ECS running Docker Compose (backend, frontend, and Postgres
all on the same instance).

## Challenges we ran into

Getting real Qwen Cloud API access working end-to-end took longer than
expected (workspace-specific endpoints, account verification). The
benchmark harness surfaced two genuine bugs only visible at 100+ turns of
scale: a consolidation function using real wall-clock time instead of
simulated benchmark time (so a stale fact could look "newer" than the
correct one and win a contradiction check it should have lost), and a
similarity pre-filter gate that was too strict for a real contradiction
phrased in very different words (measured similarity as low as 0.59 against
a 0.75 gate). We root-caused both directly from the database rather than
guessing, fixed both, and verified the fixes with targeted regression tests
plus a live end-to-end test against the deployed app — documented honestly
in the repo, including the pre-fix benchmark numbers we didn't get to
re-measure given the time remaining.

## Accomplishments that we're proud of

A real, quantified benchmark: memory count staying roughly flat (117) vs. a
naive baseline growing linearly (220), token cost per query staying flat
(~130-170) vs. the naive baseline spiking past 2000, and an honest recall
accuracy comparison (71% vs. 95%) where we found and disclosed *why* our
number was lower instead of hiding it — including root-causing it down to
specific config values and a specific re-ranking formula, then fixing both
with real regression tests. We think a chart with a number we don't love,
fully explained, is stronger evidence than a chart that only tells a
flattering story.

## What we learned

Salience decay and consolidation are worth almost nothing without a real
benchmark to check them against — several of the bugs we found (the
consolidation timestamp bug especially) were completely invisible until we
had 100+ real turns of scale and could see wrong answers appear, then trace
them back to a root cause in the actual data.

## What's next for Synapse

A live per-user analytics view (memory count / token cost over your own
real usage — the underlying data already exists in the schema, it's a
read-only chart away) and a shadow naive-baseline pipeline to make the
Synapse-vs-naive comparison continuously verifiable on real usage, not just
a one-time offline benchmark run.
