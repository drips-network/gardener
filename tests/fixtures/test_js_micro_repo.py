"""
Fixture-based JS micro repo test
"""

import os

import pytest

from gardener.analysis.main import run_analysis
from tests.support.graph_spec import assert_graph_matches_spec, load_graph_spec


@pytest.mark.integration
def test_javascript_fixture_graph_matches_spec(offline_mode):
    """
    Verify end-to-end dependency graph generation for the JavaScript fixture

    Checks for expected nodes (files, packages, components) and edges
    (imports_local/requires_local, imports_package, uses_component, contains_component)
    based on the known structure of the tests/fixtures/javascript directory
    """
    # Convert relative path to absolute to avoid path duplication in SecureFileOps
    fixture_repo_path = os.path.abspath("tests/fixtures/javascript")
    assert os.path.isdir(fixture_repo_path), f"Fixture directory not found: {fixture_repo_path}"

    with offline_mode.set_responses({}):
        results = run_analysis(
            repo_path=fixture_repo_path,
            output_prefix="test_js_fixture_output",
            verbose=False,
            minimal_outputs=True,
            focus_languages_str="javascript",
            config_overrides=None,
        )

    assert "dependency_graph" in results, "Dependency graph missing from analysis results"
    graph_data = results["dependency_graph"]

    spec = load_graph_spec("tests/data/specs/javascript_micro.yml")
    assert_graph_matches_spec(graph_data, spec, lax=True)
