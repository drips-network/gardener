"""
Focused tests for service worker evidence metadata wiring
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from gardener.analysis.evidence import ANALYSIS_SCHEMA_VERSION

pytestmark = pytest.mark.unit


class _FakeQuery:
    def __init__(self, job):
        self.job = job

    def filter_by(self, **kwargs):
        return self

    def first(self):
        return self.job


class _FakeDbSession:
    def __init__(self, job):
        self.job = job
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def query(self, model):
        return _FakeQuery(self.job)

    def commit(self):
        self.commits += 1


def test_analyze_repo_task_persists_service_repository_evidence_metadata(monkeypatch, tmp_path):
    """
    Worker analysis persists stable repository identity, not the temporary clone path
    """
    pytest.importorskip("boto3")
    pytest.importorskip("celery")
    pytest.importorskip("pydantic_settings")
    pytest.importorskip("sqlalchemy")
    monkeypatch.setenv("HMAC_SHARED_SECRET", "x" * 32)

    from services.worker.app import tasks as worker_tasks

    job_id = str(uuid4())
    commit_sha = "abc123def456"
    repo_url = "https://github.com/example/project"
    canonical_url = "github.com/example/project"
    job = SimpleNamespace(
        repository=SimpleNamespace(url=repo_url, canonical_url=canonical_url),
        predicted_duration_seconds=1,
        commit_sha="",
        status=None,
        started_at=None,
        completed_at=None,
        error_message=None,
    )
    fake_db = _FakeDbSession(job)
    work_dir = tmp_path / "worker"
    repo_dir = work_dir / "repo"
    captured = {}

    class FakeDependencyAnalyzer:
        def __init__(self, verbose=False, *, repository_metadata=None, invocation_metadata=None):
            self.logger = object()
            self.repository_metadata = repository_metadata
            self.invocation_metadata = invocation_metadata

        def discover_packages(self, discovered_repo_dir):
            assert discovered_repo_dir == str(repo_dir)
            return {"dep": {"ecosystem": "npm", "repository_url": ""}}

        def analyze_dependencies(self, external_packages):
            assert external_packages["dep"]["repository_url"] == "https://github.com/example/dep"
            return {
                "schema_version": ANALYSIS_SCHEMA_VERSION,
                "repository": self.repository_metadata,
                "invocation": self.invocation_metadata,
                "external_packages": external_packages,
                "dependency_graph": {},
                "top_dependencies": [
                    {
                        "package_name": "dep",
                        "package_url": "https://github.com/example/dep",
                        "percentage": 100.0,
                        "ecosystem": "npm",
                    }
                ],
                "analyzer_details": {"total_files": 1, "languages_detected": ["javascript"]},
            }

    def capture_persisted_results(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(worker_tasks, "get_db_session", lambda: fake_db)
    monkeypatch.setattr(worker_tasks.tempfile, "mkdtemp", lambda prefix: str(work_dir))
    monkeypatch.setattr(worker_tasks, "_clone_repository", lambda *args, **kwargs: str(repo_dir))
    monkeypatch.setattr(worker_tasks, "_read_head_commit_sha", lambda cloned_repo_dir: commit_sha)
    monkeypatch.setattr(worker_tasks, "DependencyAnalyzer", FakeDependencyAnalyzer)
    monkeypatch.setattr(worker_tasks, "_preload_url_cache", lambda db, external_packages: {})
    monkeypatch.setattr(
        worker_tasks,
        "_resolve_repository_urls",
        lambda external_packages, logger_obj, cache: {"dep": "https://github.com/example/dep"},
    )
    monkeypatch.setattr(worker_tasks, "_persist_all", capture_persisted_results)

    task_callable = getattr(worker_tasks.analyze_repo_task, "run", worker_tasks.analyze_repo_task)
    task_callable(job_id, drip_list_max_length=200, force_url_refresh=False)

    persisted_results = captured["analysis_results"]
    assert persisted_results["repository"] == {
        "input": repo_url,
        "resolved_path": None,
        "canonical_url": canonical_url,
        "commit_sha": commit_sha,
    }
    assert persisted_results["invocation"]["entrypoint"] == "service-worker"
    assert persisted_results["invocation"]["machine_summary"] is False
    assert captured["commit_sha"] == commit_sha
