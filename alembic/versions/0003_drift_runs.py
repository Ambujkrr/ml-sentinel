"""Record distribution comparisons and their thresholds."""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("monitoring_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("monitored_models.id"), nullable=False),
        sa.Column("reference_dataset_id", sa.String(36), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("production_dataset_id", sa.String(36), sa.ForeignKey("datasets.id"), nullable=False),
        sa.Column("overall_status", sa.String(20), nullable=False),
        sa.Column("drifted_feature_count", sa.Integer(), nullable=False),
        sa.Column("total_feature_count", sa.Integer(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_monitoring_runs_model_id", "monitoring_runs", ["model_id"])


def downgrade():
    op.drop_table("monitoring_runs")
