from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # env_file is optional: present in local dev, absent in ECS containers
        # (ECS injects secrets directly as environment variables).
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Elasticsearch ──────────────────────────────────────────
    # Required — no defaults; missing env var raises ValidationError at startup.
    ES_HOST: str
    ES_PORT: int
    ES_SCHEME: str  # "http" (dev) or "https" (production)
    ES_INDEX: str
    ES_USER: str  # basic-auth username (required by ES 8.x)
    ES_PASSWORD: str  # inject via ECS Task Definition secrets

    # Optional topology — safe defaults for single-node dev; override for production.
    ES_NUM_SHARDS: int = 1
    ES_NUM_REPLICAS: int = 0

    # ── Embedding ──────────────────────────────────────────────
    # Required — dims must match the deployed model; wrong value breaks index mapping.
    EMBEDDING_MODEL: str
    EMBEDDING_DIMS: int

    # Optional — override to "cuda" if GPU is available.
    EMBEDDING_DEVICE: str = "cpu"

    # ── Kafka (optional feature) ────────────────────────────────
    KAFKA_ENABLED: bool = False
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_TOPIC_LISTING: str = "listing.events"

    # Async write mode: when True, write commands go to Kafka instead of ES directly.
    # The agora-worker container consumes and processes them.
    # Set False (default) for local dev without Kafka running.
    KAFKA_WRITE_MODE: bool = False
    KAFKA_TOPIC_COMMANDS: str = "listing.commands"
    KAFKA_TOPIC_DLQ: str = "listing.commands.dlq"
    KAFKA_CONSUMER_GROUP: str = "agora-workers"
    KAFKA_MAX_POLL_RECORDS: int = 10

    # ── Embedding ──────────────────────────────────────────────
    # Tuning knob for GPU/CPU tradeoff — 32 is safe for CPU-only environments.
    EMBED_BATCH_SIZE: int = 32

    # ── Matching ───────────────────────────────────────────────
    # Safe defaults; override via env var for production tuning.
    MATCH_TOP_K: int = 10
    MATCH_NUM_CANDIDATES: int = 50
    MATCH_MIN_COSINE_SCORE: float = 0.65
    MATCH_BONUS_SAME_CATEGORY: float = 0.07
    MATCH_BONUS_SAME_CITY: float = 0.03

    @property
    def es_url(self) -> str:
        return f"{self.ES_SCHEME}://{self.ES_HOST}:{self.ES_PORT}"


# Required fields have no defaults — pydantic-settings reads them from environment
# variables at runtime. mypy cannot see this and reports false-positive call-arg errors.
settings = Settings()  # type: ignore[call-arg]
