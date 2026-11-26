
"""Backend configuration (Person 1)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Agent Monitoring System"

    database_url: str = (
        f"sqlite:///{(PROJECT_ROOT / 'data' / 'agent_monitoring.db').as_posix()}"
    )

    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173"
    )

    persist_json_files: bool = True
    data_dir: Path = PROJECT_ROOT / "data"

    latency_budget_ms: float = 5000.0

    # Agent execution configuration
    agent_mode: Literal["mock_rule_based", "ollama"] = "mock_rule_based"

    # Local Ollama configuration
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_timeout_seconds: float = 90.0

    # Independent AI specialist reviewers
    specialist_reviews_enabled: bool = False
    ollama_specialist_timeout_seconds: float = 45.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
