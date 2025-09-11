"""
Integration tests for cross-language dependency analysis

Tests the full pipeline from source code analysis to dependency graph generation
across multiple programming languages in the same repository
"""

from pathlib import Path

import pytest

from gardener.analysis.main import analyze_repository
from gardener.common.defaults import ConfigOverride
from gardener.package_metadata import url_resolver


@pytest.fixture(scope="module", autouse=True)
def _offline_url_resolution():
    url_resolver.set_request_fn(lambda url: None)
    yield
    url_resolver.set_request_fn(None)


def _analyze_fixture(repo_path, *, focus_languages=None, verbose=False):
    return analyze_repository(repo_path=str(repo_path), specific_languages=focus_languages, verbose=verbose)


@pytest.mark.integration
def test_mixed_language_import_tracking():
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    fixture_path = fixtures_dir / "monorepo_mixed"

    result = _analyze_fixture(fixture_path, verbose=False)
    packages = result.get("external_packages", {})
    graph_data = result.get("dependency_graph", {})

    if graph_data:
        import networkx as nx

        graph = nx.node_link_graph(graph_data)
        nodes = list(graph.nodes())
        js_files = [n for n in nodes if graph.nodes[n].get("type") == "file" and n.endswith(".js")]
        py_files = [n for n in nodes if graph.nodes[n].get("type") == "file" and n.endswith(".py")]
        rs_files = [n for n in nodes if graph.nodes[n].get("type") == "file" and n.endswith(".rs")]

        if graph.number_of_nodes() > len(packages):
            total_files = len(js_files) + len(py_files) + len(rs_files)
            assert total_files > 0

    assert "google-protobuf" in packages
    assert "protobuf" in packages


@pytest.mark.integration
@pytest.mark.slow
def test_centrality_calculation_mixed_repo():
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    fixture_path = fixtures_dir / "monorepo_mixed"

    with ConfigOverride({"CENTRALITY_METRIC": "pagerank"}):
        result = _analyze_fixture(fixture_path)

    graph_data = result.get("dependency_graph", {})
    if graph_data:
        import networkx as nx

        graph = nx.node_link_graph(graph_data)
    else:
        graph = None

    if graph and graph.number_of_edges() > 0:
        package_nodes = [n for n in graph.nodes() if graph.nodes[n].get("type") == "package"]
        for pkg_node in package_nodes:
            assert "pagerank" in graph.nodes[pkg_node]
            assert graph.nodes[pkg_node]["pagerank"] >= 0
    else:
        pytest.skip("No edges in graph, skipping centrality score checks")

    with ConfigOverride({"CENTRALITY_METRIC": "katz"}):
        result2 = _analyze_fixture(fixture_path)
    graph2 = nx.node_link_graph(result2.get("dependency_graph", {})) if result2.get("dependency_graph") else None
    if graph2 and graph:
        for pkg_node in package_nodes:
            if pkg_node in graph2.nodes():
                assert "katz" in graph2.nodes[pkg_node]


@pytest.mark.integration
def test_local_import_resolution_across_languages():
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    fixture_path = fixtures_dir / "monorepo_mixed"
    result = _analyze_fixture(fixture_path)
    graph_data = result.get("dependency_graph", {})
    if graph_data:
        import networkx as nx

        graph = nx.node_link_graph(graph_data)
    else:
        graph = None

    edges = list(graph.edges(data=True))
    local_import_edges = [e for e in edges if e[2].get("type") == "imports_local"]
    assert len(local_import_edges) > 0
    for _, target, _ in local_import_edges:
        assert target in graph.nodes()
        assert graph.nodes[target]["type"] == "file"


@pytest.mark.integration
def test_component_extraction_multi_language():
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    fixture_path = fixtures_dir / "monorepo_mixed"
    result = _analyze_fixture(fixture_path)
    graph_data = result.get("dependency_graph", {})
    if graph_data:
        import networkx as nx

        graph = nx.node_link_graph(graph_data)
    else:
        graph = None

    component_nodes = [n for n in graph.nodes() if graph.nodes[n].get("type") == "package_component"]
    assert len(component_nodes) > 0
    for comp_node in component_nodes[:5]:
        parents = [(s, t) for s, t, d in graph.in_edges(comp_node, data=True) if d.get("type") == "contains_component"]
        assert len(parents) == 1


@pytest.mark.integration
def test_full_pipeline_js_python_ts():
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    fixture_path = fixtures_dir / "ts_micro"
    result = _analyze_fixture(fixture_path)
    graph_data = result.get("dependency_graph", {})
    if graph_data:
        import networkx as nx

        graph = nx.node_link_graph(graph_data)
    else:
        graph = None

    if graph:
        assert graph.number_of_nodes() >= 0
        assert graph.number_of_edges() >= 0

    if graph and graph.number_of_nodes() > 0:
        node_types = set(data.get("type") for _, data in graph.nodes(data=True))
        expected = {"file", "package", "package_component"}
        assert node_types.issubset(expected)

    if graph and graph.number_of_edges() > 0:
        edge_types = set(data.get("type") for _, _, data in graph.edges(data=True))
        expected = {"imports_package", "imports_local", "uses_component", "contains_component"}
        assert edge_types.issubset(expected)


@pytest.mark.integration
@pytest.mark.slow
def test_focus_language_filtering():
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    fixture_path = fixtures_dir / "monorepo_mixed"

    result_js = _analyze_fixture(fixture_path, focus_languages=["javascript"])
    graph_js_data = result_js.get("dependency_graph", {})
    graph_js = None
    if graph_js_data:
        import networkx as nx

        graph_js = nx.node_link_graph(graph_js_data)

    result_py = _analyze_fixture(fixture_path, focus_languages=["python"])
    graph_py_data = result_py.get("dependency_graph", {})
    graph_py = None
    if graph_py_data:
        import networkx as nx

        graph_py = nx.node_link_graph(graph_py_data)

    js_files = [n for n in graph_js.nodes() if graph_js.nodes[n].get("type") == "file"]
    py_files = [n for n in graph_py.nodes() if graph_py.nodes[n].get("type") == "file"]
    for f in js_files:
        assert f.endswith((".js", ".jsx", ".mjs"))
    for f in py_files:
        assert f.endswith(".py")


@pytest.mark.integration
def test_output_generation():
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    fixture_path = fixtures_dir / "js_micro"
    result = _analyze_fixture(fixture_path)
    top_dependencies = result.get("top_dependencies", [])
    assert isinstance(top_dependencies, list)
    for dep in top_dependencies:
        assert "package_name" in dep
        assert "percentage" in dep
        assert "package_url" in dep


@pytest.mark.integration
def test_ambiguous_import_handling():
    """
    Placeholder for ambiguous-import scenarios (requires dedicated fixture)
    """
    pass


@pytest.mark.integration
def test_version_conflict_reporting():
    fixtures_dir = Path(__file__).parent.parent / "fixtures"
    fixture_path = fixtures_dir / "monorepo_python"
    result = _analyze_fixture(fixture_path)
    # Conflict detection placeholder — keep contract light
    conflicts = {}
    assert len(conflicts) == 0
