import json

import pytest

from gardener.analysis.graph import DependencyGraphBuilder
from gardener.analysis.main import DependencyAnalyzer, analyze_repository
from gardener.analysis.manifests import process_manifests
from gardener.analysis.scanner import scan_repository
from gardener.analysis.scopes import ScopeFilter, classify_path_scope, parse_scope_filter
from gardener.analysis.tree import RepositoryAnalyzer
from gardener.common.utils import Logger
from gardener.treewalk.javascript import JavaScriptLanguageHandler
from gardener.treewalk.solidity import SolidityLanguageHandler


class JavaScriptHandler:
    def get_manifest_files(self):
        return ["package.json"]

    def get_file_extensions(self):
        return [".js", ".mjs", ".cjs"]

    def process_manifest(self, file_path, packages_dict, secure_file_ops=None):
        with open(file_path, encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        for name, version in manifest.get("dependencies", {}).items():
            packages_dict[name] = {"version": version, "ecosystem": "npm"}


@pytest.mark.unit
def test_classify_path_scope_uses_conservative_precedence():
    assert classify_path_scope("src/app.js") == "production"
    assert classify_path_scope("tests/fixtures/data.js") == "fixtures"
    assert classify_path_scope("src/app.test.js") == "tests"
    assert classify_path_scope("src/app.spec.cjs") == "tests"
    assert classify_path_scope("src/app.test.mjs") == "tests"
    assert classify_path_scope("examples/demo.js") == "examples"
    assert classify_path_scope("docs/conf.js") == "docs"
    assert classify_path_scope("scripts/build.js") == "scripts"
    assert classify_path_scope("tools/runtime.js") == "production"
    assert classify_path_scope("") == "unknown"


@pytest.mark.unit
def test_parse_scope_filter_metadata_and_invalid_values():
    assert ScopeFilter.all().to_metadata() == {
        "mode": "all",
        "include": None,
        "exclude": [],
        "active": ["production", "tests", "fixtures", "examples", "docs", "scripts", "unknown"],
        "classifier": "path-heuristic-v1",
    }

    scope_filter = parse_scope_filter("production,test", "fixtures")
    assert scope_filter.to_metadata() == {
        "mode": "include-exclude",
        "include": ["production", "tests"],
        "exclude": ["fixtures"],
        "active": ["production", "tests"],
        "classifier": "path-heuristic-v1",
    }

    with pytest.raises(ValueError, match="all cannot be combined"):
        parse_scope_filter("all,tests", None)
    with pytest.raises(ValueError, match="not valid"):
        parse_scope_filter(None, "all")
    with pytest.raises(ValueError, match="empty scope"):
        parse_scope_filter("tests,", None)


@pytest.mark.unit
def test_scope_filter_direct_construction_normalizes_aliases():
    scope_filter = ScopeFilter(include=frozenset({"test"}), exclude=frozenset({"fixture"}))

    assert scope_filter.include == frozenset({"tests"})
    assert scope_filter.exclude == frozenset({"fixtures"})
    assert scope_filter.allows("tests") is True
    assert scope_filter.allows("fixtures") is False


@pytest.mark.unit
def test_scanner_separates_all_and_included_inputs(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "package.json").write_text(json.dumps({"dependencies": {"vitest": "^1.0.0"}}))
    (tmp_path / "src.js").write_text("import React from 'react';")
    (tests_dir / "helper.js").write_text("import { describe } from 'vitest';")

    result = scan_repository(
        str(tmp_path),
        secure_file_ops=None,
        focus_languages=None,
        language_handlers={"javascript": JavaScriptHandler()},
        logger=None,
        scope_filter=parse_scope_filter("production", None),
    )

    assert set(result["all_source_files"]) == {"src.js", "tests/helper.js"}
    assert set(result["source_files"]) == {"src.js"}
    assert len(result["manifest_files"]) == 2
    assert result["included_manifest_files"] == [str(tmp_path / "package.json")]
    assert result["scope_summary"]["source_files"]["all"] == {"production": 1, "tests": 1}
    assert result["scope_summary"]["source_files"]["included"] == {"production": 1}


@pytest.mark.unit
def test_graph_scope_evidence_distinguishes_direct_and_transitive_file_scopes():
    builder = DependencyGraphBuilder()
    graph = builder.build_dependency_graph(
        {
            "src/app.js": {
                "absolute_path": "/repo/src/app.js",
                "language": "javascript",
                "scope": "production",
            },
            "tests/app.test.js": {
                "absolute_path": "/repo/tests/app.test.js",
                "language": "javascript",
                "scope": "tests",
            },
        },
        {
            "zod": {
                "ecosystem": "npm",
                "import_names": ["zod"],
                "manifest_scopes": ["production"],
                "manifest_evidence_scopes": ["production"],
            }
        },
        {"src/app.js": ["zod"]},
        {},
        {"tests/app.test.js": ["src/app.js"]},
    )

    assert graph.nodes["src/app.js"]["scope"] == "production"
    assert graph.edges["src/app.js", "zod"]["scope"] == "production"
    assert graph.edges["tests/app.test.js", "src/app.js"]["scope"] == "tests"
    assert builder.get_dependency_scope_evidence("zod") == {
        "direct_imports": ["production"],
        "transitive_files": ["production", "tests"],
        "manifests": ["production"],
    }


@pytest.mark.unit
def test_graph_excludes_inactive_manifest_only_packages_until_imported():
    builder = DependencyGraphBuilder()
    graph = builder.build_dependency_graph(
        {
            "tests/app.test.js": {
                "absolute_path": "/repo/tests/app.test.js",
                "language": "javascript",
                "scope": "tests",
            }
        },
        {
            "react": {
                "ecosystem": "npm",
                "import_names": ["react"],
                "manifest_scopes": ["production"],
                "manifest_evidence_scopes": [],
            },
            "vitest": {
                "ecosystem": "npm",
                "import_names": ["vitest"],
                "manifest_scopes": ["tests"],
                "manifest_evidence_scopes": ["tests"],
            },
            "unused": {
                "ecosystem": "npm",
                "import_names": ["unused"],
                "manifest_scopes": ["production"],
                "manifest_evidence_scopes": [],
            },
        },
        {"tests/app.test.js": ["react"]},
        {},
        {},
    )

    assert "vitest" in graph.nodes
    assert "react" in graph.nodes
    assert "unused" not in graph.nodes
    assert graph.edges["tests/app.test.js", "react"]["scope"] == "tests"


@pytest.mark.unit
def test_manifest_catalog_tracks_all_manifests_and_active_evidence(tmp_path):
    root_manifest = tmp_path / "package.json"
    root_manifest.write_text(json.dumps({"dependencies": {"react": "^18.0.0", "shared": "^1.0.0"}}))
    fixtures_dir = tmp_path / "tests" / "fixtures"
    fixtures_dir.mkdir(parents=True)
    fixture_manifest = fixtures_dir / "package.json"
    fixture_manifest.write_text(json.dumps({"dependencies": {"vitest": "^1.0.0", "shared": "^2.0.0"}}))

    result = scan_repository(
        str(tmp_path),
        secure_file_ops=None,
        focus_languages=None,
        language_handlers={"javascript": JavaScriptHandler()},
        logger=None,
        scope_filter=parse_scope_filter("fixtures", None),
    )
    packages = process_manifests(
        result["manifest_files"],
        {"javascript": JavaScriptHandler()},
        None,
        None,
        repo_path=str(tmp_path),
        included_manifest_files=result["included_manifest_files"],
        manifest_scope_by_path=result["manifest_scope_by_path"],
    )

    assert result["root_manifest_files"] == [str(root_manifest)]
    assert result["included_root_manifest_files"] == []
    assert set(packages) == {"react", "shared", "vitest"}
    assert packages["react"]["manifest_scopes"] == ["production"]
    assert packages["react"]["manifest_evidence_scopes"] == []
    assert packages["vitest"]["manifest_scopes"] == ["fixtures"]
    assert packages["vitest"]["manifest_evidence_scopes"] == ["fixtures"]
    assert packages["shared"]["manifest_scopes"] == ["production", "fixtures"]
    assert packages["shared"]["manifest_evidence_scopes"] == ["fixtures"]
    assert [evidence["included"] for evidence in packages["shared"]["manifest_evidence"]] == [False, True]


@pytest.mark.unit
def test_manifest_evidence_deduplicates_identical_handler_occurrences(tmp_path):
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    occurrence = {str(manifest): "production"}

    packages = process_manifests(
        [str(manifest)],
        {"javascript": JavaScriptHandler(), "typescript": JavaScriptHandler()},
        None,
        None,
        repo_path=str(tmp_path),
        included_manifest_files=[str(manifest)],
        manifest_scope_by_path=occurrence,
    )

    assert packages["react"]["found_in_manifests"] == [str(manifest)]
    assert packages["react"]["manifest_evidence"] == [
        {"path": "package.json", "scope": "production", "included": True}
    ]


@pytest.mark.unit
def test_manifest_scope_metadata_invariant_failures_are_not_swallowed(tmp_path):
    manifest = tmp_path / "package.json"
    manifest.write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))

    with pytest.raises(KeyError):
        process_manifests(
            [str(manifest)],
            {"javascript": JavaScriptHandler()},
            None,
            None,
            repo_path=str(tmp_path),
            included_manifest_files=[str(manifest)],
            manifest_scope_by_path={},
        )


