"""
Storage backends for persisting analysis results
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal

from gardener.common.utils import get_logger
from services.shared.artifacts import (
    build_artifact_key,
    make_graph_pickle_bytes,
    make_results_json_bytes,
)
from services.shared.config import settings
from services.shared.database import get_db_session
from services.shared.models import (
    AnalysisArtifact,
    AnalysisJob,
    AnalysisMetadata,
    DripListItem,
    PackageUrlCache,
    ArtifactType,
)
from services.shared.object_storage import upload_bytes
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
        1. Individual Drip List items to drip_list_items table
        2. Analysis metadata to analysis_metadata table
        3. Serialized artifacts uploaded to object storage with metadata tracked in analysis_artifacts
        4. Package URL cache updates
        """
        logger.info(f"PostgresStorageBackend.save_analysis_results called for job {job_id}")
        logger.info(f"Drip list items: {len(drip_list)}")
        logger.info(f"Metadata keys: {list(metadata.keys())}")

        with get_db_session() as db:
            try:
                job = db.query(AnalysisJob).filter_by(id=job_id).first()
                if not job:
                    raise ValueError(f"Job {job_id} not found")

                metadata = metadata or {}
                complete_analysis_results = complete_analysis_results or {}

                repository = job.repository
                canonical_url = repository.canonical_url

                if job.commit_sha != commit_sha:
                    job.commit_sha = commit_sha

                graph_node_link = complete_analysis_results.get("dependency_graph") or {}
                graph_pickle_bytes = make_graph_pickle_bytes(graph_node_link)
                results_json_bytes = make_results_json_bytes(complete_analysis_results)

                bucket = settings.object_storage.BUCKET
                graph_key = build_artifact_key(canonical_url, commit_sha, job_id, "graph.pkl")
                results_key = build_artifact_key(canonical_url, commit_sha, job_id, "results.json")

                graph_meta = upload_bytes(
                    bucket=bucket,
                    object_key=graph_key,
                    data_bytes=graph_pickle_bytes,
                    content_type="application/octet-stream",
                    metadata={"artifact": "graph_pickle"},
                )
                results_meta = upload_bytes(
                    bucket=bucket,
                    object_key=results_key,
                    data_bytes=results_json_bytes,
                    content_type="application/json",
                    metadata={"artifact": "results_json"},
                )

                normalized_drip_list = normalize_drip_list(
                    drip_list, max_length=drip_list_max_length, analyzed_repo_url=canonical_url
                )

                analyzed_at = datetime.now(timezone.utc)

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

                graph_row = AnalysisArtifact(
                    job_id=job_id,
                    artifact_type=ArtifactType.GRAPH_PICKLE,
                    bucket=bucket,
                    object_key=graph_key,
                    content_type="application/octet-stream",
                    size_bytes=graph_meta["size_bytes"],
                    etag=graph_meta["etag"],
                    checksum_md5=graph_meta["checksum_md5"],
                    checksum_sha256=graph_meta["checksum_sha256"],
                    version_id=graph_meta["version_id"],
                )
                db.add(graph_row)

                results_row = AnalysisArtifact(
                    job_id=job_id,
                    artifact_type=ArtifactType.RESULTS_JSON,
                    bucket=bucket,
                    object_key=results_key,
                    content_type="application/json",
                    size_bytes=results_meta["size_bytes"],
                    etag=results_meta["etag"],
                    checksum_md5=results_meta["checksum_md5"],
                    checksum_sha256=results_meta["checksum_sha256"],
                    version_id=results_meta["version_id"],
                )
                db.add(results_row)

                logger.info(
                    f"Uploaded artifacts for job {job_id}: graph={graph_key} ({graph_meta['size_bytes']}B), "
                    f"results={results_key} ({results_meta['size_bytes']}B)"
                )

                analysis_meta = AnalysisMetadata(
                    job_id=job_id,
                    total_files=metadata.get("total_files", 0),
                    languages_detected=metadata.get("languages_detected", []),
                    analysis_duration_seconds=Decimal(str(metadata.get("analysis_duration_seconds", 0))),
                    graph_size_bytes=graph_meta["size_bytes"],
                )
                db.add(analysis_meta)
                logger.info("Saved analysis metadata")
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
