"""Central configuration, loaded from environment / .env.

Everything tunable (DB connectivity, sandbox limits, loop budget, LLM mode and
per-agent routing) is funnelled through `Settings` so the rest of the code never
reads os.environ directly.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    # --- LLM / LiteLLM ---
    litellm_base_url: str = Field("http://localhost:4000", alias="LITELLM_BASE_URL")
    litellm_key_planner: str = Field("sk-planner", alias="LITELLM_KEY_PLANNER")
    litellm_key_writer: str = Field("sk-writer", alias="LITELLM_KEY_WRITER")
    litellm_key_verifier: str = Field("sk-verifier", alias="LITELLM_KEY_VERIFIER")
    litellm_key_explainer: str = Field("sk-explainer", alias="LITELLM_KEY_EXPLAINER")
    llm_mode: str = Field("replay", alias="LLM_MODE")  # live | record | replay

    # --- Postgres ---
    pg_host: str = Field("localhost", alias="PG_HOST")
    pg_port: int = Field(5432, alias="PG_PORT")
    pg_db: str = Field("nl2sql", alias="PG_DB")
    pg_app_user: str = Field("nl2sql_app", alias="PG_APP_USER")
    pg_app_password: str = Field("nl2sql_app_pw", alias="PG_APP_PASSWORD")
    pg_ro_user: str = Field("analyst_ro", alias="PG_RO_USER")
    pg_ro_password: str = Field("analyst_ro_pw", alias="PG_RO_PASSWORD")

    # --- Observability ---
    otlp_endpoint: str = Field("http://localhost:6006", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    otel_service_name: str = Field("nl2sql-agent-harness", alias="OTEL_SERVICE_NAME")

    # --- Embeddings ---
    embedding_model: str = Field("BAAI/bge-small-en-v1.5", alias="EMBEDDING_MODEL")

    # --- Executor sandbox limits ---
    sql_statement_timeout_ms: int = Field(5000, alias="SQL_STATEMENT_TIMEOUT_MS")
    sql_max_rows: int = Field(1000, alias="SQL_MAX_ROWS")
    sql_max_explain_cost: float = Field(5e7, alias="SQL_MAX_EXPLAIN_COST")

    # --- Agent loop budget ---
    max_retries: int = Field(2, alias="MAX_RETRIES")
    max_wallclock_seconds: int = Field(30, alias="MAX_WALLCLOCK_SECONDS")

    def app_dsn(self) -> str:
        """Read/write DSN for the app role (owns `app` schema, can read `shop`)."""
        return (
            f"postgresql://{self.pg_app_user}:{self.pg_app_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    def readonly_dsn(self) -> str:
        """Least-privilege DSN used by the SQL executor sandbox."""
        return (
            f"postgresql://{self.pg_ro_user}:{self.pg_ro_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
