"""The benchmark (CLAUDE.md section 5, build order step 9): runs Synapse and a
naive baseline agent through the identical synthetic conversation log, at
identical simulated timestamps, tracking active memory count, context tokens
spent on injected memory, and LLM-judged recall accuracy -- especially on the
Berlin->Lisbon and Python->Rust contradiction probes, where naive storage is
expected to sometimes surface the stale fact since it never retires anything.

Every reply, extraction, score, and judgment below is a real Qwen Cloud call;
there is no fallback/mock path. A full run makes on the order of ~2000 Qwen
calls across ~163 turns x 2 agents plus checkpoint probes -- use --quick for a
cheap first pass to confirm the harness works before committing to the full run.
"""
import argparse
import json
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import tiktoken
from sqlalchemy import func, select

from app import qwen_client
from app.config import get_settings
from app.db.session import SessionLocal
from app.main import _build_system_prompt
from app.memory import consolidation, decay
from app.memory.models import Memory, User
from app.memory.retrieval import retrieve_for_query
from app.memory.scoring import extract_and_write_turn
from benchmark.conversation_log import PROBE_CHECKPOINT_DAYS, build_probes, build_turns, turn_datetime
from benchmark.naive_agent import NaiveAgent, ensure_schema, reset_user

logger = logging.getLogger("synapse.benchmark")
_settings = get_settings()
_encoder = tiktoken.get_encoding("cl100k_base")

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def count_tokens(text: str) -> int:
    return len(_encoder.encode(text))


def active_memory_count(db, user_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count()).select_from(Memory).where(Memory.user_id == user_id, Memory.is_active.is_(True))
    ).scalar_one()


def run(turns_limit: int | None = None, checkpoint_days: list[int] | None = None) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
    ensure_schema()

    db = SessionLocal()
    synapse_user = User()
    db.add(synapse_user)
    db.commit()
    db.refresh(synapse_user)
    synapse_user_id = synapse_user.id

    naive_user_id = uuid.uuid4()
    reset_user(naive_user_id)
    naive = NaiveAgent(naive_user_id, top_k=_settings.retrieval_top_k)

    turns = build_turns()
    if turns_limit:
        turns = turns[:turns_limit]
    probes = build_probes()
    checkpoint_days = set(checkpoint_days if checkpoint_days is not None else PROBE_CHECKPOINT_DAYS)

    logger.info("running benchmark: %d turns, synapse_user=%s naive_user=%s", len(turns), synapse_user_id, naive_user_id)

    per_turn_records: list[dict] = []
    checkpoint_records: list[dict] = []

    # The naive agent manages its own DB sessions internally (see NaiveAgent),
    # so its calls are safe to run on a background thread concurrently with
    # the Synapse side, which uses the single shared `db` session on this
    # (main) thread. This roughly halves per-turn wall-clock time without
    # changing what either agent actually does.
    executor = ThreadPoolExecutor(max_workers=1)

    for i, turn in enumerate(turns):
        now = turn_datetime(turn.day)
        is_last_turn_of_day = (i == len(turns) - 1) or (turns[i + 1].day != turn.day)

        # --- Naive agent kicked off in background: retrieve -> chat -> store everything, forever ---
        naive_future = executor.submit(naive.chat, turn.user_message, now)

        # --- Synapse agent (main thread): retrieve -> chat -> extract/write ---
        recalled = retrieve_for_query(db, synapse_user_id, turn.user_message, now=now)
        system_prompt = _build_system_prompt(recalled)
        synapse_reply = qwen_client.chat([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": turn.user_message},
        ])
        try:
            extract_and_write_turn(db, synapse_user_id, turn.user_message, synapse_reply, now=now)
        except Exception:
            logger.exception(
                "turn=%d day=%d: memory extraction/write failed after retries -- skipping this turn's writes, continuing run",
                turn.index, turn.day,
            )
            db.rollback()

        synapse_tokens = count_tokens(system_prompt)
        synapse_active = active_memory_count(db, synapse_user_id)

        naive_reply, naive_recalled = naive_future.result()
        naive_tokens = count_tokens(naive._system_prompt(naive_recalled))
        naive_active = naive.active_memory_count()

        per_turn_records.append({
            "turn_index": turn.index,
            "day": turn.day,
            "synapse_active_memories": synapse_active,
            "naive_active_memories": naive_active,
            "synapse_context_tokens": synapse_tokens,
            "naive_context_tokens": naive_tokens,
        })

        if synapse_active and synapse_active % _settings.consolidation_trigger_every_n_writes == 0:
            logger.info("day=%d turn=%d: triggering consolidation pass (active=%d)", turn.day, turn.index, synapse_active)
            try:
                consolidation.run_consolidation_pass(db, synapse_user_id, now=now)
                decay.run_decay_and_prune(db, now=now)
            except Exception:
                logger.exception("turn=%d day=%d: consolidation pass failed after retries -- skipping, continuing run", turn.index, turn.day)
                db.rollback()

        if is_last_turn_of_day:
            try:
                decay.run_decay_and_prune(db, now=now)  # simulated "nightly" pass
            except Exception:
                logger.exception("turn=%d day=%d: nightly decay pass failed -- skipping, continuing run", turn.index, turn.day)
                db.rollback()

        if turn.day in checkpoint_days and is_last_turn_of_day:
            for probe in probes:
                try:
                    expected = probe.answer_at(turn.day)

                    n_future = executor.submit(naive.ask_readonly, probe.question)

                    s_recalled = retrieve_for_query(db, synapse_user_id, probe.question, now=now, bump=False)
                    s_prompt = _build_system_prompt(s_recalled)
                    s_reply = qwen_client.chat([
                        {"role": "system", "content": s_prompt},
                        {"role": "user", "content": probe.question},
                    ])
                    s_judged = qwen_client.judge_recall(probe.question, expected, s_reply)

                    n_reply, _ = n_future.result()
                    n_judged = qwen_client.judge_recall(probe.question, expected, n_reply)

                    checkpoint_records.append({
                        "day": turn.day,
                        "question": probe.question,
                        "category": probe.category,
                        "expected": expected,
                        "synapse_reply": s_reply,
                        "synapse_correct": bool(s_judged["correct"]),
                        "naive_reply": n_reply,
                        "naive_correct": bool(n_judged["correct"]),
                    })
                    logger.info(
                        "probe day=%d q=%r expected=%r synapse_correct=%s naive_correct=%s",
                        turn.day, probe.question, expected, s_judged["correct"], n_judged["correct"],
                    )
                except Exception:
                    logger.exception("day=%d probe=%r failed after retries -- skipping this probe, continuing run", turn.day, probe.question)
                    db.rollback()

    executor.shutdown(wait=True)
    db.close()

    results = {"per_turn": per_turn_records, "checkpoints": checkpoint_records}
    (OUTPUT_DIR / "benchmark_results.json").write_text(json.dumps(results, indent=2))

    _render_chart(results)
    _print_summary(results)


