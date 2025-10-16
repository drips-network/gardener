"""
Add analysis_artifacts table for S3 artifact metadata

Revision ID: 003
Revises: 002
Create Date: 2025-10-11 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

ARTIFACT_TYPE_ENUM = postgresql.ENUM(
    "GRAPH_PICKLE",
    "RESULTS_JSON",
    name="artifact_type",
    create_type=False,
)


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'artifact_type') THEN
                CREATE TYPE artifact_type AS ENUM ('GRAPH_PICKLE','RESULTS_JSON');
            END IF;
        END$$;
        """
    )

    op.create_table(
        "analysis_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_type", ARTIFACT_TYPE_ENUM, nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("etag", sa.String(length=128), nullable=True),
        sa.Column("checksum_md5", sa.String(length=32), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("version_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "artifact_type", name="uq_artifact_job_type"),
    )
    op.create_index("idx_artifacts_job", "analysis_artifacts", ["job_id"], unique=False)
    op.create_index("idx_artifacts_type", "analysis_artifacts", ["artifact_type"], unique=False)


def downgrade():
    op.drop_index("idx_artifacts_type", table_name="analysis_artifacts")
    op.drop_index("idx_artifacts_job", table_name="analysis_artifacts")
    op.drop_table("analysis_artifacts")
    op.execute("DROP TYPE IF EXISTS artifact_type CASCADE;")
