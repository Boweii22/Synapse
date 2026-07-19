"""All tunable memory-engine constants live here, sourced from env vars.

Nothing in memory/*.py should hardcode a threshold, half-life, or weight —
import it from here instead.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root .env (backend/app/config.py -> backend/app -> backend -> repo root),
# so this resolves the same whether uvicorn runs from backend/ locally or inside
# the Docker container (where docker-compose's env_file already populates
# process env vars and this path simply won't exist -- harmless).
_REPO_ROOT_ENV = Path(__file__).resolve().parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", _REPO_ROOT_ENV), extra="ignore")

    # --- Qwen Cloud (DashScope, OpenAI-compatible mode) ---
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    qwen_chat_model: str = "qwen3.7-plus"
    qwen_embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024

    # --- Database ---
    database_url: str = "postgresql+psycopg://synapse:synapse_dev_password@localhost:5432/synapse"

    # --- Salience decay (section 3.3) ---
    # Half-life expressed in hours; converted to a decay-rate lambda via ln(2)/half_life.
    decay_halflife_hours_semantic: float = 720.0     # ~30 days
    decay_halflife_hours_episodic: float = 72.0      # ~3 days
    decay_halflife_hours_consolidated: float = 720.0  # ~30 days, same as semantic

    # --- Pruning (section 3.5) ---
    prune_salience_floor: float = 0.05

    # --- Retrieval (section 3.6) ---
    retrieval_top_n: int = 25   # candidates pulled by raw cosine similarity
    retrieval_top_k: int = 6    # final count injected into chat context after re-rank
    retrieval_relevance_floor: float = 0.6  # min similarity to count as "about the right topic"

    # --- Consolidation (section 3.4) ---
    consolidation_similarity_threshold: float = 0.86
    consolidation_min_cluster_size: int = 3
    consolidation_trigger_every_n_writes: int = 20
    supersession_similarity_gate: float = 0.55

    # --- App ---
    app_env: str = "development"
    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()
