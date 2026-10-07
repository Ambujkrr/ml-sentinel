"""Persist profiles and data quality with each immutable upload."""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("dataset_profiles",
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id"), primary_key=True),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("dataset_profiles")
