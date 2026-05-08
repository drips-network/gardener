import copy
import re

import pytest

from gardener.analysis import evidence
from gardener.analysis.evidence import (
    ANALYSIS_SCHEMA_VERSION,
    DEPENDENCY_KIND_BUILTIN,
    DEPENDENCY_KIND_LOCAL,
    DEPENDENCY_KIND_PACKAGE_MANAGER,
    DEPENDENCY_KIND_UNKNOWN,
    MACHINE_SUMMARY_SCHEMA_VERSION,
    build_machine_summary,
    build_producer_metadata,
    build_repository_metadata,
    classify_dependency_fact,
    complete_invocation_metadata,
    enrich_analysis_result,
    enrich_external_packages,
    graph_digest,
)
from gardener.common.defaults import ConfigOverride


@pytest.mark.unit
def test_schema_and_provenance_metadata_contract(monkeypatch):
    monkeypatch.setenv("GARDENER_GIT_COMMIT", "producer-sha")
    monkeypatch.setattr(evidence.metadata, "version", lambda package_name: "9.9.9")

    with ConfigOverride({"CENTRALITY_METRIC": "katz"}):
        invocation = complete_invocation_metadata(
            {
                "entrypoint": "cli",
                "languages": ["javascript"],
                "minimal_outputs": True,
                "machine_summary": True,
            }
        )

    producer = build_producer_metadata()

    assert producer["name"] == "gardener"
    assert producer["version"] == "9.9.9"
    assert producer["git_commit"] == "producer-sha"
    assert build_producer_metadata(git_commit="explicit-sha")["git_commit"] == "explicit-sha"
    assert re.fullmatch(r"\d+\.\d+\.\d+", producer["python"])
    assert invocation == {
        "entrypoint": "cli",
        "languages": ["javascript"],
        "centrality_metric": "katz",
        "minimal_outputs": True,
        "visualize": None,
        "machine_summary": True,
        "config_overrides": {},
    }
    assert build_repository_metadata(
        input_value="https://github.com/example/repo",
        resolved_path=None,
        canonical_url="https://github.com/example/repo",
        commit_sha="abc123",
    ) == {
        "input": "https://github.com/example/repo",
        "resolved_path": None,
        "canonical_url": "https://github.com/example/repo",
        "commit_sha": "abc123",
    }
    assert build_repository_metadata(
        input_value="https://user:token@github.com/example/repo.git",
    )["input"] == "https://github.com/example/repo.git"

    result = enrich_analysis_result(
        {"external_packages": {}, "dependency_graph": {}, "top_dependencies": [], "analyzer_details": {}},
        repository_metadata={"input": "repo", "resolved_path": "/repo", "canonical_url": None, "commit_sha": None},
        invocation_metadata={"entrypoint": "cli"},
        created_at="2026-05-08T12:34:56Z",
    )

    assert result["schema_version"] == ANALYSIS_SCHEMA_VERSION
    assert result["repository"] == {"input": "repo", "resolved_path": "/repo", "canonical_url": None, "commit_sha": None}
    assert result["invocation"]["entrypoint"] == "cli"
    assert result["created_at"] == "2026-05-08T12:34:56Z"


