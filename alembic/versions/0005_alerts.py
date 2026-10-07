"""Persist alerts generated from monitoring run findings."""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("alerts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("monitored_models.id"), nullable=False),
        sa.Column("monitoring_run_id", sa.String(36), sa.ForeignKey("monitoring_runs.id")),
        sa.Column("alert_type", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)))
    op.create_index("ix_alerts_model_id", "alerts", ["model_id"])
    op.create_index("ix_alerts_monitoring_run_id", "alerts", ["monitoring_run_id"])


def downgrade():
    op.drop_table("alerts")
