"""
Main FastAPI application
"""

import os
import sys
from decimal import Decimal
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

import redis
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session, joinedload
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as StarletteJSONResponse
from gardener.common.subprocess import SecureSubprocess
from gardener.common.utils import get_logger
from services.api.app.schemas import (
    AnalysisResultsResponse,
    AnalysisRunRequest,
    AnalysisRunResponse,
    DripListItemResponse,
    ErrorResponse,
    HealthResponse,
    JobStatusResponse,
    VersionResponse,
)
from services.api.app.security import verify_auth_token
from services.shared.celery_client import celery_client
from services.shared.config import settings
from services.shared.database import check_db_connection, get_db
from services.shared.models import AnalysisJob, JobStatus, Repository
from services.shared.utils import canonicalize_repo_url
from services.shared.estimator import estimate_duration_seconds

try:
    from importlib.metadata import version as _pkg_version  # Python 3.9+
except Exception:  # pragma: no cover
    _pkg_version = None

# Initialize logger
logger = get_logger("api", verbose=settings.DEBUG)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_request_size):
        super().__init__(app)
        self.max_request_size = max_request_size

    async def dispatch(self, request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_request_size:
                    return StarletteJSONResponse(status_code=413, content={"detail": "Request too large"})
            except ValueError:
                # Malformed content-length header
                return StarletteJSONResponse(status_code=400, content={"detail": "Invalid content-length header"})
        elif request.method in ("POST", "PUT", "PATCH"):
            # Missing content-length on body-carrying methods
            # Note: For streaming bodies, consider server-level limits
            logger.warning("Request without content-length header")
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context handling startup/shutdown without on_event"""
    logger.info("Starting Gardener API service...")
    try:
        logger.info(
            "Service version: %s | env=%s | commit=%s",
            settings.SERVICE_VERSION,
            settings.ENVIRONMENT,
            os.environ.get("GARDENER_GIT_COMMIT", "unknown"),
        )
    except Exception:
        pass

    # Optional DB migrations
    try:
        if os.environ.get("RUN_DB_MIGRATIONS", "1") in ("1", "true", "True"):
            logger.info("Applying database migrations...")
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
            services_dir = os.path.join(project_root, "services")

            python_executable = sys.executable or ""
            python_bin_dirs = []
            if python_executable:
                try:
                    python_dir = os.path.dirname(os.path.abspath(python_executable))
                    if os.path.isdir(python_dir):
                        python_bin_dirs.append(python_dir)
                except Exception:
                    python_bin_dirs = []
            else:
                python_executable = "python3"

            migration_env_keys = [
                "DATABASE_URL",
                "PGHOST",
                "PGPORT",
                "PGUSER",
                "PGPASSWORD",
                "PGDATABASE",
                "PGSSLMODE",
                "ENVIRONMENT",
                "DEBUG",
                "PYTHONPATH",
                "HMAC_SHARED_SECRET",
                "HMAC_HASH_NAME",
                "TOKEN_EXPIRY_SECONDS",
            ]
            migration_env = {}
            for key in migration_env_keys:
                value = os.environ.get(key)
                if isinstance(value, str) and value:
                    migration_env[key] = value

            if "DATABASE_URL" not in migration_env and settings.database.DATABASE_URL:
                migration_env["DATABASE_URL"] = str(settings.database.DATABASE_URL)

            pythonpath_entries = []
            existing_pythonpath = migration_env.get("PYTHONPATH")
            if existing_pythonpath:
                pythonpath_entries.extend(
                    entry for entry in existing_pythonpath.split(os.pathsep) if entry
                )
            if project_root not in pythonpath_entries:
                pythonpath_entries.append(project_root)
            migration_env["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)

            secure_proc = SecureSubprocess(
                allowed_root=project_root,
                timeout=60,
                allowed_env_vars=migration_env_keys,
                extra_path_dirs=python_bin_dirs,
            )
            secure_proc.run([python_executable, "-m", "alembic", "upgrade", "head"],
                            cwd=services_dir, env=migration_env, check=True)
            logger.info("Database migrations applied")
    except Exception as e:
        logger.error(f"Failed to apply migrations on startup: {e}")

    # Initialize Redis
    app.state.redis_client = None
    try:
        app.state.redis_client = redis.from_url(settings.redis.REDIS_URL)
        app.state.redis_client.ping()
        logger.info("Redis connection established")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")

    # Check database connection
    if not check_db_connection():
        logger.error("Database connection failed during startup")

    # Test Celery client connection
    try:
        celery_client.control.ping(timeout=1.0)
        logger.info("Celery client connected successfully")
    except Exception as e:
        logger.warning(f"Celery client connection test failed: {e}")

    yield

    # Shutdown
    logger.info("Shutting down Gardener API service...")
    try:
        rc = getattr(app.state, "redis_client", None)
        if rc:
            rc.close()
    except Exception:
        pass
    logger.info("Gardener API service shut down")


# Create FastAPI app with lifespan handler
app = FastAPI(
    title="Gardener Dependency Analysis API",
    description="Microservice for analyzing code repository dependencies",
    version=settings.SERVICE_VERSION,
    docs_url="/docs" if settings.DEBUG else None,  # Disable docs in production
    redoc_url="/redoc" if settings.DEBUG else None,
    lifespan=lifespan,
)

# Configure CORS (adjust origins for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else ["https://drips.network"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security middleware
app.add_middleware(RequestSizeLimitMiddleware, max_request_size=settings.api.MAX_REQUEST_SIZE)

if settings.ENVIRONMENT == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.api.ALLOWED_HOSTS)

# Configure rate limiting (Redis-backed for multi-instance safety)
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis.REDIS_URL)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# Validation error handler to avoid leaking request details
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    if settings.ENVIRONMENT == "production":
        return JSONResponse(status_code=422, content={"detail": "Unprocessable entity"})
    # In development, show full validation errors
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


def get_git_commit_hash() -> str:
    """Get git commit from environment"""
    return os.environ.get("GARDENER_GIT_COMMIT", "unknown")


# Health check endpoints
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Check service health status"""
    # Check database
    db_healthy = check_db_connection()

    # Check Redis
    redis_healthy = False
    try:
        rc = getattr(app.state, "redis_client", None)
        if rc:
            rc.ping()
            redis_healthy = True
    except Exception:
        pass

    return HealthResponse(
        status="healthy" if (db_healthy and redis_healthy) else "degraded",
        timestamp=datetime.now(timezone.utc),
        database=db_healthy,
        redis=redis_healthy,
    )


@app.get("/version", response_model=VersionResponse, tags=["Health"])
async def version_info():
    """Get API version information"""
    return VersionResponse(
        api_version=settings.SERVICE_VERSION,
        gardener_version=settings.SERVICE_VERSION,
        environment=settings.ENVIRONMENT,
    )


# Main API endpoints
@app.post(
    "/api/v1/analyses/run",
    response_model=AnalysisRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Analysis"],
    dependencies=[Depends(verify_auth_token)],
)
@limiter.limit(f"{settings.api.RATE_LIMIT_PER_MINUTE}/minute")
async def run_analysis(analysis_request: AnalysisRunRequest, request: Request, db: Session = Depends(get_db)):
    """
    Submit a repository for dependency analysis

    This endpoint queues an analysis job and returns immediately

    Use the returned job_id to check status and retrieve results
    """
    try:
        # Canonicalize the URL
        canonical_url = canonicalize_repo_url(analysis_request.repo_url)

        # Find or create repository
        repository = db.query(Repository).filter_by(canonical_url=canonical_url).first()
        if not repository:
            repository = Repository(url=analysis_request.repo_url, canonical_url=canonical_url)
            db.add(repository)
            db.commit()
            db.refresh(repository)
            logger.info(f"Created new repository: {repository.id}")

        # Only check for currently running jobs to prevent concurrent execution
        existing_running_job = (
            db.query(AnalysisJob)
            .filter(AnalysisJob.repository_id == repository.id, AnalysisJob.status == JobStatus.RUNNING)
            .first()
        )

        if existing_running_job:
            # Check if the running job is stale; if so, mark it FAILED and start a new job
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.api.RUNNING_JOB_STALE_SECONDS)
                # Only consider jobs that actually started (started_at set by worker)
                # Fallback to commit_sha check for older records
                started = existing_running_job.started_at
                actually_started = bool(started) or (
                    existing_running_job.commit_sha and existing_running_job.commit_sha != "pending"
                )
                reference_time = started or existing_running_job.created_at
                if actually_started and reference_time and reference_time < cutoff:
                    existing_running_job.status = JobStatus.FAILED
                    existing_running_job.error_message = (
                        f"Previous job exceeded allowed runtime "
                        f"({settings.api.RUNNING_JOB_STALE_SECONDS}s) and was marked stale by API"
                    )
                    existing_running_job.stale_marked_at = datetime.now(timezone.utc)
                    existing_running_job.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    logger.info(f"Marked stale RUNNING job {existing_running_job.id} as FAILED")
                else:
                    logger.info(f"Returning existing running job: {existing_running_job.id}")
                    return AnalysisRunResponse(
                        job_id=existing_running_job.id,
                        repository_id=repository.id,
                        status=existing_running_job.status,
                        message="Analysis already in progress",
                    )
            except Exception as e:
                logger.warning(f"Failed stale check on existing RUNNING job {existing_running_job.id}: {e}")
                return AnalysisRunResponse(
                    job_id=existing_running_job.id,
                    repository_id=repository.id,
                    status=existing_running_job.status,
                    message="Analysis already in progress",
                )

        # Create new job
        job = AnalysisJob(
            repository_id=repository.id, commit_sha="pending", status=JobStatus.PENDING  # Will be updated by worker
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        logger.info(f"Created new analysis job: {job.id}")

        # Queue the job to Celery
        try:
            task_result = celery_client.send_task(
                "analyze_repo_task",
                args=[str(job.id)],
                kwargs={
                    "drip_list_max_length": analysis_request.drip_list_max_length,
                    "force_url_refresh": analysis_request.force_url_refresh,
                },
                queue="celery",
            )
            logger.info(f"Queued job {job.id} to Celery with task ID: {task_result.id}")
        except Exception as e:
            logger.error(f"Failed to queue job {job.id} to Celery: {e}")
            # Update job status to failed
            job.status = JobStatus.FAILED
            job.error_message = f"Failed to queue task: {str(e)}"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to queue analysis job"
            )

        # Attempt job runtime prediction
        predicted = None
        try:
            predicted = estimate_duration_seconds(analysis_request.repo_url)
            if predicted is not None:
                job.predicted_duration_seconds = predicted
                db.commit()
                db.refresh(job)
        except Exception:
            logger.warning("Prediction failed; continuing without predicted_duration_seconds")

        return AnalysisRunResponse(
            job_id=job.id,
            repository_id=repository.id,
            status=job.status,
            message="Analysis queued successfully",
            predicted_duration_seconds=job.predicted_duration_seconds,
        )

    except Exception as e:
        logger.error(f"Failed to create analysis job: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create analysis job")


