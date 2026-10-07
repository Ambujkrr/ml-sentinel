from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Timestamped(BaseModel):
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class ModelCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    model_version: str = Field(default="1.0", min_length=1, max_length=80)


class ModelRead(ModelCreate, Timestamped):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime


class DatasetRead(Timestamped):
    model_config = ConfigDict(from_attributes=True)
    id: str
    model_id: str
    name: str
    dataset_type: Literal["reference", "production"]
    file_name: str
    row_count: int
    column_count: int
    created_at: datetime
