"""
Storage backends for persisting analysis results
"""

from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal

from gardener.common.utils import get_logger
from services.shared.compression import to_gzip_bytes
from services.shared.database import get_db_session
from services.shared.models import AnalysisJob, AnalysisMetadata, DripListItem, PackageUrlCache
from services.shared.url_cache import UrlCacheService
from services.shared.utils import normalize_drip_list

logger = get_logger(__name__)


class StorageBackend(ABC):
    """Abstract base class for storage backends"""

    @abstractmethod
    def save_analysis_results(
        self, job_id, commit_sha, drip_list, metadata, complete_analysis_results, drip_list_max_length=200
    ):
        """
        Persists all structured results and artifacts from a completed analysis

        This method should handle the entire transaction of writing to the
        drip_list_items, analysis_metadata, and graph artifact storage

        Args:
            job_id (UUID): UUID of the analysis job
            commit_sha (str): Git commit SHA that was analyzed
            drip_list (list): List of dependencies with funding percentages
            metadata (dict): Analysis metadata (languages, counts, etc.)
            complete_analysis_results (dict): Complete analysis results including graph data and metadata
            drip_list_max_length (int): Maximum number of dependencies to include in normalized drip list
        """
        pass


class PostgresStorageBackend(StorageBackend):
    """PostgreSQL implementation of the storage backend"""

    def __init__(self):
        logger.info("Initialized PostgreSQL storage backend")

    def save_analysis_results(
        self,
        job_id,
        commit_sha,
        drip_list,
        metadata,
        complete_analysis_results,
        drip_list_max_length=200,
        force_url_refresh=False,
        external_packages=None,
    ):
        """
        Save analysis results to PostgreSQL database

        This performs a transactional save of:
        1. Compressed complete analysis results to analysis_jobs.graph_data_gz
        2. Individual Drip List items to drip_list_items table
        3. Analysis metadata to analysis_metadata table
        4. Package URL cache updates
        """
        logger.info(f"PostgresStorageBackend.save_analysis_results called for job {job_id}")
        logger.info(f"Drip list items: {len(drip_list)}")
        logger.info(f"Metadata keys: {list(metadata.keys())}")

        with get_db_session() as db:
            try:
                # Get the job record with repository relationship
                job = db.query(AnalysisJob).filter_by(id=job_id).first()
                if not job:
                    raise ValueError(f"Job {job_id} not found")

                # Get repository URL for denormalization
                repository = job.repository
                canonical_url = repository.canonical_url

                # Update commit SHA if needed
                if job.commit_sha != commit_sha:
                    job.commit_sha = commit_sha

                # Compress and save complete analysis results
                analysis_compressed = to_gzip_bytes(complete_analysis_results)
                job.graph_data_gz = analysis_compressed
                logger.info(f"Compressed analysis results: {len(analysis_compressed)} bytes gzipped")

                # Normalize Drip List to filter out empty URLs, self-references, and ensure 100% total
                normalized_drip_list = normalize_drip_list(
                    drip_list, max_length=drip_list_max_length, analyzed_repo_url=canonical_url
                )

                # Get the analysis completion timestamp
                # Note: This is called after the analysis is done, so we use current time
                # The job's completed_at will be set by the worker after this method returns
                from datetime import timezone

                analyzed_at = datetime.now(timezone.utc)

                # Save normalized Drip List items
                for item in normalized_drip_list:
                    drip_item = DripListItem(
                        job_id=job_id,
                        package_name=item["package_name"],
                        package_url=item.get("package_url"),
                        split_percentage=item["split_percentage"],
                        repository_url=canonical_url,
                        analyzed_at=analyzed_at,
                    )
                    db.add(drip_item)

                # Update package URL cache using original external package names
                if external_packages:
                    logger.info(f"Updating cache for {len(external_packages)} external packages")
                    for original_name, pkg_data in external_packages.items():
                        package_url = pkg_data.get("repository_url", "")
                        if package_url:
                            self._update_package_url_cache(
                                db,
                                package_name=original_name,
                                package_url=package_url,
                                ecosystem=pkg_data.get("ecosystem", "unknown"),
                                force_refresh=force_url_refresh,
                            )
                else:
                    logger.warning("No external_packages provided for cache updates")

                logger.info(f"Saved {len(normalized_drip_list)} Drip List items (filtered from {len(drip_list)})")

                # Save analysis metadata
                analysis_meta = AnalysisMetadata(
                    job_id=job_id,
                    total_files=metadata.get("total_files", 0),
                    languages_detected=metadata.get("languages_detected", []),
                    analysis_duration_seconds=Decimal(str(metadata.get("analysis_duration_seconds", 0))),
                    graph_size_bytes=len(analysis_compressed),
                )
                db.add(analysis_meta)
                logger.info("Saved analysis metadata")

                # Transaction will be committed by the context manager
                logger.info(f"Successfully saved all analysis results for job {job_id}")

            except Exception as e:
                logger.error(f"Failed to save analysis results: {e}")
                db.rollback()
                raise

    def _update_package_url_cache(self, db, package_name, package_url, ecosystem, force_refresh=False):
        """Update the package URL cache"""
        try:
            # Check if entry already exists
            # Delegate to shared service
            UrlCacheService().upsert(
                db=db,
                package_name=package_name,
                ecosystem=ecosystem,
                repository_url=package_url,
                force_refresh=force_refresh,
            )

        except Exception as e:
            # Don't fail the whole transaction for cache updates
            logger.warning(f"Failed to update URL cache for {package_name}: {e}")


# Default storage backend instance
storage_backend = PostgresStorageBackend()
