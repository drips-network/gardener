"""
Pure evidence-layer contracts for analysis results and machine summaries
"""

import hashlib
import json
import os
import platform
import sys
from datetime import UTC, datetime
from importlib import metadata
from urllib.parse import urlsplit, urlunsplit

from gardener.common.defaults import GraphAnalysisConfig

ANALYSIS_SCHEMA_VERSION = "gardener.analysis.v1"
MACHINE_SUMMARY_SCHEMA_VERSION = "gardener.machine_summary.v1"

DEPENDENCY_KIND_PACKAGE_MANAGER = "package-manager"
DEPENDENCY_KIND_BUILTIN = "builtin"
DEPENDENCY_KIND_LOCAL = "local"
DEPENDENCY_KIND_UNKNOWN = "unknown"

URL_RESOLUTION_RESOLVED = "resolved"
URL_RESOLUTION_UNRESOLVED = "unresolved"
URL_RESOLUTION_NOT_APPLICABLE = "not-applicable"

_INVOCATION_KEYS = (
    "entrypoint",
    "languages",
    "centrality_metric",
    "minimal_outputs",
    "visualize",
    "machine_summary",
    "config_overrides",
)

_NODE_CORE_MODULES = frozenset(
    {
        "assert",
        "async_hooks",
        "buffer",
        "child_process",
        "cluster",
        "console",
        "constants",
        "crypto",
        "dgram",
        "diagnostics_channel",
        "dns",
        "domain",
        "events",
        "fs",
        "http",
        "http2",
        "https",
        "inspector",
        "module",
        "net",
        "os",
        "path",
        "perf_hooks",
        "process",
        "punycode",
        "querystring",
        "readline",
        "repl",
        "stream",
        "string_decoder",
        "sys",
        "test",
        "timers",
        "tls",
        "trace_events",
        "tty",
        "url",
        "util",
        "v8",
        "vm",
        "wasi",
        "worker_threads",
        "zlib",
    }
)

_RUST_BUILTIN_CRATES = frozenset({"alloc", "core", "std", "test"})


def build_producer_metadata(git_commit: str | None = None) -> dict:
    """
    Build metadata identifying the Gardener producer process

    Args:
        git_commit (str | None): Explicit Gardener source commit identifier

    Returns:
        Producer metadata dictionary
    """
    try:
        version = metadata.version("gardener")
    except metadata.PackageNotFoundError:
        version = "unknown"

    return {
        "name": "gardener",
        "version": version,
        "git_commit": git_commit if git_commit is not None else os.environ.get("GARDENER_GIT_COMMIT"),
        "python": platform.python_version(),
    }


def complete_invocation_metadata(invocation_metadata: dict | None) -> dict:
    """
    Complete invocation metadata with stable evidence-layer keys

    Args:
        invocation_metadata (dict | None): Partial invocation metadata from a caller

    Returns:
        Complete invocation metadata dictionary
    """
    invocation = dict(invocation_metadata or {})
    complete = {key: invocation.get(key) for key in _INVOCATION_KEYS}
    complete["centrality_metric"] = (
        invocation.get("centrality_metric") or GraphAnalysisConfig.CENTRALITY_METRIC.lower()
    )
    complete["config_overrides"] = dict(invocation.get("config_overrides") or {})
    return complete


def build_repository_metadata(
    *,
    input_value: str | None,
    resolved_path: str | None = None,
    canonical_url: str | None = None,
    commit_sha: str | None = None,
) -> dict:
    """
    Build metadata identifying the analyzed repository input

    Args:
        input_value (str | None): Original caller-provided repository value
        resolved_path (str | None): Local resolved path when appropriate for the entrypoint
        canonical_url (str | None): Canonical remote repository URL
        commit_sha (str | None): Analyzed repository commit

    Returns:
        Repository metadata dictionary
    """
    return {
        "input": _sanitize_repository_input(input_value),
        "resolved_path": resolved_path,
        "canonical_url": canonical_url,
        "commit_sha": commit_sha,
    }


def _sanitize_repository_input(input_value: str | None) -> str | None:
    """
    Strip URL credentials before repository provenance is persisted
    """
    if input_value is None:
        return None

    value = str(input_value)
    parsed = urlsplit(value)
    if parsed.scheme and parsed.hostname:
        netloc = parsed.hostname
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    return value


