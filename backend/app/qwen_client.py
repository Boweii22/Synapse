"""Thin wrapper over the DashScope (Qwen Cloud) OpenAI-compatible API.

Every function here makes a real network call to Qwen Cloud. There is no
offline/mock fallback path — if QWEN_API_KEY is missing or invalid, calls
raise, on purpose, so a broken key is loud rather than silently faked.
"""
import json
import logging
from typing import Literal

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings

logger = logging.getLogger("synapse.qwen")

_settings = get_settings()

_client = OpenAI(
    api_key=_settings.qwen_api_key,
    base_url=_settings.qwen_base_url,
)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of strings with Qwen text-embedding-v3. Returns 1024-dim vectors."""
    if not texts:
        return []
    resp = _client.embeddings.create(
        model=_settings.qwen_embedding_model,
        input=texts,
        dimensions=_settings.embedding_dim,
        encoding_format="float",
    )
    return [item.embedding for item in resp.data]


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def chat(messages: list[dict], temperature: float = 0.7, max_tokens: int = 1024) -> str:
    """Real chat completion call against qwen-max. Returns the assistant text."""
    resp = _client.chat.completions.create(
        model=_settings.qwen_chat_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def _extract_json(raw: str) -> dict | list:
    """Qwen sometimes wraps JSON in markdown fences despite instructions; strip them."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
