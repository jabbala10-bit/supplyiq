"""Centralized configuration for SupplyIQ using Pydantic Settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.domain.constants import (
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_RATE_LIMIT_PER_MINUTE,
    DEFAULT_SQLITE_PATH,
    EXACT_SOLVE_TIME_LIMIT_SECONDS,
    NETWORK_EXACT_MAX_VARIABLES,
    REPLENISHMENT_EXACT_MAX_SKU_LOCATIONS,
    ROUTING_EXACT_MAX_STOPS,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # App
    app_name: str = "SupplyIQ"
    environment: str = Field(default="development")
    debug: bool = False
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Solver budgets (ADR-002)
    exact_solve_time_limit_seconds: float = EXACT_SOLVE_TIME_LIMIT_SECONDS
    routing_exact_max_stops: int = ROUTING_EXACT_MAX_STOPS
    network_exact_max_variables: int = NETWORK_EXACT_MAX_VARIABLES
    replenishment_exact_max_sku_locations: int = REPLENISHMENT_EXACT_MAX_SKU_LOCATIONS

    # Copilot (Ollama-served LLM)
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = DEFAULT_LLM_MODEL
    llm_temperature: float = DEFAULT_LLM_TEMPERATURE

    # Storage
    sqlite_path: str = DEFAULT_SQLITE_PATH

    # Security
    api_auth_token: str = Field(default="", repr=False)
    rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE
    cors_allowed_origins: list[str] = Field(default_factory=lambda: ["http://localhost:7860"])

    # Observability
    log_level: str = "INFO"
    log_format: str = "json"
    metrics_enabled: bool = True

    @field_validator("environment")
    @classmethod
    def _validate_environment(cls, v: str) -> str:
        allowed = {"development", "staging", "production"}
        if v not in allowed:
            raise ValueError(f"environment must be one of {allowed}, got '{v}'")
        return v

    def validate_production_secrets(self) -> None:
        from src.domain.exceptions import ConfigurationError

        if self.environment != "production":
            return
        if not self.api_auth_token:
            raise ConfigurationError("Missing required production secret: API_AUTH_TOKEN")

    def ensure_directories(self) -> None:
        Path(self.sqlite_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