def classify_dependency_fact(
    name: str,
    *,
    ecosystem: str | None,
    language: str | None = None,
    is_package_manager: bool = False,
    is_local: bool = False,
    repository_url: str | None = None,
) -> dict:
    """
    Classify a dependency fact without changing analyzer-owned fields

    Args:
        name (str): Dependency distribution or import name
        ecosystem (str | None): Existing analyzer ecosystem label
        language (str | None): Source language for unmanaged imports
        is_package_manager (bool): Whether the fact came from a package manager manifest
        is_local (bool): Whether the fact identifies a local dependency
        repository_url (str | None): Resolved package repository URL, if any

    Returns:
        Additive dependency evidence fields
    """
    if is_local:
        return _classification(DEPENDENCY_KIND_LOCAL, name, URL_RESOLUTION_NOT_APPLICABLE)

    if is_package_manager:
        status = URL_RESOLUTION_RESOLVED if repository_url else URL_RESOLUTION_UNRESOLVED
        return _classification(DEPENDENCY_KIND_PACKAGE_MANAGER, name, status)

    language_key = (language or "").lower()
    ecosystem_key = (ecosystem or "").lower()

    if _is_javascript_like(language_key, ecosystem_key):
        node_name = _normalize_node_builtin(name)
        if node_name:
            return _classification(DEPENDENCY_KIND_BUILTIN, node_name, URL_RESOLUTION_NOT_APPLICABLE, "node")

    if _is_python_like(language_key, ecosystem_key):
        python_name = _normalize_python_builtin(name)
        if python_name:
            return _classification(DEPENDENCY_KIND_BUILTIN, python_name, URL_RESOLUTION_NOT_APPLICABLE, "python")

    if _is_go_like(language_key, ecosystem_key) and _is_go_builtin(name):
        return _classification(DEPENDENCY_KIND_BUILTIN, name, URL_RESOLUTION_NOT_APPLICABLE, "go")

    if _is_rust_like(language_key, ecosystem_key):
        rust_name = _normalize_rust_builtin(name)
        if rust_name:
            return _classification(DEPENDENCY_KIND_BUILTIN, rust_name, URL_RESOLUTION_NOT_APPLICABLE, "rust")

    return _classification(DEPENDENCY_KIND_UNKNOWN, name, URL_RESOLUTION_NOT_APPLICABLE)


def enrich_external_packages(external_packages: dict) -> dict:
    """
    Add evidence classification metadata to manifest-derived packages

    Args:
        external_packages (dict): Package metadata keyed by distribution name

    Returns:
        Shallow-enriched copy of external package metadata
    """
    packages = _require_container(external_packages, dict, "external_packages")
    enriched = {}
    for package_name, package_data in packages.items():
        package_info = dict(_require_container(package_data, dict, f"external_packages[{package_name}]"))
        package_info.update(
            classify_dependency_fact(
                package_name,
                ecosystem=package_info.get("ecosystem"),
                is_package_manager=True,
                repository_url=package_info.get("repository_url"),
            )
        )
        enriched[package_name] = package_info
    return enriched


def graph_digest(graph_data: dict) -> str:
    """
    Build a deterministic digest for graph data independent of list or dict ordering

    Args:
        graph_data (dict): Node-link graph data

    Returns:
        sha256-prefixed graph digest
    """
    normalized = dict(graph_data or {})
    normalized["nodes"] = sorted(
        list(normalized.get("nodes", [])),
        key=lambda node: (str(node.get("type", "")), str(node.get("id", "")), _canonical_json(node)),
    )
    normalized["links"] = sorted(
        list(normalized.get("links", [])),
        key=lambda edge: (
            str(edge.get("type", "")),
            str(edge.get("source", "")),
            str(edge.get("target", "")),
            str(edge.get("ident", "")),
            _canonical_json(edge),
        ),
    )
    canonical = _canonical_json(normalized)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def enrich_analysis_result(
    result: dict,
    *,
    repository_metadata: dict | None,
    invocation_metadata: dict | None,
    created_at: str | None = None,
) -> dict:
    """
    Add top-level evidence metadata while preserving existing analysis keys

    Args:
        result (dict): Existing analysis result
        repository_metadata (dict | None): Repository provenance metadata
        invocation_metadata (dict | None): Invocation provenance metadata
        created_at (str | None): Explicit creation timestamp

    Returns:
        Enriched analysis result copy
    """
    enriched = dict(_require_container(result, dict, "result"))
    enriched["schema_version"] = ANALYSIS_SCHEMA_VERSION
    enriched["producer"] = build_producer_metadata()
    enriched["repository"] = dict(repository_metadata or build_repository_metadata(input_value=None))
    enriched["invocation"] = complete_invocation_metadata(invocation_metadata)
    enriched["created_at"] = created_at or _utc_now_isoformat()
    enriched["external_packages"] = enrich_external_packages(enriched.get("external_packages", {}))
    return enriched


