"""Record optional monitored output column selections."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("monitoring_runs", sa.Column("prediction_column", sa.String(120)))
    op.add_column("monitoring_runs", sa.Column("target_column", sa.String(120)))


def downgrade():
    op.drop_column("monitoring_runs", "target_column")
    op.drop_column("monitoring_runs", "prediction_column")
