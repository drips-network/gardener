"""
Backfill S3 artifacts from legacy graph_data_gz entries

Usage:
    python services/scripts/backfill_artifacts_from_db.py
"""

import gzip
import json

from sqlalchemy import text

from services.shared.artifacts import (
    build_artifact_key,
    make_graph_pickle_bytes,
    make_results_json_bytes,
)
from services.shared.config import settings
from services.shared.database import get_db_session
from services.shared.models import AnalysisArtifact, ArtifactType
from services.shared.object_storage import upload_bytes


def _iter_jobs_with_blob(db):
    """
    Yield dict rows for jobs where graph_data_gz still exists

    Args:
        db (Session): SQLAlchemy session

    Returns:
        list: Query results with job id, commit sha, canonical url, blob
    """
    query = text(
        """
        SELECT
            j.id,
            j.commit_sha,
            j.graph_data_gz,
            r.canonical_url
        FROM analysis_jobs j
        JOIN repositories r ON r.id = j.repository_id
        WHERE j.graph_data_gz IS NOT NULL
        """
    )
    return db.execute(query)


def _artifact_exists(db, job_id, artifact_type):
    """
    Check whether an artifact of the given type already exists for a job

    Args:
        db (Session): SQLAlchemy session
        job_id (UUID): Job identifier
        artifact_type (ArtifactType): Artifact type to check

    Returns:
        bool: True if already present
    """
    count_query = (
        db.query(AnalysisArtifact)
        .filter(AnalysisArtifact.job_id == job_id, AnalysisArtifact.artifact_type == artifact_type)
        .count()
    )
    return count_query > 0


def main():
    """
    Convert stored graph_data_gz payloads into S3 artifacts

    Reads legacy blobs, uploads converted artifacts, and records metadata rows
    """
    with get_db_session() as db:
        rows = list(_iter_jobs_with_blob(db))
        if not rows:
            print("No legacy graph_data_gz rows found")
            return

        bucket = settings.object_storage.BUCKET

        for job_row in rows:
            job_id = job_row.id
            blob = job_row.graph_data_gz
            if not blob:
                continue

            if _artifact_exists(db, job_id, ArtifactType.GRAPH_PICKLE) and _artifact_exists(
                db, job_id, ArtifactType.RESULTS_JSON
            ):
                continue

            payload = json.loads(gzip.decompress(blob).decode("utf-8"))
            graph_node_link = payload.get("dependency_graph") or {}

            graph_key = build_artifact_key(job_row.canonical_url, job_row.commit_sha, job_id, "graph.pkl")
            results_key = build_artifact_key(job_row.canonical_url, job_row.commit_sha, job_id, "results.json")

            graph_meta = upload_bytes(
                bucket=bucket,
                object_key=graph_key,
                data_bytes=make_graph_pickle_bytes(graph_node_link),
                content_type="application/octet-stream",
                metadata={"artifact": "graph_pickle"},
            )
            results_meta = upload_bytes(
                bucket=bucket,
                object_key=results_key,
                data_bytes=make_results_json_bytes(payload),
                content_type="application/json",
                metadata={"artifact": "results_json"},
            )

            if not _artifact_exists(db, job_id, ArtifactType.GRAPH_PICKLE):
                db.add(
                    AnalysisArtifact(
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
                )

            if not _artifact_exists(db, job_id, ArtifactType.RESULTS_JSON):
                db.add(
                    AnalysisArtifact(
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
                )

            db.execute(
                text("UPDATE analysis_jobs SET graph_data_gz = NULL WHERE id = :job_id"),
                {"job_id": job_id},
            )

        print(f"Processed {len(rows)} analysis_jobs rows")


if __name__ == "__main__":
    main()