@pytest.mark.unit
def test_repository_analyzer_records_excluded_local_imports_without_graphing_them(tmp_path):
    root_manifest = tmp_path / "package.json"
    root_manifest.write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    src_dir = tmp_path / "src"
    tests_dir = tmp_path / "tests"
    src_dir.mkdir()
    tests_dir.mkdir()
    app_file = src_dir / "app.js"
    helper_file = tests_dir / "helper.js"
    app_file.write_text("import '../tests/helper.js';\nimport React from 'react';\nconsole.log(React);\n")
    helper_file.write_text("export const helper = 1;\n")

    analyzer = RepositoryAnalyzer(str(tmp_path), logger=None, scope_filter=parse_scope_filter("production", None))
    analyzer.register_language_handler("javascript", JavaScriptLanguageHandler())
    analyzer.scan_repo()
    analyzer.process_manifest_files()
    analyzer.extract_imports_from_all_files()

    assert analyzer.file_imports["src/app.js"] == ["react"]
    assert dict(analyzer.local_imports_map) == {}
    assert dict(analyzer.excluded_local_imports_map) == {"src/app.js": ["tests/helper.js"]}

    graph = DependencyGraphBuilder().build_dependency_graph(
        analyzer.source_files,
        analyzer.external_packages,
        analyzer.file_imports,
        analyzer.file_package_components,
        analyzer.local_imports_map,
    )
    assert "src/app.js" in graph.nodes
    assert "tests/helper.js" not in graph.nodes
    assert "react" in graph.nodes