@pytest.mark.unit
def test_producer_metadata_falls_back_when_package_metadata_is_missing(monkeypatch):
    def raise_package_not_found(package_name):
        raise evidence.metadata.PackageNotFoundError(package_name)

    monkeypatch.delenv("GARDENER_GIT_COMMIT", raising=False)
    monkeypatch.setattr(evidence.metadata, "version", raise_package_not_found)

    producer = build_producer_metadata()

    assert producer["version"] == "unknown"
    assert producer["git_commit"] is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "ecosystem", "language", "expected"),
    [
        (
            "fs",
            "js_stdlib",
            "javascript",
            {
                "dependency_kind": DEPENDENCY_KIND_BUILTIN,
                "runtime": "node",
                "normalized_name": "node:fs",
                "url_resolution_status": "not-applicable",
            },
        ),
        (
            "node:assert/strict",
            "ts_stdlib",
            "typescript",
            {
                "dependency_kind": DEPENDENCY_KIND_BUILTIN,
                "runtime": "node",
                "normalized_name": "node:assert/strict",
                "url_resolution_status": "not-applicable",
            },
        ),
        (
            "os.path",
            "python_stdlib",
            "python",
            {
                "dependency_kind": DEPENDENCY_KIND_BUILTIN,
                "runtime": "python",
                "normalized_name": "os",
                "url_resolution_status": "not-applicable",
            },
        ),
        (
            "net/http",
            "go_stdlib",
            "go",
            {
                "dependency_kind": DEPENDENCY_KIND_BUILTIN,
                "runtime": "go",
                "normalized_name": "net/http",
                "url_resolution_status": "not-applicable",
            },
        ),
        (
            "std::collections",
            "rust_stdlib",
            "rust",
            {
                "dependency_kind": DEPENDENCY_KIND_BUILTIN,
                "runtime": "rust",
                "normalized_name": "std",
                "url_resolution_status": "not-applicable",
            },
        ),
    ],
)
def test_dependency_classification_for_platform_builtins(name, ecosystem, language, expected):
    assert classify_dependency_fact(name, ecosystem=ecosystem, language=language) == expected


@pytest.mark.unit
def test_dependency_classification_for_package_manager_and_unknown_dependencies():
    assert classify_dependency_fact(
        "requests",
        ecosystem="pypi",
        is_package_manager=True,
        repository_url="https://github.com/psf/requests",
    ) == {
        "dependency_kind": DEPENDENCY_KIND_PACKAGE_MANAGER,
        "runtime": None,
        "normalized_name": "requests",
        "url_resolution_status": "resolved",
    }
    assert classify_dependency_fact("github.com/acme/pkg", ecosystem="go_stdlib", language="go") == {
        "dependency_kind": DEPENDENCY_KIND_UNKNOWN,
        "runtime": None,
        "normalized_name": "github.com/acme/pkg",
        "url_resolution_status": "not-applicable",
    }
    assert classify_dependency_fact("./local", ecosystem="npm", is_package_manager=True, is_local=True) == {
        "dependency_kind": DEPENDENCY_KIND_LOCAL,
        "runtime": None,
        "normalized_name": "./local",
        "url_resolution_status": "not-applicable",
    }
    assert classify_dependency_fact("not-a-core-module", ecosystem="js_stdlib", language="javascript") == {
        "dependency_kind": DEPENDENCY_KIND_UNKNOWN,
        "runtime": None,
        "normalized_name": "not-a-core-module",
        "url_resolution_status": "not-applicable",
    }

    enriched = enrich_external_packages(
        {
            "zod": {"ecosystem": "npm", "version": "^3.0.0", "repository_url": "https://github.com/colinhacks/zod"},
            "left-pad": {"ecosystem": "npm", "version": "^1.0.0"},
        }
    )

    assert enriched["zod"]["dependency_kind"] == DEPENDENCY_KIND_PACKAGE_MANAGER
    assert enriched["zod"]["normalized_name"] == "zod"
    assert enriched["zod"]["url_resolution_status"] == "resolved"
    assert enriched["left-pad"]["url_resolution_status"] == "unresolved"


@pytest.mark.unit
def test_graph_digest_is_deterministic_across_node_link_ordering():
    graph_one = {
        "directed": True,
        "nodes": [
            {"id": "b.py", "type": "file", "language": "python"},
            {"id": "requests", "type": "package", "ecosystem": "pypi"},
        ],
        "links": [
            {"source": "b.py", "target": "requests", "type": "imports_package", "weight": 0.5},
            {"source": "a.py", "target": "b.py", "type": "imports_local", "weight": 0.7},
        ],
    }
    graph_two = {
        "links": [
            {"weight": 0.7, "target": "b.py", "type": "imports_local", "source": "a.py"},
            {"weight": 0.5, "target": "requests", "source": "b.py", "type": "imports_package"},
        ],
        "nodes": [
            {"type": "package", "ecosystem": "pypi", "id": "requests"},
            {"language": "python", "type": "file", "id": "b.py"},
        ],
        "directed": True,
    }

    digest = graph_digest(graph_one)

    assert digest == graph_digest(graph_two)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)


