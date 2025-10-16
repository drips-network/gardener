"""
Drop graph_data_gz column from analysis_jobs

Revision ID: 004
Revises: 003
Create Date: 2025-10-11 00:00:01
"""

from alembic import op
import sqlalchemy as sa


revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("analysis_jobs", "graph_data_gz")


def downgrade():
    op.add_column(
        "analysis_jobs",
        sa.Column("graph_data_gz", sa.LargeBinary(), nullable=True),
    )
