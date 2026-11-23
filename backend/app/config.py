"""Backend configuration (Person 1).

Values come from environment variables or a `.env` file in the project root.
See `.env.example` for the full list.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Agent Monitoring System"
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data' / 'agent_monitoring.db').as_posix()}"
    # Comma-separated list of origins allowed to call the API from a browser.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Also write each trace / review as JSON under data/executions and data/evaluation.
    persist_json_files: bool = True
    data_dir: Path = PROJECT_ROOT / "data"
    # Passed to the reviewer's latency check.
    latency_budget_ms: float = 5000.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
