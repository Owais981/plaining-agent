"""Central configuration loaded from environment variables. No secrets are
hardcoded anywhere in this codebase -- everything flows through here."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- data layer ---
    database_url: str = "sqlite:///./dev.db"
    redis_url: str = "redis://localhost:6379/0"
    celery_enabled: bool = False  # set true when a Celery worker is actually running (see docker-compose.yml)

    # --- LLM ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # --- routing ---
    routing_provider: str = "haversine"  # haversine | osrm | google
    osrm_base_url: str = ""
    google_maps_api_key: str = ""
    mapbox_token: str = ""
    road_winding_factor: float = 1.3
    average_speed_kmh: float = 55.0
    route_cache_ttl_hours: int = 168

    # --- auth ---
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12

    # --- solver ---
    solver_max_seconds: int = 120
    solver_workers: int = 8
    solver_relative_gap: float = 0.02
    solver_seed: int = 42

    # --- misc ---
    environment: str = "development"
    cors_origins: str = "http://localhost:5173"
    max_request_body_bytes: int = 2_000_000
    rate_limit_per_minute: int = 120


@lru_cache
def get_settings() -> Settings:
    return Settings()
