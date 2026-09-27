"""
Focused integration tests for core evidence metadata wiring
"""

import json
import os
from pathlib import Path

import pytest

from gardener import main_cli
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
    assert all("repository_url_resolution" in package_data for package_data in results["external_packages"].values())

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
    package_dependencies = [dependency for dependency in summary["dependencies"] if dependency["kind"] == "package-manager"]
    assert package_dependencies
    assert "source" in package_dependencies[0]["url_resolution"]
    assert "checked_at" in package_dependencies[0]["url_resolution"]


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


@pytest.mark.integration
def test_cli_persists_environment_and_locked_import_evidence(tmp_path, monkeypatch, fake_pypi, offline_mode):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("PyYAML\nrequests\n")
    (repo / "app.py").write_text("import yaml\nimport requests\n")
    (repo / "uv.lock").write_text(
        '[[package]]\nname="requests"\nversion="1"\nsource={registry="https://pypi.org/simple"}\n'
        '[[package]]\nname="transitive"\nversion="1"\nsource={registry="https://pypi.org/simple"}\n'
    )
    metadata = tmp_path / "env/lib/python3.11/site-packages/pyyaml-6.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "top_level.txt").write_text("yaml\n_yaml\n")
    locked_url = fake_pypi.add_release("requests", "1", {"p.dist-info/top_level.txt": "requests"})
    latest_url = fake_pypi.add_release("requests", "2", {"p.dist-info/top_level.txt": "wrong"})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["gardener", str(repo), "--python-env", "env", "-o", "evidence"])
    with offline_mode.set_responses({}):
        main_cli.main()

    results = json.loads((tmp_path / "output/evidence_dependency_analysis.json").read_text())
    packages = results["external_packages"]
    assert packages["PyYAML"]["import_names"] == ["_yaml", "yaml"]
    assert packages["PyYAML"]["import_name_resolution"] == {
        "source": "installed-environment", "versions": ["6"], "lockfiles": [],
    }
    assert packages["requests"]["import_name_resolution"] == {
        "source": "pypi:locked-version", "versions": ["1"], "lockfiles": ["uv.lock"],
    }
    assert "transitive" not in packages
    edges = {(edge["source"], edge["target"]) for edge in results["dependency_graph"]["links"]}
    assert ("app.py", "PyYAML") in edges
    assert ("app.py", "requests") in edges
    assert fake_pypi.requested_urls == ["https://pypi.org/pypi/requests/json", locked_url]
    assert latest_url not in fake_pypi.requested_urls


@pytest.mark.integration
def test_unsearchable_environment_exits_two_before_analysis(tmp_path, monkeypatch, capsys):
    root = tmp_path / "env"
    root.mkdir()
    original_is_dir = Path.is_dir

    def denied_layout(path):
        if path == root / "lib":
            raise PermissionError("layout is not searchable")
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", denied_layout)
    monkeypatch.setattr("sys.argv", ["gardener", str(tmp_path), "--python-env", str(root)])
    with pytest.raises(SystemExit) as error:
        main_cli.main()
    assert error.value.code == 2
    assert "layout is not searchable" in capsys.readouterr().err


@pytest.mark.integration
def test_cli_invalid_environment_fails_before_analysis(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["gardener", str(tmp_path / "missing-repo"), "--python-env", "missing-env"]
    )
    with pytest.raises(SystemExit) as error:
        main_cli.main()
    assert error.value.code == 2
    assert "Cannot read Python environment" in capsys.readouterr().err
    assert not (tmp_path / "output").exists()
