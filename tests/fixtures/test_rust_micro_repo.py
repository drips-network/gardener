"""
Fixture-based Rust micro repo test
"""

import os

import pytest

from gardener.analysis.main import run_analysis
from tests.support.graph_spec import assert_graph_matches_spec, load_graph_spec


# Helper function to find nodes by ID prefix
def find_node_by_prefix(graph_data, prefix):  # Changed 'graph' to 'graph_data' for clarity
    """Find the first node whose ID starts with the given prefix"""
    for node in graph_data.get("nodes", []):  # Iterate list of node dicts
        node_id = node.get("id")
        if node_id and node_id.startswith(prefix):
            return node_id, node  # Return id and node data
    return None, None


# Helper function to find nodes by specific attributes
def find_node_by_attrs(graph_data, **attrs):  # Changed 'graph' to 'graph_data'
    """Find the first node matching the specified attributes"""
    for node in graph_data.get("nodes", []):  # Iterate list of node dicts
        node_id = node.get("id")
        # Ensure node_id exists before using it, though matching is on attrs
        match = all(node.get(key) == value for key, value in attrs.items())
        if match:
            return node_id, node  # Return id and node data (id might be None if not in attrs)
    return None, None


# Helper function to check if an edge exists
def edge_exists(graph, source_prefix, target_prefix, edge_type):
    """Check if an edge exists between nodes matching source/target prefixes"""
    source_id, _ = find_node_by_prefix(graph, source_prefix)
    target_id, _ = find_node_by_prefix(graph, target_prefix)

    if not source_id or not target_id:
        return False

    for edge in graph.get("links", []):  # Changed 'edges' to 'links'
        if edge.get("source") == source_id and edge.get("target") == target_id and edge.get("type") == edge_type:
            return True
    return False


@pytest.mark.integration
def test_rust_fixture_graph_matches_spec(offline_mode):
    """
    Verify end-to-end dependency graph generation for the Rust fixture

    Checks nodes (files, packages, components) and edges (imports, usage)
    """
    # Convert relative path to absolute to avoid path duplication in SecureFileOps
    fixture_repo_path = os.path.abspath("tests/fixtures/rust")
    output_prefix = "test_rust_fixture_output"  # Use a unique prefix for test outputs

    # Ensure the fixture directory exists
    assert os.path.isdir(fixture_repo_path), f"Fixture directory not found: {fixture_repo_path}"

    with offline_mode.set_responses({}):
        results = run_analysis(
            repo_path=fixture_repo_path,
            output_prefix=output_prefix,
            verbose=False,
            minimal_outputs=True,
            focus_languages_str="rust",
            config_overrides=None,
        )

    assert "dependency_graph" in results, "Analysis results should contain 'dependency_graph'"
    graph_data = results["dependency_graph"]

    assert (
        "nodes" in graph_data and "links" in graph_data
    ), "Graph data should have 'nodes' and 'links'"  # Changed 'edges' to 'links'

    nodes = graph_data["nodes"]
    edges = graph_data["links"]

    spec = load_graph_spec("tests/data/specs/rust_micro.yml")
    assert_graph_matches_spec(graph_data, spec, lax=True)