@pytest.mark.unit
def test_graph_digest_is_deterministic_across_tied_sort_keys():
    graph_one = {
        "nodes": [
            {"id": "pkg", "type": "package", "ecosystem": "npm"},
            {"id": "pkg", "type": "package", "ecosystem": "pypi"},
        ],
        "links": [
            {"source": "a.py", "target": "pkg", "type": "imports_package", "weight": 0.5},
            {"source": "a.py", "target": "pkg", "type": "imports_package", "weight": 0.7},
        ],
    }
    graph_two = {
        "links": list(reversed(graph_one["links"])),
        "nodes": list(reversed(graph_one["nodes"])),
    }

    assert graph_digest(graph_one) == graph_digest(graph_two)


@pytest.mark.unit
def test_enrichment_helpers_reject_malformed_required_inputs():
    with pytest.raises(ValueError, match="result must be a dict"):
        enrich_analysis_result(None, repository_metadata=None, invocation_metadata=None)

    with pytest.raises(ValueError, match="external_packages must be a dict"):
        enrich_external_packages(None)

    with pytest.raises(ValueError, match=r"external_packages\[zod\] must be a dict"):
        enrich_external_packages({"zod": None})


def _valid_summary_analysis_result():
    return {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "producer": {"name": "gardener", "version": "0.1.2", "git_commit": None, "python": "3.11.8"},
        "repository": {"input": "repo", "resolved_path": "/repo", "canonical_url": None, "commit_sha": "abc123"},
        "created_at": "2026-05-08T12:34:56Z",
        "invocation": {
            "entrypoint": "cli",
            "languages": ["javascript"],
            "centrality_metric": "pagerank",
            "minimal_outputs": True,
            "visualize": False,
            "machine_summary": True,
            "config_overrides": {},
        },
        "dependency_graph": {
            "nodes": [{"id": "zod", "type": "package"}],
            "links": [],
        },
        "top_dependencies": [
            {
                "package_name": "zod",
                "percentage": 100.0,
                "score": 0.08,
                "package_url": "https://github.com/colinhacks/zod",
                "ecosystem": "npm",
                "dependency_kind": "package-manager",
                "runtime": None,
                "normalized_name": "zod",
                "url_resolution_status": "resolved",
            }
        ],
        "analyzer_details": {"languages_detected": ["javascript"], "total_files": 1},
    }


@pytest.mark.unit
def test_machine_summary_projects_enriched_analysis_result_in_dependency_order():
    analysis_result = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "producer": {"name": "gardener", "version": "0.1.2", "git_commit": None, "python": "3.11.8"},
        "repository": {"input": "repo", "resolved_path": "/repo", "canonical_url": None, "commit_sha": "abc123"},
        "created_at": "2026-05-08T12:34:56Z",
        "invocation": {
            "entrypoint": "cli",
            "languages": ["javascript"],
            "centrality_metric": "pagerank",
            "minimal_outputs": True,
            "visualize": False,
            "machine_summary": True,
            "config_overrides": {},
        },
        "dependency_graph": {
            "nodes": [
                {"id": "zod", "type": "package"},
                {"id": "src/index.ts", "type": "file"},
            ],
            "links": [{"source": "src/index.ts", "target": "zod", "type": "imports_package"}],
        },
        "top_dependencies": [
            {
                "package_name": "zod",
                "percentage": 80.0,
                "score": 0.08,
                "package_url": "https://github.com/colinhacks/zod",
                "ecosystem": "npm",
                "dependency_kind": "package-manager",
                "runtime": None,
                "normalized_name": "zod",
                "url_resolution_status": "resolved",
            },
            {
                "package_name": "fs",
                "percentage": 20.0,
                "score": 0.02,
                "package_url": "",
                "ecosystem": "ts_stdlib",
                "dependency_kind": "builtin",
                "runtime": "node",
                "normalized_name": "node:fs",
                "url_resolution_status": "not-applicable",
            },
        ],
        "analyzer_details": {"languages_detected": ["typescript", "javascript"], "total_files": 7},
    }

    summary = build_machine_summary(analysis_result)

    assert summary["schema_version"] == MACHINE_SUMMARY_SCHEMA_VERSION
    assert summary["producer"] == analysis_result["producer"]
    assert summary["repository"] == analysis_result["repository"]
    assert summary["created_at"] == "2026-05-08T12:34:56Z"
    assert summary["analysis"] == {
        "languages_detected": ["javascript", "typescript"],
        "total_files": 7,
        "centrality_metric": "pagerank",
        "graph": {
            "nodes": 2,
            "links": 1,
            "digest": graph_digest(analysis_result["dependency_graph"]),
        },
    }
    assert summary["dependencies"] == [
        {
            "name": "zod",
            "kind": "package-manager",
            "ecosystem": "npm",
            "runtime": None,
            "normalized_name": "zod",
            "repository_url": "https://github.com/colinhacks/zod",
            "url_resolution": {"status": "resolved"},
            "centrality": {"metric": "pagerank", "percentage": 80.0, "score": 0.08},
            "evidence_ref": "top_dependencies[0]",
        },
        {
            "name": "fs",
            "kind": "builtin",
            "ecosystem": "ts_stdlib",
            "runtime": "node",
            "normalized_name": "node:fs",
            "repository_url": "",
            "url_resolution": {"status": "not-applicable"},
            "centrality": {"metric": "pagerank", "percentage": 20.0, "score": 0.02},
            "evidence_ref": "top_dependencies[1]",
        },
    ]


