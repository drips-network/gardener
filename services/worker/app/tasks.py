"""
Celery tasks for repository analysis
"""

import os
import shutil
import tempfile
import time
from datetime import datetime, timezone
from uuid import UUID

import networkx as nx
from celery import Task

from gardener.analysis.main import DependencyAnalyzer
from gardener.common.subprocess import SecureSubprocess, SubprocessSecurityError
from gardener.common.utils import get_logger
from gardener.package_metadata.url_resolver import resolve_package_urls
from services.shared.config import settings
from services.shared.database import get_db_session
from services.shared.errors import AnalysisError, AnalysisErrorType
from services.shared.models import AnalysisJob, JobStatus
from services.shared.storage import storage_backend
from services.shared.url_cache import UrlCacheService
from services.worker.app.main import app

logger = get_logger("worker.tasks")


def _clone_repository(repo_url, work_dir, timeout, job_id=None):
    """
    Clone repository into work_dir/repo using a shallow, blobless clone

    Args:
        repo_url (str): Repository URL
        work_dir (str): Temporary working directory
        timeout (int): Timeout in seconds for clone operation
        job_id (str|UUID): Optional job id for immediate failure marking

    Returns:
        str: Path to the cloned repository directory

    Raises:
        AnalysisError: If cloning fails
    """
    repo_dir = os.path.join(work_dir, "repo")
    logger.info(f"Cloning repository to {repo_dir}")
    secure_subprocess = SecureSubprocess(allowed_root=work_dir, timeout=timeout)
    # Disable any interactive credential prompts for non-interactive worker
    clone_result = secure_subprocess.run(
        ["git", "clone", "--depth", "1", "--filter=blob:none", "--single-branch", repo_url, repo_dir],
        env={
            "GIT_TERMINAL_PROMPT": "0",  # never prompt for creds in worker
            "GIT_ASKPASS": "/bin/echo",  # empty askpass to short-circuit
            "GIT_SSH_COMMAND": "ssh -o BatchMode=yes",
        },
    )

    if clone_result.returncode != 0:
        # Attempt to mark the job FAILED immediately if job_id provided
        if job_id is not None:
            try:
                with get_db_session() as db:
                    j = db.query(AnalysisJob).filter_by(id=UUID(str(job_id))).first()
                    if j:
                        j.status = JobStatus.FAILED
                        j.error_message = f"Git clone failed: {clone_result.stderr}"
                        j.completed_at = datetime.now(timezone.utc)
                        db.commit()
                        logger.error(f"Marked job {job_id} as FAILED due to clone error")
            except Exception as upd_err:
                logger.error(f"Failed to mark job {job_id} as FAILED in _clone_repository: {upd_err}")
        raise AnalysisError(AnalysisErrorType.CLONE_FAILED, f"Git clone failed: {clone_result.stderr}")
    return repo_dir


def _read_head_commit_sha(repo_dir):
    """
    Get HEAD commit SHA

    Args:
        repo_dir (str): Path to repository directory

    Returns:
        str: Commit SHA string

    Raises:
        AnalysisError: If reading commit SHA fails
    """
    repo_subprocess = SecureSubprocess(allowed_root=repo_dir, timeout=30)
    commit_result = repo_subprocess.run(["git", "rev-parse", "HEAD"])
    if commit_result.returncode != 0:
        raise AnalysisError(AnalysisErrorType.CLONE_FAILED, f"Failed to read commit SHA: {commit_result.stderr}")
    return commit_result.stdout.strip()


def _preload_url_cache(db, external_packages):
    """
    Preload cache hits keyed 'ecosystem:package_name'

    Args:
        db (Session): Database session
        external_packages (dict): Discovered external packages

    Returns:
        dict: Mapping of '<ecosystem>:<package_name>' to resolved URL
    """
    service = UrlCacheService()
    return service.preload(db, external_packages)


def _resolve_repository_urls(external_packages, logger_obj, cache):
    """
    Use resolve_package_urls(...) and merge back into external_packages

    Args:
        external_packages (dict): Discovered packages
        logger_obj: Logger instance to pass to resolver
        cache (dict): Preloaded cache mapping

    Returns:
        dict[str,str]: Mapping of package_name to repository_url
    """
    return resolve_package_urls(external_packages, logger_obj, cache=cache)


def _build_drip_list(analysis_results):
    """
    Convert 'top_dependencies' into raw drip list format required by storage

    Args:
        analysis_results (dict): Results from analyzer.analyze_dependencies

    Returns:
        list[dict]: Drip list items
    """
    drip_list = []
    for dep in analysis_results.get("top_dependencies", []):
        drip_list.append(
            {
                "package_name": dep["package_name"],
                "package_url": dep.get("package_url", ""),
                "percentage": f"{dep['percentage']:.4f}",
                "ecosystem": dep.get("ecosystem", "unknown"),
            }
        )
    return drip_list


