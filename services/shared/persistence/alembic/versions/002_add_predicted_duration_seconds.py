"""
Add predicted_duration_seconds to analysis_jobs

Revision ID: 002
Revises: 001
Create Date: 2025-10-02 00:00:00
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "analysis_jobs",
        sa.Column("predicted_duration_seconds", sa.Numeric(10, 3), nullable=True),
    )
    op.create_index(
        "idx_analysis_jobs_predicted",
        "analysis_jobs",
        ["predicted_duration_seconds"],
        unique=False,
    )


def downgrade():
    op.drop_index("idx_analysis_jobs_predicted", table_name="analysis_jobs")
    op.drop_column("analysis_jobs", "predicted_duration_seconds")
