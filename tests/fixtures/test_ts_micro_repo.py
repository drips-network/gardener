"""
Fixture-based TS micro repo test
"""

import os

import pytest

from gardener.analysis.main import run_analysis
from tests.support.graph_spec import assert_graph_matches_spec, load_graph_spec


# Helper function to find nodes by attributes
def find_node_by_attrs(nodes_list, attrs_to_match):
    """Helper to find a node from a list of node-attribute-dictionaries"""
    for node_data in nodes_list:
        match = True
        for key, value in attrs_to_match.items():
            if node_data.get(key) != value:
                match = False
                break
        if match:
            # Return the node's ID and the node data itself
            return node_data.get("id"), node_data
    return None, None


# Helper function to find edges
def find_edge(edges, source_id, target_id, edge_type):
    """Helper to find an edge by source, target, and type"""
    for edge in edges:
        s = edge.get("source")
        t = edge.get("target")
        et = edge.get("type")

        if s == source_id and t == target_id and et == edge_type:
            return edge
    return None


# Helper function to get actual_id from stored expected_nodes list
def get_actual_id(logical_id, node_list):
    for item in node_list:
        if item["id"] == logical_id:
            return item.get("actual_id", logical_id)
    return logical_id  # Fallback if not found (should not happen if nodes were asserted)


@pytest.mark.integration
def test_typescript_fixture_graph_matches_spec(offline_mode):
    """
    Tests the end-to-end dependency graph generation for the TypeScript fixture

    Verifies nodes (files, packages, components) and edges (imports, uses, contains)
    are correctly identified
    """
    # Convert relative path to absolute to avoid path duplication in SecureFileOps
    fixture_repo_path = os.path.abspath("tests/fixtures/typescript")

    with offline_mode.set_responses({}):
        results = run_analysis(
            repo_path=fixture_repo_path,
            output_prefix="test_ts_fixture_output",
            verbose=False,
            minimal_outputs=True,
            focus_languages_str="typescript,tsx",
            config_overrides=None,
        )

    graph_data = results.get("dependency_graph", {})
    spec = load_graph_spec("tests/data/specs/typescript_micro.yml")
    assert_graph_matches_spec(graph_data, spec, lax=True)
