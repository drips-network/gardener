"""
Pydantic models for API request/response schemas

This module defines all the data models used by the Gardener API service
for request validation, response formatting, and data serialization.
All models are based on Pydantic for automatic validation and documentation
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer, field_validator

from services.shared.models import JobStatus


# Request models
class AnalysisRunRequest(BaseModel):
    """Request body for submitting a new analysis"""

    repo_url: str = Field(..., description="Git repository URL to analyze")
    drip_list_max_length: Optional[int] = Field(
        200, ge=1, le=200, description="Maximum number of dependencies in the final drip list (default: 200, max: 200)"
    )
    force_url_refresh: Optional[bool] = Field(
        False, description="If true, bypasses the URL cache and fetches fresh repository URLs for all dependencies"
    )

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v):
        """
        Validate that URL looks like a git repository

        Performs basic pattern matching to ensure the URL appears to be
        a valid git repository from supported hosting services

        Args:
            v (str): Repository URL string to validate

        Returns:
            Cleaned and validated URL string

        Raises:
            ValueError: If URL is empty or doesn't match git repository patterns
        """
        v = v.strip()
        if not v:
            raise ValueError("Repository URL cannot be empty")
        # Basic check for common git URL patterns
        if not any(
            host in v.lower() for host in ["github.com", "gitlab.com", "bitbucket.org", "git"]
        ) and not v.endswith(".git"):
            raise ValueError("URL does not appear to be a valid git repository")
        return v


# Response models
class AnalysisRunResponse(BaseModel):
    """Response after submitting an analysis request"""

    job_id: UUID = Field(..., description="Unique identifier for the analysis job")
    repository_id: UUID = Field(..., description="Unique identifier for the repository")
    status: JobStatus = Field(..., description="Current status of the job")
    message: str = Field(..., description="Human-readable status message")


class JobStatusResponse(BaseModel):
    """Response for job status queries"""

    job_id: UUID
    repository_id: UUID
    status: JobStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    commit_sha: Optional[str] = None


class DripListItemResponse(BaseModel):
    """Individual Drip List item in results"""

    package_name: str
    package_url: Optional[str]
    split_percentage: Decimal

    @field_serializer("split_percentage")
    def serialize_split_percentage(self, v):
        return float(v)


class AnalysisMetadataResponse(BaseModel):
    """Metadata about the analysis"""

    total_files: Optional[int]
    languages_detected: Optional[List[str]]
    analysis_duration_seconds: Optional[float]


class AnalysisResultsResponse(BaseModel):
    """Complete analysis results"""

    job_id: UUID
    repository_id: UUID
    commit_sha: str
    completed_at: datetime
    results: List[DripListItemResponse]
    metadata: Optional[AnalysisMetadataResponse]

    pass


# Health check models
class HealthResponse(BaseModel):
    """Health check response"""

    status: str = Field(..., description="Service health status")
    timestamp: datetime = Field(..., description="Current server time")
    database: bool = Field(..., description="Database connectivity status")
    redis: bool = Field(..., description="Redis connectivity status")


class VersionResponse(BaseModel):
    """Version information response"""

    api_version: str = Field(..., description="API service version")
    gardener_version: str = Field(..., description="Gardener core library version")
    environment: str = Field(..., description="Current environment")


# Error response model
class ErrorResponse(BaseModel):
    """Standard error response"""

    error: str = Field(..., description="Error type or code")
    message: str = Field(..., description="Human-readable error message")
    detail: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
