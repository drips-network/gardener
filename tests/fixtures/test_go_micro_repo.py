"""
Fixture-based Go micro repo test
"""

import os

import pytest

from gardener.analysis.main import run_analysis
from tests.support.graph_spec import assert_graph_matches_spec, load_graph_spec


# Helper function to find nodes by specific ID
def find_node_by_id(graph_data, node_id):
    """Find a node by its exact ID"""
    for node in graph_data.get("nodes", []):
        if node.get("id") == node_id:
            return node
    return None


# Helper function to find edges
def find_edge(graph_data, source_prefix, target_prefix, edge_type):
    """Find an edge based on source/target ID prefixes and type"""
    for edge in graph_data.get("links", []):  # Changed 'edges' to 'links'
        source_node = find_node_by_id(graph_data, edge.get("source"))
        target_node = find_node_by_id(graph_data, edge.get("target"))
        if (
            source_node
            and target_node
            and source_node["id"].startswith(source_prefix)
            and target_node["id"].startswith(target_prefix)
            and edge.get("type") == edge_type
        ):
            return edge
    return None


@pytest.mark.integration
def test_go_fixture_graph_matches_spec(tmp_path, offline_mode):
    """
    Verify end-to-end dependency graph generation for the Go fixture

    Checks for expected file nodes, package nodes, and import edges
    """
    # Convert relative path to absolute to avoid path duplication in SecureFileOps
    fixture_repo_path = os.path.abspath("tests/fixtures/go")
    output_prefix = os.path.join(str(tmp_path), "test_go_fixture_output")

    # Ensure the fixture directory exists
    assert os.path.isdir(fixture_repo_path), f"Fixture directory not found: {fixture_repo_path}"

    with offline_mode.set_responses({}):
        results = run_analysis(
            repo_path=fixture_repo_path,
            output_prefix=output_prefix,
            verbose=False,
            minimal_outputs=True,
            focus_languages_str="go",
            config_overrides=None,
        )

    graph_data = results.get("dependency_graph", {})
    spec = load_graph_spec("tests/data/specs/go_micro.yml")
    assert_graph_matches_spec(graph_data, spec, lax=True)
