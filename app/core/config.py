from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "ML Sentinel"
    APP_ENV: str = "development"
    DATABASE_URL: str = "postgresql+psycopg://localhost/ml_sentinel"
    UPLOAD_DIR: Path = Path("data/uploads")
    MAX_UPLOAD_BYTES: int = Field(default=10_000_000, ge=1024)
    MAX_DATASET_ROWS: int = Field(default=100_000, ge=1)
    MAX_DATASET_COLUMNS: int = Field(default=200, ge=1)
    DRIFT_ALPHA: float = Field(default=0.05, gt=0, lt=1)
    PSI_WARNING: float = Field(default=0.10, gt=0)
    PSI_CRITICAL: float = Field(default=0.25, gt=0)
    PSI_BINS: int = Field(default=10, ge=2, le=20)
    MIN_DRIFT_SAMPLES: int = Field(default=10, ge=2)
    MISSING_RATE_CHANGE: float = Field(default=0.05, gt=0, le=1)
    PERFORMANCE_F1_DROP: float = Field(default=0.10, gt=0, le=1)

    @field_validator("DATABASE_URL")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        # Render supplies a plain postgres URL; explicitly select Psycopg 3.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return value.replace(prefix, "postgresql+psycopg://", 1)
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