def chat_json(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> dict | list:
    """Chat call constrained to return parseable JSON. Raises if the model won't comply
    after retries -- callers should not swallow this into a fabricated default."""
    resp = _client.chat.completions.create(
        model=_settings.qwen_chat_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or ""
    return _extract_json(raw)


def _chat_json_retrying(system_prompt: str, user_prompt: str, validate, temperature: float = 0.2, max_attempts: int = 3):
    """Like chat_json, but also retries when the response parses as JSON yet has the
    wrong shape (e.g. `{}` instead of `{"candidates": [...]}`) -- chat_json's own
    @retry only covers network/parse failures, not a successfully-returned response
    that just doesn't match the expected schema. Smaller/faster models are more
    prone to this than larger ones, so this matters more since switching to a
    faster chat model tier for benchmark throughput. `validate(result)` should
    raise ValueError/KeyError/TypeError on a bad shape; still raises after
    max_attempts so a persistent failure is loud, not silently swallowed.
    """
    last_err: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = chat_json(system_prompt, user_prompt, temperature=temperature)
            validate(result)
            return result
        except (ValueError, KeyError, TypeError) as e:
            last_err = e
            logger.warning("qwen structured response had unexpected shape (attempt %d/%d): %s", attempt, max_attempts, e)
    raise last_err


IMPORTANCE_SYSTEM_PROMPT = """You are the memory-importance scorer inside a personal AI \
assistant's long-term memory system. Given a single piece of candidate memory text \
extracted from a conversation, score how important it is to retain long-term.

Score on:
- Explicit signal: did the user explicitly ask to remember/not forget this? (strong signal, not required)
- Decision-relevance: is this the kind of fact that should change the assistant's future \
behavior -- an ongoing project, a stated preference, a constraint, an unresolved task -- \
versus a passing remark with no lasting relevance?
- Specificity: concrete, checkable facts score higher than vague chit-chat.

Respond with strict JSON only, matching this exact shape:
{"importance": <float 0.0-1.0>, "memory_type": "episodic" | "semantic", "reasoning": "<one sentence>"}

"semantic" = a stable fact/preference/trait that will likely still be true in a month.
"episodic" = a specific event/detail tied to this particular conversation/moment.
"""


def _validate_importance(result):
    if not isinstance(result, dict) or "importance" not in result:
        raise ValueError(f"Qwen returned malformed importance score: {result!r}")
    if result.get("memory_type") not in ("episodic", "semantic"):
        raise ValueError(f"Qwen returned invalid memory_type: {result!r}")


def score_importance(candidate_text: str) -> dict:
    result = _chat_json_retrying(IMPORTANCE_SYSTEM_PROMPT, candidate_text, _validate_importance)
    result["importance"] = max(0.0, min(1.0, float(result["importance"])))
    return result


BATCH_IMPORTANCE_SYSTEM_PROMPT = """You are the memory-importance scorer inside a personal AI \
assistant's long-term memory system. You will be given a JSON list of candidate memory texts \
extracted from a conversation. Score each one independently on:
- Explicit signal: did the user explicitly ask to remember/not forget this? (strong signal, not required)
- Decision-relevance: is this the kind of fact that should change the assistant's future \
behavior -- an ongoing project, a stated preference, a constraint, an unresolved task -- \
versus a passing remark with no lasting relevance?
- Specificity: concrete, checkable facts score higher than vague chit-chat.

Respond with strict JSON only, matching this exact shape, with one entry per input candidate \
IN THE SAME ORDER:
{"scores": [{"importance": <float 0.0-1.0>, "memory_type": "episodic" | "semantic", "reasoning": "<one sentence>"}, ...]}

"semantic" = a stable fact/preference/trait that will likely still be true in a month.
"episodic" = a specific event/detail tied to this particular conversation/moment.
"""


def score_importance_batch(candidate_texts: list[str]) -> list[dict]:
    """Scores multiple candidates in a single call instead of one call each --
    a real latency/throughput optimization, not a change in what gets scored."""
    if not candidate_texts:
        return []
    prompt = json.dumps(candidate_texts)

    def validate(result):
        if not isinstance(result, dict) or "scores" not in result or len(result["scores"]) != len(candidate_texts):
            raise ValueError(f"Qwen returned malformed batch importance result: {result!r}")
        for s in result["scores"]:
            if s.get("memory_type") not in ("episodic", "semantic"):
                raise ValueError(f"Qwen returned invalid memory_type: {s!r}")

    result = _chat_json_retrying(BATCH_IMPORTANCE_SYSTEM_PROMPT, prompt, validate)
    scores = result["scores"]
    for s in scores:
        s["importance"] = max(0.0, min(1.0, float(s["importance"])))
    return scores


EXTRACTION_SYSTEM_PROMPT = """You are the memory-extraction module inside a personal AI \
assistant. Given one turn of conversation (a user message and the assistant's reply), \
identify any discrete facts worth remembering long-term: stated preferences, ongoing \
projects, constraints, unresolved tasks, biographical facts, explicit "remember this" \
requests, or corrections to previously stated facts.

Do not extract generic chit-chat, pleasantries, or the assistant's own generic advice.
Each candidate should be a short, self-contained natural-language statement written from \
the user's perspective (e.g. "User is allergic to penicillin"), not a copy of the raw \
message.

Respond with strict JSON only, matching this exact shape:
{"candidates": ["<statement 1>", "<statement 2>", ...]}

If there is nothing worth remembering, respond with {"candidates": []}. Do not invent \
facts that were not stated.
"""


def _validate_extraction(result):
    if not isinstance(result, dict) or "candidates" not in result:
        raise ValueError(f"Qwen returned malformed extraction result: {result!r}")


def extract_memory_candidates(user_message: str, assistant_message: str) -> list[str]:
    prompt = f"User: {user_message}\n\nAssistant: {assistant_message}"
    result = _chat_json_retrying(EXTRACTION_SYSTEM_PROMPT, prompt, _validate_extraction)
    return [c for c in result["candidates"] if isinstance(c, str) and c.strip()]


CONTRADICTION_SYSTEM_PROMPT = """You are the contradiction-detection module inside a \
personal AI assistant's memory system. You will be given an existing memory and a new \
candidate memory. Decide whether the new memory supersedes (contradicts and replaces) \
the existing one -- e.g. "User lives in Berlin" superseded by "User just moved to Lisbon".

Respond with strict JSON only:
{"supersedes": true|false, "reasoning": "<one sentence>"}

Only mark supersedes=true when the new memory directly conflicts with or replaces the \
old one about the same subject. Do not mark true for merely related or additive facts.
"""


def _validate_supersession(result):
    if not isinstance(result, dict) or "supersedes" not in result:
        raise ValueError(f"Qwen returned malformed supersession result: {result!r}")


def detect_supersession(existing_memory: str, new_memory: str) -> dict:
    prompt = f"Existing memory: {existing_memory}\n\nNew candidate memory: {new_memory}"
    return _chat_json_retrying(CONTRADICTION_SYSTEM_PROMPT, prompt, _validate_supersession)


CONSOLIDATION_SYSTEM_PROMPT = """You are the memory-consolidation module inside a \
personal AI assistant's memory system, run during a "sleep" pass. You will be given a \
cluster of several episodic memories that appear to describe a repeating pattern. \
Summarize them into ONE consolidated semantic memory statement that captures the \
generalizable pattern, written from the user's perspective.

Respond with strict JSON only:
{"consolidated_memory": "<one consolidated statement>", "reasoning": "<one sentence>"}
"""


def _validate_consolidation(result):
    if not isinstance(result, dict) or "consolidated_memory" not in result:
        raise ValueError(f"Qwen returned malformed consolidation result: {result!r}")


def consolidate_cluster(memory_contents: list[str]) -> dict:
    prompt = "\n".join(f"- {m}" for m in memory_contents)
    return _chat_json_retrying(CONSOLIDATION_SYSTEM_PROMPT, prompt, _validate_consolidation)


JUDGE_SYSTEM_PROMPT = """You are an LLM judge for a memory-recall benchmark (this is \
disclosed to end users as an LLM-judged evaluation). You will be given a recall \
question, the currently-correct answer per the ground-truth conversation log, and an \
AI assistant's actual reply. Decide whether the assistant's reply correctly reflects \
the currently-correct answer. Paraphrasing is fine. A reply that gives an outdated or \
stale answer (correct at some earlier point but superseded since) must be marked incorrect. \
A reply that says it doesn't know/isn't sure, when a correct answer was available in \
context, must also be marked incorrect.

Respond with strict JSON only:
{"correct": true|false, "reasoning": "<one sentence>"}
"""


def _validate_judge(result):
    if not isinstance(result, dict) or "correct" not in result:
        raise ValueError(f"Qwen judge returned malformed result: {result!r}")


def judge_recall(question: str, expected_answer: str, agent_reply: str) -> dict:
    prompt = f"Question: {question}\nCurrently-correct answer: {expected_answer}\nAssistant's reply: {agent_reply}"
    return _chat_json_retrying(JUDGE_SYSTEM_PROMPT, prompt, _validate_judge)
