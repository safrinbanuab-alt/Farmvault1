"""
Application configuration.

Loads and validates all runtime configuration from environment variables
(or a `.env` file) using pydantic-settings. Import the module-level
`settings` singleton anywhere configuration values are needed.
"""

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings, sourced from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = Field(default="FarmVault")
    app_env: str = Field(default="development")  # development | staging | production
    debug: bool = Field(default=True)
    secret_key: str = Field(default="change-this-to-a-long-random-secret-key")
    api_v1_prefix: str = Field(default="/api")

    # --- Server ---
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    frontend_url: str = Field(default="http://localhost:5173")
    allowed_origins: str = Field(default="http://localhost:5173,http://localhost:3000")

    # --- Database ---
    
    database_url: str = Field(
    default="sqlite+aiosqlite:///./farmvault.db"
)
    # --- WebSocket ---
    ws_heartbeat_interval: int = Field(default=30)

    # --- IoT Simulator ---
    sensor_update_interval_seconds: int = Field(default=5)
    market_feed_update_interval_seconds: int = Field(default=30)
    anomaly_injection_enabled: bool = Field(default=True)
    anomaly_injection_probability: float = Field(default=0.05)

    # --- AI Models ---
    decay_model_path: str = Field(default="app/data/decay_curves.csv")
    mandi_price_data_path: str = Field(default="app/data/mandi_prices.csv")
    price_forecast_horizon_days: int = Field(default=7)

    # --- Logging ---
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/farmvault.log")

    # --- Auth ---
    jwt_secret_key: str = Field(default="change-this-jwt-secret")
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=60)

    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, value: str) -> str:
        allowed = {"development", "staging", "production"}
        if value not in allowed:
            raise ValueError(f"app_env must be one of {allowed}, got '{value}'")
        return value

    @field_validator("anomaly_injection_probability")
    @classmethod
    def validate_probability(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("anomaly_injection_probability must be between 0 and 1")
        return value

    @property
    def cors_origins(self) -> List[str]:
        """Parsed list of allowed CORS origins."""
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (loaded once per process)."""
    return Settings()


settings = get_settings()