"""Isolation tests for every Qwen Cloud call the memory engine depends on
(build order step 2: "test each in isolation with real API calls before
wiring into the pipeline"). These hit the real DashScope API -- they will
fail fast with a clear auth error if QWEN_API_KEY in .env is still the
placeholder, which is the intended behavior (no offline/mock fallback).

Run with: backend/.venv/Scripts/python.exe -m pytest backend/tests/test_qwen_client.py -v -s
"""
from app import qwen_client


def test_embed_texts_returns_correct_dimension():
    vectors = qwen_client.embed_texts(["I live in Berlin.", "I'm allergic to shellfish."])
    assert len(vectors) == 2
    for v in vectors:
        assert len(v) == 1024
        assert any(abs(x) > 1e-9 for x in v)  # not an all-zero placeholder


def test_chat_returns_nonempty_reply():
    reply = qwen_client.chat([
        {"role": "system", "content": "You are a terse assistant."},
        {"role": "user", "content": "Reply with exactly the word: pong"},
    ])
    assert reply.strip()
    print("chat reply:", reply)


def test_score_importance_explicit_request_scores_high():
    result = qwen_client.score_importance("Please remember: I am allergic to penicillin, it's a serious allergy.")
    print("importance result:", result)
    assert 0.0 <= result["importance"] <= 1.0
    assert result["memory_type"] in ("episodic", "semantic")
    assert result["importance"] > 0.6  # explicit + safety-relevant should score high
    assert result["reasoning"]


def test_score_importance_trivia_scores_lower_than_explicit_request():
    trivia = qwen_client.score_importance("It's raining outside today.")
    explicit = qwen_client.score_importance("Please remember, this is important: my flight is on the 5th.")
    print("trivia:", trivia, "explicit:", explicit)
    assert trivia["importance"] < explicit["importance"]


def test_extract_memory_candidates_finds_stated_preference():
    candidates = qwen_client.extract_memory_candidates(
        user_message="By the way, I'm vegetarian, so please keep that in mind for any food suggestions.",
        assistant_message="Got it, I'll keep that in mind!",
    )
    print("candidates:", candidates)
    assert isinstance(candidates, list)
    assert any("vegetarian" in c.lower() for c in candidates)


def test_extract_memory_candidates_ignores_pure_chitchat():
    candidates = qwen_client.extract_memory_candidates(
        user_message="Haha nice, thanks!",
        assistant_message="You're welcome!",
    )
    print("candidates (chit-chat):", candidates)
    assert candidates == [] or len(candidates) <= 1


def test_detect_supersession_true_for_contradiction():
    result = qwen_client.detect_supersession("User lives in Berlin.", "User just moved to Lisbon.")
    print("supersession result:", result)
    assert result["supersedes"] is True


def test_detect_supersession_false_for_unrelated_facts():
    result = qwen_client.detect_supersession("User lives in Berlin.", "User is allergic to shellfish.")
    print("supersession result (unrelated):", result)
    assert result["supersedes"] is False


def test_consolidate_cluster_produces_single_summary():
    result = qwen_client.consolidate_cluster([
        "User mentioned working on the Synapse project, building the Postgres schema.",
        "User mentioned making progress on Synapse, wiring up the Qwen embeddings client.",
        "User mentioned Synapse progress, implementing the salience decay formula.",
    ])
    print("consolidation result:", result)
    assert "synapse" in result["consolidated_memory"].lower()