@pytest.mark.unit
def test_default_scope_filter_preserves_graph_and_dependency_scores(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    tests_dir = tmp_path / "tests"
    fixtures_dir = tests_dir / "fixtures"
    tests_dir.mkdir()
    fixtures_dir.mkdir()
    (fixtures_dir / "package.json").write_text(json.dumps({"dependencies": {"fixture-only": "^1.0.0"}}))
    (tmp_path / "app.js").write_text("import React from 'react';\nconsole.log(React);\n")
    (tests_dir / "app.test.js").write_text("import { describe } from 'vitest';\ndescribe('app', () => {});\n")

    implicit = _analyze_without_url_resolution(tmp_path, None)
    explicit = _analyze_without_url_resolution(tmp_path, ScopeFilter.all())

    assert _graph_signature(implicit["dependency_graph"]) == _graph_signature(explicit["dependency_graph"])
    assert _dependency_signature(implicit["top_dependencies"]) == _dependency_signature(explicit["top_dependencies"])
    node_ids = {node["id"] for node in implicit["dependency_graph"]["nodes"]}
    assert "tests/app.test.js" in node_ids
    assert "fixture-only" in node_ids


@pytest.mark.unit
def test_programmatic_scoped_analysis_records_actual_invocation_scope(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    (tmp_path / "app.js").write_text("import React from 'react';\n")
    monkeypatch.setattr(DependencyAnalyzer, "_resolve_repository_urls", lambda self, packages, url_cache=None: packages)

    results = analyze_repository(
        str(tmp_path),
        specific_languages=["javascript"],
        scope_filter=parse_scope_filter("production", None),
        invocation_metadata={"entrypoint": "test"},
    )

    assert results["invocation"]["scope"]["mode"] == "include"
    assert results["invocation"]["scope"]["active"] == ["production"]


@pytest.mark.unit
def test_programmatic_scoped_analysis_replaces_empty_invocation_scope(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    (tmp_path / "app.js").write_text("import React from 'react';\n")
    monkeypatch.setattr(DependencyAnalyzer, "_resolve_repository_urls", lambda self, packages, url_cache=None: packages)

    results = analyze_repository(
        str(tmp_path),
        specific_languages=["javascript"],
        scope_filter=parse_scope_filter("production", None),
        invocation_metadata={"entrypoint": "test", "scope": None},
    )

    assert results["invocation"]["scope"]["mode"] == "include"
    assert results["invocation"]["scope"]["active"] == ["production"]


@pytest.mark.unit
def test_direct_analyze_dependencies_records_actual_invocation_scope(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    (tmp_path / "app.js").write_text("import React from 'react';\n")

    analyzer = DependencyAnalyzer(scope_filter=parse_scope_filter("production", None))
    external_packages = analyzer.discover_packages(str(tmp_path), ["javascript"])
    results = analyzer.analyze_dependencies(external_packages, invocation_metadata={"entrypoint": "test"})

    assert results["invocation"]["scope"]["mode"] == "include"
    assert results["invocation"]["scope"]["active"] == ["production"]


@pytest.mark.unit
def test_explicit_invocation_scope_is_preserved(tmp_path, monkeypatch):
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18.0.0"}}))
    (tmp_path / "app.js").write_text("import React from 'react';\n")
    monkeypatch.setattr(DependencyAnalyzer, "_resolve_repository_urls", lambda self, packages, url_cache=None: packages)

    results = analyze_repository(
        str(tmp_path),
        specific_languages=["javascript"],
        scope_filter=parse_scope_filter("production", None),
        invocation_metadata={
            "entrypoint": "test",
            "scope": ScopeFilter.all().to_metadata(),
        },
    )

    assert results["invocation"]["scope"]["mode"] == "all"
    assert results["invocation"]["scope"]["active"] == ScopeFilter.all().to_metadata()["active"]


@pytest.mark.unit
def test_solidity_remapping_candidates_emit_scope_evidence_and_obey_filtered_graph(tmp_path):
    (tmp_path / "remappings.txt").write_text("forge-std/=lib/forge-std/src/\n")
    test_dir = tmp_path / "tests"
    test_dir.mkdir()
    (test_dir / "Empty.t.sol").write_text("contract Empty {}\n")

    analyzer = RepositoryAnalyzer(str(tmp_path), logger=None, scope_filter=parse_scope_filter("tests", None))
    analyzer.register_language_handler("solidity", SolidityLanguageHandler())
    analyzer.scan_repo()
    packages = analyzer.process_manifest_files()

    assert packages["forge-std"]["manifest_evidence"] == [
        {"path": "remappings.txt", "scope": "production", "included": False}
    ]
    assert packages["forge-std"]["manifest_scopes"] == ["production"]
    assert packages["forge-std"]["manifest_evidence_scopes"] == []

    graph = DependencyGraphBuilder().build_dependency_graph(
        analyzer.source_files,
        analyzer.external_packages,
        {},
        {},
        {},
    )
    assert "tests/Empty.t.sol" in graph.nodes
    assert "forge-std" not in graph.nodes


@pytest.mark.unit
def test_solidity_remapping_existing_package_without_source_does_not_crash(tmp_path):
    analyzer = RepositoryAnalyzer(str(tmp_path), logger=Logger(verbose=False), scope_filter=ScopeFilter.all())
    analyzer.external_packages = {"hardhat": {"ecosystem": "npm", "import_names": ["hardhat"]}}

    analyzer._solidity_candidates_from_remappings(
        {"hardhat/": "node_modules/hardhat/"},
        "hardhat config",
        SolidityLanguageHandler(),
    )

    assert analyzer.external_packages["hardhat"]["manifest_evidence"] == [
        {"path": "hardhat.config.js", "scope": "production", "included": True}
    ]
    assert analyzer.external_packages["hardhat"]["manifest_scopes"] == ["production"]
    assert analyzer.external_packages["hardhat"]["manifest_evidence_scopes"] == ["production"]


def _analyze_without_url_resolution(repo_path, scope_filter):
    analyzer = DependencyAnalyzer(scope_filter=scope_filter)
    external_packages = analyzer.discover_packages(str(repo_path), ["javascript"])
    return analyzer.analyze_dependencies(external_packages, invocation_metadata={"entrypoint": "test"})


def _graph_signature(graph_data):
    nodes = sorted(node["id"] for node in graph_data["nodes"])
    edges = sorted((edge["source"], edge["target"], edge["type"]) for edge in graph_data["links"])
    return nodes, edges


def _dependency_signature(top_dependencies):
    return [
        (
            dependency["package_name"],
            dependency["score"],
            dependency["percentage"],
        )
        for dependency in top_dependencies
    ]