@app.get("/api/v1/analyses/{job_id}", response_model=JobStatusResponse, tags=["Analysis"])
async def get_job_status(job_id: UUID, db: Session = Depends(get_db)):
    """Get the status of a specific analysis job"""
    job = db.query(AnalysisJob).filter_by(id=job_id).first()

    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    # Flip stale RUNNING jobs to FAILED on status check
    try:
        if job.status == JobStatus.RUNNING:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.api.RUNNING_JOB_STALE_SECONDS)
            # Only consider jobs that actually started (started_at set by worker)
            # Fallback to commit_sha check for older records
            started = job.started_at
            actually_started = bool(started) or (job.commit_sha and job.commit_sha != "pending")
            reference_time = started or job.created_at
            if actually_started and reference_time and reference_time < cutoff:
                job.status = JobStatus.FAILED
                job.error_message = (
                    f"Job exceeded allowed runtime "
                    f"({settings.api.RUNNING_JOB_STALE_SECONDS}s) and was marked stale by API"
                )
                job.stale_marked_at = datetime.now(timezone.utc)
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
                db.refresh(job)
    except Exception as e:
        logger.warning(f"Failed to apply stale status on job {job_id}: {e}")

    # Compute elapsed runtime seconds from job start and freeze at completion
    # so elapsed doesn't continune to accumulate after DONE
    elapsed = None
    try:
        start_ts = job.started_at
        if start_ts:
            end_ts = job.completed_at or datetime.now(timezone.utc)
            seconds = (end_ts - start_ts).total_seconds()
            elapsed = Decimal(seconds if seconds > 0 else 0)
    except Exception:
        elapsed = None

    return JobStatusResponse(
        job_id=job.id,
        repository_id=job.repository_id,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        commit_sha=job.commit_sha if job.commit_sha != "pending" else None,
        predicted_duration_seconds=job.predicted_duration_seconds,
        elapsed_seconds=elapsed,
    )