def _render_chart(results: dict) -> None:
    per_turn = results["per_turn"]
    checkpoints = results["checkpoints"]

    turn_idx = [r["turn_index"] for r in per_turn]
    synapse_mem = [r["synapse_active_memories"] for r in per_turn]
    naive_mem = [r["naive_active_memories"] for r in per_turn]
    synapse_tok = [r["synapse_context_tokens"] for r in per_turn]
    naive_tok = [r["naive_context_tokens"] for r in per_turn]

    days = sorted(set(c["day"] for c in checkpoints))
    synapse_acc, naive_acc = [], []
    for d in days:
        day_checkpoints = [c for c in checkpoints if c["day"] == d]
        synapse_acc.append(sum(c["synapse_correct"] for c in day_checkpoints) / len(day_checkpoints))
        naive_acc.append(sum(c["naive_correct"] for c in day_checkpoints) / len(day_checkpoints))

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    axes[0].plot(turn_idx, synapse_mem, label="Synapse", color="#2563eb")
    axes[0].plot(turn_idx, naive_mem, label="Naive baseline", color="#dc2626")
    axes[0].set_xlabel("Turn")
    axes[0].set_ylabel("Active memories stored")
    axes[0].set_title("Memory count over time")
    axes[0].legend()

    axes[1].plot(turn_idx, synapse_tok, label="Synapse", color="#2563eb")
    axes[1].plot(turn_idx, naive_tok, label="Naive baseline", color="#dc2626")
    axes[1].set_xlabel("Turn")
    axes[1].set_ylabel("Context tokens spent on injected memory")
    axes[1].set_title("Token cost per query over time")
    axes[1].legend()

    if days:
        axes[2].plot(days, synapse_acc, marker="o", label="Synapse", color="#2563eb")
        axes[2].plot(days, naive_acc, marker="o", label="Naive baseline", color="#dc2626")
    axes[2].set_xlabel("Simulated day")
    axes[2].set_ylabel("Recall accuracy (LLM-judged)")
    axes[2].set_title("Recall accuracy over time")
    axes[2].set_ylim(-0.05, 1.05)
    axes[2].legend()

    fig.suptitle("Synapse vs naive baseline -- identical conversation log, identical Qwen models")
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "benchmark_results.png", dpi=150)
    logger.info("wrote chart to %s", OUTPUT_DIR / "benchmark_results.png")


def _print_summary(results: dict) -> None:
    checkpoints = results["checkpoints"]
    contradiction = [c for c in checkpoints if c["category"] == "contradiction"]
    if contradiction:
        s_acc = sum(c["synapse_correct"] for c in contradiction) / len(contradiction)
        n_acc = sum(c["naive_correct"] for c in contradiction) / len(contradiction)
        print(f"Contradiction-question accuracy -- Synapse: {s_acc:.0%}, Naive: {n_acc:.0%}")
    if results["per_turn"]:
        final_turn = results["per_turn"][-1]
        print(f"Final active memory count -- Synapse: {final_turn['synapse_active_memories']}, Naive: {final_turn['naive_active_memories']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Run only the first 30 turns / 2 checkpoints for a cheap smoke test")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run(turns_limit=30 if args.quick else None, checkpoint_days=[4, 10] if args.quick else None)
