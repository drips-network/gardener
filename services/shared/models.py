"""
SQLAlchemy ORM models for the Gardener microservice
"""

import enum
from uuid import uuid4

from sqlalchemy import (
    ARRAY,
    TIMESTAMP,
    BigInteger,
    Column,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class JobStatus(enum.Enum):
    """
    Status enumeration for analysis jobs

    Tracks the lifecycle state of dependency analysis jobs from creation
    through completion or failure
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ArtifactType(enum.Enum):
    """
    Artifact types persisted in object storage

    Enumerates the serialized artifact categories saved for each analysis job
    """

    GRAPH_PICKLE = "GRAPH_PICKLE"
    RESULTS_JSON = "RESULTS_JSON"


class Repository(Base):
    """
    Repository table model for storing analyzed Git repositories

    Maintains canonical repository information and serves as the parent
    entity for analysis jobs. Each repository can have multiple analysis
    jobs representing different commits or analysis runs
    """

    __tablename__ = "repositories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    url = Column(Text, nullable=False)
    canonical_url = Column(Text, nullable=False, unique=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    analysis_jobs = relationship("AnalysisJob", back_populates="repository")


class AnalysisJob(Base):
    """
    Analysis job table model for tracking dependency analysis executions

    Represents individual analysis runs on repository commits, storing
    the complete analysis state, results, and metadata. Each job is
    associated with a specific repository and git commit
    """

    __tablename__ = "analysis_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    repository_id = Column(UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False)
    commit_sha = Column(String(64), nullable=False)
    status = Column(Enum(JobStatus), nullable=False, default=JobStatus.PENDING)
    # Optional runtime prediction for client progress bars
    predicted_duration_seconds = Column(Numeric(10, 3), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    completed_at = Column(TIMESTAMP(timezone=True), nullable=True)
    stale_marked_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Relationships
    repository = relationship("Repository", back_populates="analysis_jobs")
    drip_list_items = relationship("DripListItem", back_populates="job", cascade="all, delete-orphan")
    analysis_metadata = relationship(
        "AnalysisMetadata", back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    artifacts = relationship("AnalysisArtifact", back_populates="job", cascade="all, delete-orphan")

    # Constraints - Removed unique constraint on (repository_id, commit_sha)
    __table_args__ = (
        Index("idx_analysis_jobs_status", "status"),
        Index("idx_analysis_jobs_repo_created", "repository_id", "created_at"),
        Index("idx_analysis_jobs_predicted", "predicted_duration_seconds"),
    )


class DripListItem(Base):
    """
    Drip list items table model for funding distribution results

    Stores the final funding allocation percentage (per Pagerank/Katz-derived
    dependency importance scores) for each analyzed package
    """

    __tablename__ = "drip_list_items"

    job_id = Column(
        UUID(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, primary_key=True
    )
    package_name = Column(Text, nullable=False, primary_key=True)
    package_url = Column(Text, nullable=True)
    split_percentage = Column(Numeric(7, 4), nullable=False)  # e.g., 12.3456
    repository_url = Column(Text, nullable=False)
    analyzed_at = Column(TIMESTAMP(timezone=True), nullable=False)

    # Relationships
    job = relationship("AnalysisJob", back_populates="drip_list_items")

    # Constraints and indexes
    __table_args__ = (
        Index("idx_drip_items_repo", "repository_url"),
        Index("idx_drip_items_analyzed", "analyzed_at"),
    )


class AnalysisMetadata(Base):
    """
    Analysis metadata table model for storing analysis execution details

    Captures performance metrics and characteristics of the analysis run,
    including file counts, detected languages, execution time, and resource usage.
    Used for monitoring and debugging
    """

    __tablename__ = "analysis_metadata"

    job_id = Column(UUID(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), primary_key=True)
    total_files = Column(Integer, nullable=True)
    languages_detected = Column(ARRAY(Text), nullable=True)
    analysis_duration_seconds = Column(Numeric(10, 2), nullable=True)
    graph_size_bytes = Column(BigInteger, nullable=True)

    # Relationships
    job = relationship("AnalysisJob", back_populates="analysis_metadata")


class PackageUrlCache(Base):
    """
    Package URL cache table model for optimizing repository URL resolution

    To improve performance and mitigate rate limiting risks, caches the mappings
    between package names (across different ecosystems) and their resolved repository
    URLs to avoid unnecessary API calls across dependency analysis jobs
    """

    __tablename__ = "package_url_cache"

    package_name = Column(Text, primary_key=True)
    ecosystem = Column(String(20), primary_key=True)
    resolved_url = Column(Text, nullable=False)
    resolved_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())


class AnalysisArtifact(Base):
    """
    Pointer and metadata for S3-stored analysis artifacts

    Stores object storage coordinates and checksums for serialized analysis outputs
    """

    __tablename__ = "analysis_artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False)
    artifact_type = Column(Enum(ArtifactType), nullable=False)
    bucket = Column(Text, nullable=False)
    object_key = Column(Text, nullable=False)
    content_type = Column(String(100), nullable=False)
    size_bytes = Column(BigInteger, nullable=False)
    etag = Column(String(128), nullable=True)
    checksum_md5 = Column(String(32), nullable=True)
    checksum_sha256 = Column(String(64), nullable=True)
    version_id = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())

    job = relationship("AnalysisJob", back_populates="artifacts")

    __table_args__ = (
        UniqueConstraint("job_id", "artifact_type", name="uq_artifact_job_type"),
        Index("idx_artifacts_job", "job_id"),
        Index("idx_artifacts_type", "artifact_type"),
    )
