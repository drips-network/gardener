import pytest

from gardener.analysis.graph import DependencyGraphBuilder
from gardener.common.defaults import ConfigOverride


@pytest.mark.unit
def test_centrality_scores_attached(logger):
    builder = DependencyGraphBuilder(logger)

    # Minimal graph: one file imports one package
    source_files = {"a.py": "/abs/a.py"}
    external_packages = {"pkg": {"ecosystem": "pypi", "import_names": ["pkg"]}}
    file_imports = {"a.py": ["pkg"]}
    file_package_components = {}
    local_imports_map = {}

    builder.build_dependency_graph(
        source_files, external_packages, file_imports, file_package_components, local_imports_map
    )

    with ConfigOverride({"CENTRALITY_METRIC": "pagerank"}, logger=logger):
        scores = builder.calculate_importance()
        assert scores, "Expected non-empty centrality scores"
        assert "pkg" in builder.graph.nodes
        assert "pagerank" in builder.graph.nodes["pkg"]

    with ConfigOverride({"CENTRALITY_METRIC": "katz"}, logger=logger):
        scores2 = builder.calculate_importance()
        assert scores2, "Expected non-empty centrality scores for katz"
        assert "katz" in builder.graph.nodes["pkg"]