def _build_metadata(analysis_results, duration_seconds):
    """
    Build metadata summary for analysis

    Args:
        analysis_results (dict): Analyzer results
        duration_seconds (float): Analysis duration in seconds

    Returns:
        dict: Metadata dictionary
    """
    analyzer_details = analysis_results.get("analyzer_details", {})
    return {
        "total_files": analyzer_details.get("total_files", 0),
        "languages_detected": analyzer_details.get("languages_detected", []),
        "analysis_duration_seconds": duration_seconds,
        "graph_size_bytes": len(str(analysis_results.get("dependency_graph", {}))),
    }


def _persist_all(
    job_id,
    commit_sha,
    drip_list,
    metadata,
    analysis_results,
    external_packages,
    drip_list_max_length,
    force_url_refresh,
):
    """
    Wrap storage_backend.save_analysis_results with the exact arguments used today

    Args:
        job_id (UUID): Analysis job id
        commit_sha (str): Git commit SHA
        drip_list (list): Drip list items
        metadata (dict): Metadata details
        analysis_results (dict): Full analysis results
        external_packages (dict): Discovered packages enriched with repo URLs
        drip_list_max_length (int): Max drip list size
        force_url_refresh (bool): Whether to refresh URL cache
    """
    storage_backend.save_analysis_results(
        job_id=job_id,
        commit_sha=commit_sha,
        drip_list=drip_list,
        metadata=metadata,
        complete_analysis_results=analysis_results,
        drip_list_max_length=drip_list_max_length,
        force_url_refresh=force_url_refresh,
        external_packages=external_packages,
    )