@pytest.mark.unit
def test_machine_summary_fails_fast_without_required_evidence_keys():
    with pytest.raises(ValueError, match="analysis_result missing required keys: schema_version"):
        build_machine_summary(
            {
                "producer": {},
                "repository": {},
                "created_at": "2026-05-08T12:34:56Z",
                "invocation": {},
                "dependency_graph": {},
                "top_dependencies": [],
                "analyzer_details": {},
            }
        )

    with pytest.raises(ValueError, match=r"analysis_result.top_dependencies\[0\] missing required keys: score"):
        build_machine_summary(
            {
                "schema_version": ANALYSIS_SCHEMA_VERSION,
                "producer": {},
                "repository": {},
                "created_at": "2026-05-08T12:34:56Z",
                "invocation": {"centrality_metric": "pagerank"},
                "dependency_graph": {},
                "top_dependencies": [
                    {
                        "package_name": "zod",
                        "percentage": 100.0,
                        "package_url": "https://github.com/colinhacks/zod",
                        "ecosystem": "npm",
                        "dependency_kind": "package-manager",
                        "runtime": None,
                        "normalized_name": "zod",
                        "url_resolution_status": "resolved",
                    }
                ],
                "analyzer_details": {},
            }
        )


@pytest.mark.unit
def test_machine_summary_dependency_requires_canonical_package_url():
    analysis_result = _valid_summary_analysis_result()
    del analysis_result["top_dependencies"][0]["package_url"]
    analysis_result["top_dependencies"][0]["repository_url"] = "https://github.com/colinhacks/zod"

    with pytest.raises(
        ValueError,
        match=r"analysis_result.top_dependencies\[0\] missing required keys: package_url",
    ):
        build_machine_summary(analysis_result)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value", "expected_message"),
    [
        ("dependency_graph", None, "analysis_result.dependency_graph must be a dict"),
        ("top_dependencies", None, "analysis_result.top_dependencies must be a list"),
        ("analyzer_details", None, "analysis_result.analyzer_details must be a dict"),
    ],
)
def test_machine_summary_rejects_malformed_required_containers(field, value, expected_message):
    analysis_result = copy.deepcopy(_valid_summary_analysis_result())
    analysis_result[field] = value

    with pytest.raises(ValueError, match=expected_message):
        build_machine_summary(analysis_result)


@pytest.mark.unit
def test_machine_summary_rejects_malformed_top_dependency_entries():
    analysis_result = _valid_summary_analysis_result()
    analysis_result["top_dependencies"] = [None]

    with pytest.raises(ValueError, match=r"analysis_result.top_dependencies\[0\] must be a dict"):
        build_machine_summary(analysis_result)