@app.get(
    "/api/v1/repositories/{repository_id}/results/latest", response_model=AnalysisResultsResponse, tags=["Results"]
)
async def get_latest_results(repository_id: UUID, db: Session = Depends(get_db)):
    """Get the latest successful analysis results for a repository"""
    # Find the latest completed job with eager loading of related data
    job = (
        db.query(AnalysisJob)
        .options(joinedload(AnalysisJob.drip_list_items))
        .filter(AnalysisJob.repository_id == repository_id, AnalysisJob.status == JobStatus.COMPLETED)
        .order_by(AnalysisJob.completed_at.desc())
        .first()
    )

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No completed analysis found for this repository"
        )

    # Build response
    drip_list = [
        DripListItemResponse(
            package_name=item.package_name, package_url=item.package_url, split_percentage=item.split_percentage
        )
        for item in job.drip_list_items
    ]

    return AnalysisResultsResponse(
        job_id=job.id,
        repository_id=job.repository_id,
        commit_sha=job.commit_sha,
        completed_at=job.completed_at,
        results=drip_list,
    )


@app.get("/api/v1/repositories/results/latest", response_model=AnalysisResultsResponse, tags=["Results"])
async def get_latest_results_by_url(repository_url: str, db: Session = Depends(get_db)):
    """
    Get the latest successful analysis results for a repository by URL

    Accepts URLs like:
        https://github.com/owner/repo
        http://github.com/owner/repo
        github.com/owner/repo
        git@github.com:owner/repo.git
    """
    try:
        canonical = canonicalize_repo_url(repository_url)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid repository_url")

    repo = db.query(Repository).filter(Repository.canonical_url == canonical).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    job = (
        db.query(AnalysisJob)
        .options(joinedload(AnalysisJob.drip_list_items), joinedload(AnalysisJob.analysis_metadata))
        .filter(AnalysisJob.repository_id == repo.id, AnalysisJob.status == JobStatus.COMPLETED)
        .order_by(AnalysisJob.completed_at.desc())
        .first()
    )

    if not job:
        raise HTTPException(status_code=404, detail="No completed analysis found for this repository")

    # Build response
    drip_list = [
        DripListItemResponse(
            package_name=item.package_name, package_url=item.package_url, split_percentage=item.split_percentage
        )
        for item in job.drip_list_items
    ]

    return AnalysisResultsResponse(
        job_id=job.id,
        repository_id=job.repository_id,
        commit_sha=job.commit_sha,
        completed_at=job.completed_at,
        results=drip_list,
    )


# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    error_response = ErrorResponse(
        error=exc.__class__.__name__, message=exc.detail, detail={"status_code": exc.status_code}
    )
    return JSONResponse(status_code=exc.status_code, content=error_response.dict())


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler"""
    if settings.ENVIRONMENT == "production":
        logger.error("Unhandled exception", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
    # In non-production, re-raise for full traceback during development
    raise exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app, host=settings.api.API_HOST, port=settings.api.API_PORT, log_level="info" if not settings.DEBUG else "debug"
    )