class AnalysisTask(Task):
    """Base task class with error handling"""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure"""
        job_id = args[0] if args else None
        logger.error(f"Task {task_id} failed for job {job_id}: {exc}")

        # Update job status in database
        if job_id:
            try:
                with get_db_session() as db:
                    # Ensure UUID type for lookup
                    _job_uuid = None
                    try:
                        _job_uuid = UUID(str(job_id))
                    except Exception:
                        _job_uuid = job_id
                    job = db.query(AnalysisJob).filter_by(id=_job_uuid).first()
                    if job:
                        job.status = JobStatus.FAILED
                        job.error_message = str(exc)
                        job.completed_at = datetime.now(timezone.utc)
                        db.commit()
            except Exception as e:
                logger.error(f"Failed to update job status: {e}")


@app.task(base=AnalysisTask, name="analyze_repo_task")
def analyze_repo_task(job_id, drip_list_max_length=200, force_url_refresh=False):
    """
    Main task for analyzing a repository

    Args:
        job_id (UUID): UUID of the analysis job
        drip_list_max_length (int): Maximum number of dependencies to return in drip list
        force_url_refresh (bool): If true, bypasses URL cache and fetches fresh repository URLs

    Returns:
        Dictionary with analysis results
    """
    logger.info(f"Starting analysis for job: {job_id}")
    start_time = time.time()
    repo_dir = None

    try:
        # Get job details from database
        with get_db_session() as db:
            job = db.query(AnalysisJob).filter_by(id=UUID(job_id)).first()
            if not job:
                raise AnalysisError(AnalysisErrorType.INVALID_REPO, f"Job {job_id} not found")

            # Update status to RUNNING and set started_at
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            db.commit()

            repo_url = job.repository.url
            logger.info(f"Analyzing repository: {repo_url}")

        # Create temporary directory for cloning
        work_dir = tempfile.mkdtemp(prefix=f"gardener-{job_id}-")

        try:
            # Clone and read HEAD commit
            repo_dir = _clone_repository(repo_url, work_dir, settings.worker.CLONE_TIMEOUT, job_id)
            commit_sha = _read_head_commit_sha(repo_dir)

            # Update job with commit SHA
            with get_db_session() as db:
                job = db.query(AnalysisJob).filter_by(id=UUID(job_id)).first()
                job.commit_sha = commit_sha
                db.commit()

            # Orchestrate analysis with targeted caching
            logger.info("Starting orchestrated analysis with targeted caching")

            try:
                # 1. Create analyzer and discover packages from manifests
                analyzer = DependencyAnalyzer(verbose=True)
                external_packages = analyzer.discover_packages(repo_dir)

                # 2. Query the cache for only the packages found
                preloaded_url_cache = {}
                if not force_url_refresh and external_packages:
                    logger.info(f"Querying URL cache for {len(external_packages)} packages...")
                    with get_db_session() as db:
                        preloaded_url_cache = _preload_url_cache(db, external_packages)
                    logger.info(f"Loaded {len(preloaded_url_cache)} items from URL cache.")
                elif force_url_refresh:
                    logger.info("URL cache refresh forced, skipping cache query.")

                # 3. Resolve URLs using the cache
                logger.info("Resolving URLs...")
                resolved_urls = _resolve_repository_urls(external_packages, analyzer.logger, preloaded_url_cache)

                # Update external packages with resolved URLs
                for name, url in resolved_urls.items():
                    if name in external_packages:
                        external_packages[name]["repository_url"] = url
                for name in external_packages:
                    external_packages[name].setdefault("repository_url", "")

                # 4. Analyze dependencies with resolved URLs
                logger.info("Completing analysis...")
                analysis_results = analyzer.analyze_dependencies(external_packages)

                # Calculate analysis duration
                analysis_duration = time.time() - start_time

                # Convert top dependencies to Drip List format
                drip_list = _build_drip_list(analysis_results)

                # Extract metadata
                metadata = _build_metadata(analysis_results, analysis_duration)

                # Generate visualizations
                graph_data = analysis_results.get("dependency_graph", {})

                # Save results using storage backend
                _persist_all(
                    job_id=job_id,
                    commit_sha=commit_sha,
                    drip_list=drip_list,
                    metadata=metadata,
                    analysis_results=analysis_results,
                    external_packages=external_packages,
                    drip_list_max_length=drip_list_max_length,
                    force_url_refresh=force_url_refresh,
                )

                # Optionally generate visualization HTML (for future use)
                if graph_data and "nodes" in graph_data:
                    try:
                        from gardener.visualization.generate_graph import generate_graph_viz  # noqa: WPS433

                        graph = nx.node_link_graph(graph_data)
                        graph_html = generate_graph_viz(graph, logger)

                        # These could be stored separately or included in metadata
                        logger.debug("Generated visualization HTML")
                    except Exception as viz_err:
                        logger.warning(f"Failed to generate visualizations: {viz_err}")

                logger.info(f"Gardener analysis completed successfully for {len(drip_list)} dependencies")

            except Exception as analysis_err:
                logger.error(f"Gardener analysis failed: {analysis_err}")
                raise AnalysisError(AnalysisErrorType.PARSE_ERROR, f"Dependency analysis failed: {str(analysis_err)}")
            logger.info("Analysis results saved to database")

            # Update job status to COMPLETED
            with get_db_session() as db:
                job = db.query(AnalysisJob).filter_by(id=UUID(job_id)).first()
                job.status = JobStatus.COMPLETED
                # Clear any stale error set earlier (e.g., API stale marker)
                job.error_message = None
                job.completed_at = datetime.now(timezone.utc)
                db.commit()

            logger.info(f"Analysis completed for job {job_id} in {analysis_duration:.2f}s")

            # Return results in expected format
            return {"drip_list": drip_list, "metadata": metadata, "graph_data": graph_data}

        finally:
            # Cleanup temporary directory
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)

    except AnalysisError as e:
        # Update job to FAILED, then re-raise to trigger Celery failure flow
        try:
            with get_db_session() as db:
                job = db.query(AnalysisJob).filter_by(id=UUID(job_id)).first()
                if job:
                    job.status = JobStatus.FAILED
                    job.error_message = str(e)
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
        except Exception as upd_err:
            logger.error(f"Failed to mark job {job_id} as FAILED after AnalysisError: {upd_err}")
        raise

    except SubprocessSecurityError as e:
        # Map secure subprocess timeouts explicitly
        if "timeout" in str(e).lower():
            logger.error(f"Repository operation timed out for job {job_id}: {e}")
            raise AnalysisError(AnalysisErrorType.TIMEOUT, "Repository operation timed out")
        logger.error(f"Subprocess error in job {job_id}: {e}")
        # Attempt to mark job as FAILED before raising
        try:
            with get_db_session() as db:
                job = db.query(AnalysisJob).filter_by(id=UUID(job_id)).first()
                if job:
                    job.status = JobStatus.FAILED
                    job.error_message = str(e)
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
        except Exception as upd_err:
            logger.error(f"Failed to mark job {job_id} as FAILED after SubprocessSecurityError: {upd_err}")
        raise AnalysisError(AnalysisErrorType.PARSE_ERROR, f"Analysis failed: {str(e)}")

    except Exception as e:
        # Last-resort safety net
        logger.error(f"Unexpected error in job {job_id}: {e}")
        # Attempt to mark job as FAILED before raising
        try:
            with get_db_session() as db:
                job = db.query(AnalysisJob).filter_by(id=UUID(job_id)).first()
                if job:
                    job.status = JobStatus.FAILED
                    job.error_message = str(e)
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
        except Exception as upd_err:
            logger.error(f"Failed to mark job {job_id} as FAILED after unexpected error: {upd_err}")
        raise AnalysisError(AnalysisErrorType.PARSE_ERROR, f"Analysis failed: {str(e)}")