def build_machine_summary(analysis_result: dict) -> dict:
    """
    Project an enriched analysis result into the compact machine summary schema

    Args:
        analysis_result (dict): Evidence-enriched full analysis result

    Returns:
        Machine summary dictionary

    Raises:
        ValueError: If required evidence-layer keys are absent
    """
    _require_keys(
        analysis_result,
        (
            "schema_version",
            "producer",
            "repository",
            "created_at",
            "invocation",
            "dependency_graph",
            "top_dependencies",
            "analyzer_details",
        ),
        "analysis_result",
    )
    if analysis_result["schema_version"] != ANALYSIS_SCHEMA_VERSION:
        raise ValueError(f"analysis_result.schema_version must be {ANALYSIS_SCHEMA_VERSION}")

    producer = _require_container(analysis_result["producer"], dict, "analysis_result.producer")
    repository = _require_container(analysis_result["repository"], dict, "analysis_result.repository")
    invocation = _require_container(analysis_result["invocation"], dict, "analysis_result.invocation")
    graph_data = _require_container(analysis_result["dependency_graph"], dict, "analysis_result.dependency_graph")
    top_dependencies = _require_container(analysis_result["top_dependencies"], list, "analysis_result.top_dependencies")
    analyzer_details = _require_container(analysis_result["analyzer_details"], dict, "analysis_result.analyzer_details")
    centrality_metric = invocation.get("centrality_metric")
    if centrality_metric is None:
        raise ValueError("analysis_result.invocation.centrality_metric is required")

    return {
        "schema_version": MACHINE_SUMMARY_SCHEMA_VERSION,
        "producer": producer,
        "repository": repository,
        "created_at": analysis_result["created_at"],
        "invocation": invocation,
        "analysis": {
            "languages_detected": sorted(str(language) for language in analyzer_details.get("languages_detected", [])),
            "total_files": analyzer_details.get("total_files", 0),
            "centrality_metric": centrality_metric,
            "graph": {
                "nodes": len(graph_data.get("nodes", [])),
                "links": len(graph_data.get("links", [])),
                "digest": graph_digest(graph_data),
            },
        },
        "dependencies": [
            _project_summary_dependency(dependency, index, centrality_metric)
            for index, dependency in enumerate(top_dependencies)
        ],
    }


def _classification(kind: str, normalized_name: str, url_resolution_status: str, runtime: str | None = None) -> dict:
    return {
        "dependency_kind": kind,
        "runtime": runtime,
        "normalized_name": normalized_name,
        "url_resolution_status": url_resolution_status,
    }


def _is_javascript_like(language: str, ecosystem: str) -> bool:
    return language in {"javascript", "typescript"} or ecosystem in {"js_stdlib", "ts_stdlib"}


def _is_python_like(language: str, ecosystem: str) -> bool:
    return language == "python" or ecosystem == "python_stdlib"


def _is_go_like(language: str, ecosystem: str) -> bool:
    return language == "go" or ecosystem == "go_stdlib"


def _is_rust_like(language: str, ecosystem: str) -> bool:
    return language == "rust" or ecosystem == "rust_stdlib"


def _normalize_node_builtin(name: str) -> str | None:
    raw_name = str(name)
    without_prefix = raw_name.removeprefix("node:")
    module_name = without_prefix.split("/", 1)[0]
    if module_name in _NODE_CORE_MODULES:
        return f"node:{without_prefix}"
    return None


def _normalize_python_builtin(name: str) -> str | None:
    module_name = str(name).split(".", 1)[0]
    if module_name in sys.stdlib_module_names:
        return module_name
    return None


def _is_go_builtin(name: str) -> bool:
    first_segment = str(name).split("/", 1)[0]
    return "." not in first_segment


def _normalize_rust_builtin(name: str) -> str | None:
    crate_name = str(name).split("::", 1)[0]
    if crate_name in _RUST_BUILTIN_CRATES:
        return crate_name
    return None


def _utc_now_isoformat() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _require_keys(data: dict, keys: tuple[str, ...], context: str) -> None:
    missing_keys = [key for key in keys if key not in data]
    if missing_keys:
        joined_keys = ", ".join(missing_keys)
        raise ValueError(f"{context} missing required keys: {joined_keys}")


def _require_container(value: object, expected_type: type, context: str):
    if not isinstance(value, expected_type):
        type_name = expected_type.__name__
        raise ValueError(f"{context} must be a {type_name}")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _project_summary_dependency(dependency: dict, index: int, centrality_metric: str) -> dict:
    context = f"analysis_result.top_dependencies[{index}]"
    dependency = _require_container(dependency, dict, context)
    _require_keys(
        dependency,
        (
            "package_name",
            "percentage",
            "score",
            "ecosystem",
            "package_url",
            "dependency_kind",
            "runtime",
            "normalized_name",
            "url_resolution_status",
        ),
        context,
    )
    return {
        "name": dependency["package_name"],
        "kind": dependency["dependency_kind"],
        "ecosystem": dependency["ecosystem"],
        "runtime": dependency["runtime"],
        "normalized_name": dependency["normalized_name"],
        "repository_url": dependency["package_url"],
        "url_resolution": {"status": dependency["url_resolution_status"]},
        "centrality": {
            "metric": centrality_metric,
            "percentage": dependency["percentage"],
            "score": dependency["score"],
        },
        "evidence_ref": f"top_dependencies[{index}]",
    }
