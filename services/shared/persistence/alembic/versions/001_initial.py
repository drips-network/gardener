"""
Initial schema baseline

Revision ID: 001
Revises:
Create Date: 2025-09-11 18:41:46.866734
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None

# Single canonical PG enum object; prevent auto-create during table DDL
JOB_STATUS_ENUM = postgresql.ENUM(
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    name="job_status",
    create_type=False,
)


def upgrade() -> None:
    # Ensure the enum type exists exactly once (idempotent)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'job_status') THEN
                CREATE TYPE job_status AS ENUM ('PENDING','RUNNING','COMPLETED','FAILED');
            END IF;
        END$$;
        """
    )

    # repositories
    op.create_table(
        "repositories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_url"),
    )

    # analysis_jobs
    op.create_table(
        "analysis_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repository_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commit_sha", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            JOB_STATUS_ENUM,
            nullable=False,
            server_default=sa.text("'PENDING'::job_status"),
        ),
        sa.Column("graph_data_gz", sa.LargeBinary(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("stale_marked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_analysis_jobs_status",
        "analysis_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_analysis_jobs_repo_created",
        "analysis_jobs",
        ["repository_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_analysis_jobs_repo_status_completed",
        "analysis_jobs",
        ["repository_id", "status", "completed_at"],
        unique=False,
    )
    op.create_index(
        "idx_analysis_jobs_repo_started",
        "analysis_jobs",
        ["repository_id", "started_at"],
        unique=False,
    )

    # drip_list_items
    op.create_table(
        "drip_list_items",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("package_name", sa.Text(), nullable=False),
        sa.Column("package_url", sa.Text(), nullable=True),
        sa.Column("split_percentage", sa.Numeric(precision=7, scale=4), nullable=False),
        sa.Column("repository_url", sa.Text(), nullable=False),
        sa.Column("analyzed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id", "package_name", name="drip_list_items_pkey"),
    )
    op.create_index(
        "idx_drip_items_repo",
        "drip_list_items",
        ["repository_url"],
        unique=False,
    )
    op.create_index(
        "idx_drip_items_analyzed",
        "drip_list_items",
        ["analyzed_at"],
        unique=False,
    )

    # analysis_metadata
    op.create_table(
        "analysis_metadata",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_files", sa.Integer(), nullable=True),
        sa.Column("languages_detected", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "analysis_duration_seconds",
            sa.Numeric(precision=10, scale=2),
            nullable=True,
        ),
        sa.Column("graph_size_bytes", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["analysis_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )

    # package_url_cache
    op.create_table(
        "package_url_cache",
        sa.Column("package_name", sa.Text(), nullable=False),
        sa.Column("ecosystem", sa.String(length=20), nullable=False),
        sa.Column("resolved_url", sa.Text(), nullable=False),
        sa.Column(
            "resolved_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("package_name", "ecosystem"),
    )


def downgrade() -> None:
    # Drop in dependency-safe reverse order
    op.drop_table("package_url_cache")
    op.drop_table("analysis_metadata")
    op.drop_index("idx_drip_items_analyzed", table_name="drip_list_items")
    op.drop_index("idx_drip_items_repo", table_name="drip_list_items")
    op.drop_table("drip_list_items")
    op.drop_index("idx_analysis_jobs_repo_started", table_name="analysis_jobs")
    op.drop_index("idx_analysis_jobs_repo_status_completed", table_name="analysis_jobs")
    op.drop_index("idx_analysis_jobs_repo_created", table_name="analysis_jobs")
    op.drop_index("idx_analysis_jobs_status", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
    op.drop_table("repositories")

    # Finally, remove the enum type (only after dependents are gone)
    op.execute("DROP TYPE IF EXISTS job_status CASCADE;")
