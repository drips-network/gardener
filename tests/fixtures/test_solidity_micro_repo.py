"""
Fixture-based Solidity micro repo test
"""

import os

import pytest

from gardener.analysis.main import run_analysis
from tests.support.graph_spec import assert_graph_matches_spec, load_graph_spec

# Convert relative path to absolute to avoid path duplication in SecureFileOps
FIXTURE_REPO_PATH = os.path.abspath("tests/fixtures/solidity")


@pytest.mark.integration
def test_solidity_fixture_graph_matches_spec(offline_mode):
    """
    Test end-to-end dependency graph generation for the Solidity fixture

    Verifies nodes (files, packages, components) and edges (imports_local,
    imports_package, uses_component, contains_component) based on the
    known structure and imports within the tests/fixtures/solidity directory,
    including handling of remappings
    """
    with offline_mode.set_responses({}):
        results = run_analysis(
            repo_path=FIXTURE_REPO_PATH,
            output_prefix="test_solidity_fixture_output",
            verbose=False,
            minimal_outputs=True,
            focus_languages_str="solidity",
            config_overrides=None,
        )

    graph_data = results.get("dependency_graph", {})
    spec = load_graph_spec("tests/data/specs/solidity_micro.yml")
    assert_graph_matches_spec(graph_data, spec, lax=True)
