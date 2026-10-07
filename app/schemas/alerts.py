from datetime import datetime
from typing import Literal

from pydantic import ConfigDict

from app.schemas.domain import Timestamped


class AlertRead(Timestamped):
    model_config = ConfigDict(from_attributes=True)
    id: str
    model_id: str
    monitoring_run_id: str | None
    alert_type: str
    severity: Literal["info", "warning", "critical"]
    message: str
    resolved_at: datetime | None
