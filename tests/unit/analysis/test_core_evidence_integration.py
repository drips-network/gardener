"""
Focused integration tests for core evidence metadata wiring
"""

import json
import os

import pytest

from gardener.analysis import main as analysis_main
from gardener.analysis.evidence import ANALYSIS_SCHEMA_VERSION, MACHINE_SUMMARY_SCHEMA_VERSION
from gardener.analysis.main import run_analysis
from gardener.persistence.file import FilePersistence


@pytest.mark.integration
def test_run_analysis_persists_full_result_and_machine_summary_sidecar(tmp_path, offline_mode):
    """
    CLI analysis persistence writes the enriched full result and opt-in machine summary sidecar
    """
    fixture_repo_path = os.path.abspath("tests/fixtures/javascript")
    output_prefix = "issue569_item2_summary"
    persistence = FilePersistence(output_dir=str(tmp_path), verbose=False)

    with offline_mode.set_responses({}):
        results = run_analysis(
            repo_path=fixture_repo_path,
            output_prefix=output_prefix,
            verbose=False,
            minimal_outputs=True,
            focus_languages_str="javascript",
            config_overrides=None,
            persistence=persistence,
            machine_summary=True,
        )

    analysis_path = tmp_path / f"{output_prefix}_dependency_analysis.json"
    summary_path = tmp_path / f"{output_prefix}_dependency_summary.json"

    assert analysis_path.exists()
    assert summary_path.exists()
    assert results["schema_version"] == ANALYSIS_SCHEMA_VERSION
    assert results["repository"] == {
        "input": fixture_repo_path,
        "resolved_path": fixture_repo_path,
        "canonical_url": None,
        "commit_sha": None,
    }
    assert results["invocation"]["entrypoint"] == "cli"
    assert results["invocation"]["languages"] == ["javascript"]
    assert results["invocation"]["minimal_outputs"] is True
    assert results["invocation"]["visualize"] is False
    assert results["invocation"]["machine_summary"] is True
    assert "external_packages" in results
    assert "dependency_graph" in results
    assert "top_dependencies" in results
    assert "analyzer_details" in results

    first_dependency = results["top_dependencies"][0]
    for key in (
        "score",
        "dependency_kind",
        "runtime",
        "normalized_name",
        "url_resolution_status",
    ):
        assert key in first_dependency

    with analysis_path.open(encoding="utf-8") as analysis_file:
        persisted_analysis = json.load(analysis_file)
    with summary_path.open(encoding="utf-8") as summary_file:
        summary = json.load(summary_file)

    assert persisted_analysis["schema_version"] == ANALYSIS_SCHEMA_VERSION
    assert summary["schema_version"] == MACHINE_SUMMARY_SCHEMA_VERSION
    assert summary["repository"] == results["repository"]
    assert summary["invocation"] == results["invocation"]
    assert len(summary["dependencies"]) == len(results["top_dependencies"])
    assert summary["dependencies"][0]["evidence_ref"] == "top_dependencies[0]"


@pytest.mark.integration
def test_run_analysis_sanitizes_remote_repository_input_metadata(tmp_path, monkeypatch, offline_mode):
    """
    Remote URL provenance strips credentials and does not persist the temporary resolved path
    """
    fixture_repo_path = os.path.abspath("tests/fixtures/javascript")
    persistence = FilePersistence(output_dir=str(tmp_path), verbose=False)
    monkeypatch.setattr(analysis_main, "_prepare_repository_path", lambda repo_path, logger: fixture_repo_path)

    with offline_mode.set_responses({}):
        results = run_analysis(
            repo_path="https://user:token@github.com/example/repo.git",
            output_prefix="issue569_item2_sanitized_input",
            verbose=False,
            minimal_outputs=True,
            focus_languages_str="javascript",
            config_overrides=None,
            persistence=persistence,
            machine_summary=False,
        )

    assert results["repository"]["input"] == "https://github.com/example/repo.git"
    assert results["repository"]["resolved_path"] is None
