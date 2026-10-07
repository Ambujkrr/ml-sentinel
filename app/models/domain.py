from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MonitoredModel(Base):
    __tablename__ = "monitored_models"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    model_version: Mapped[str] = mapped_column(String(80), default="1.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Dataset(Base):
    __tablename__ = "datasets"
    __table_args__ = (CheckConstraint("dataset_type IN ('reference', 'production')", name="ck_dataset_type"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_id: Mapped[str] = mapped_column(ForeignKey("monitored_models.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    dataset_type: Mapped[str] = mapped_column(String(20))
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(80), unique=True)
    row_count: Mapped[int]
    column_count: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DatasetProfile(Base):
    __tablename__ = "dataset_profiles"

    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), primary_key=True)
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MonitoringRun(Base):
    __tablename__ = "monitoring_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_id: Mapped[str] = mapped_column(ForeignKey("monitored_models.id"), index=True)
    reference_dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"))
    production_dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"))
    overall_status: Mapped[str] = mapped_column(String(20))
    drifted_feature_count: Mapped[int]
    total_feature_count: Mapped[int]
    report: Mapped[dict] = mapped_column(JSON)
    prediction_column: Mapped[str | None] = mapped_column(String(120))
    target_column: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    model_id: Mapped[str] = mapped_column(ForeignKey("monitored_models.id"), index=True)
    monitoring_run_id: Mapped[str | None] = mapped_column(ForeignKey("monitoring_runs.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
