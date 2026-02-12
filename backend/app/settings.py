from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Load the single canonical .env (repo root) into the process environment
# before Settings is instantiated, so all components (API, worker, scripts)
# see the same values regardless of current working directory.
try:
    from dotenv import load_dotenv

    _repo_root = Path(__file__).resolve().parent.parent.parent
    load_dotenv(_repo_root / ".env")
except Exception:
    # If python-dotenv is not installed or the file is missing, fall back to OS env vars.
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",  # ignore ingest-client vars (API_BASE_URL, WATCH_DIR, POLL_SECONDS) in shared .env
    )

    database_url: str = "sqlite:///./dev.db"

    storage_backend: str = "local"  # gcs|local
    gcs_bucket: str = ""
    gcs_prefix: str = "investing-agent"
    local_storage_dir: str = ".local_storage"

    gcp_project: str = ""
    gcp_location: str = "us-central1"
    vertex_gemini_model: str = "gemini-2.0-flash"
    vertex_embed_model: str = "gemini-embedding-001"

    enable_vertex: bool = False
    enable_auth: bool = False

    # Embeddings: vertex (GCP) or openai (no Vertex required). "auto" = vertex if enabled else openai if LLM_API_KEY set.
    embedding_provider: str = "auto"  # auto | vertex | openai | none
    embedding_model: str = "text-embedding-3-small"  # for OpenAI; Vertex uses vertex_embed_model

    # Simple LLM API (MVP: use API key instead of full Vertex)
    # Set LLM_API_KEY to use real extraction; otherwise heuristic is used.
    llm_provider: str = "openai"  # openai | gemini | openai_compatible
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"  # or gemini-1.5-flash, deepseek-chat, etc.
    llm_base_url: str = ""  # optional; e.g. https://api.deepseek.com for DeepSeek
    # Request timeout in seconds for LLM API calls (Gemini can be slow on long documents).
    llm_timeout_seconds: int = 180
    # Optional delay in seconds after each LLM/Vertex extraction call (e.g. 1.0 to stay under OpenAI RPM with 1000+ docs).
    llm_delay_after_request_seconds: float = 0.0
    # Max concurrent LLM requests when processing ingested documents (worker parallelism).
    # Higher = faster throughput but more API pressure. Default 3 is safe for most providers.
    llm_max_concurrent_requests: int = 3
    # Force heuristic extraction (no LLM/Vertex). When true, ignores LLM_API_KEY and Vertex.
    use_heuristic_extraction: bool = False

    # Theme deduplication: similarity-based resolution when exact/alias match fails.
    theme_similarity_use_embedding: bool = True  # use embedding similarity when embedding_provider is available
    theme_similarity_use_text: bool = True  # use token (Dice) text similarity; no API required
    theme_similarity_embedding_threshold: float = 0.92  # min cosine similarity to merge (0–1)
    theme_similarity_text_threshold: float = 0.7  # min Dice coefficient for token similarity (0–1)
    # Theme merge suggestion (admin): higher = stricter (fewer, more precise merges).
    theme_merge_suggestion_embedding_threshold: float = 0.92  # min cosine sim for label embedding
    theme_merge_use_llm_suggest: bool = False  # when True, also use LLM to suggest merge groups
    # Use theme content (narratives + quotes) for embedding similarity, not just the label.
    theme_merge_use_content_embedding: bool = False
    theme_merge_content_embedding_threshold: float = 0.90  # min cosine sim of content embeddings (stricter)
    # When True, a pair is only merged if BOTH label and content similarity pass (avoids e.g. merging "Pop Mart IP" with "China IP retailers").
    theme_merge_require_both_embeddings: bool = False
    theme_merge_content_weight: float = 0.5  # weight for content when combining with label sim (0=label only, 1=content only)
    theme_merge_max_narratives_per_theme: int = 5
    theme_merge_max_quotes_per_theme: int = 8
    theme_merge_max_quote_chars: int = 250
    # When user merges themes, store source label+embedding and use during extraction (resolve new labels to merged-into theme).
    theme_merge_reinforcement_enabled: bool = True
    theme_merge_reinforcement_threshold: float = 0.8  # min cosine sim to resolve label to a reinforcement target

    # Optional: write backend logs to this file (worker + API). Leave empty for stdout only.
    log_file: str = ""

    # Ingest queue cap: reject new /ingest and /ingest-file when queued+processing jobs >= this (0 = no cap).
    max_queued_ingest_jobs: int = 0

    # Temporary pause: when true, reject all new ingest requests (use while developing on existing data).
    pause_ingest: bool = False


settings = Settings()

