from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas.domain import Timestamped


class DriftRunCreate(BaseModel):
    reference_dataset_id: UUID
    production_dataset_id: UUID
    prediction_column: str | None = None
    target_column: str | None = None


class MonitoringRunSummary(Timestamped):
    model_config = ConfigDict(from_attributes=True)
    id: str
    model_id: str
    reference_dataset_id: str
    production_dataset_id: str
    overall_status: str
    drifted_feature_count: int
    total_feature_count: int
    prediction_column: str | None = None
    target_column: str | None = None


class MonitoringRunRead(MonitoringRunSummary):
    report: dict
