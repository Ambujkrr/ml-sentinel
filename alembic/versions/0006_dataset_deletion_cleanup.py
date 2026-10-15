"""Track retryable CSV cleanup without cascading any monitoring history."""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("pending_dataset_deletions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("dataset_name", sa.String(120), nullable=False),
        sa.Column("file_path", sa.String(80), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("pending_dataset_deletions")
