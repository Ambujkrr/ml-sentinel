"""Register monitored models and dataset metadata."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("monitored_models",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("model_version", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_id", sa.String(36), sa.ForeignKey("monitored_models.id"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("dataset_type", sa.String(20), nullable=False),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(80), nullable=False, unique=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("column_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("dataset_type IN ('reference', 'production')", name="ck_dataset_type"))
    op.create_index("ix_datasets_model_id", "datasets", ["model_id"])


def downgrade():
    op.drop_table("datasets")
    op.drop_table("monitored_models")
