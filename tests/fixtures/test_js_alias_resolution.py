"""
Fixture-based JS alias resolution test
"""

import os

import pytest

from gardener.analysis.main import run_analysis


@pytest.mark.integration
def test_internal_path_alias_resolution():
    """
    Verify internal path alias resolution for JavaScript/TypeScript

    Checks that:
    - Aliased imports are correctly resolved to their actual file paths
    - Resolved paths appear in the local_imports_map
    - The dependency graph shows correct 'file' nodes and 'imports_local' edges
    - Pseudo-packages from aliases do not appear as 'package' nodes
    """
    # Convert relative path to absolute to avoid path duplication in SecureFileOps
    fixture_repo_path = os.path.abspath("tests/fixtures/javascript_aliases/internal_paths")
    assert os.path.isdir(fixture_repo_path), f"Fixture directory not found: {fixture_repo_path}"

    results = run_analysis(
        repo_path=fixture_repo_path,
        output_prefix="test_js_internal_alias_output",
        verbose=False,  # Keep false unless debugging
        minimal_outputs=True,
        focus_languages_str="javascript,typescript",  # Cover both JS and TS
        config_overrides=None,
    )

    assert "dependency_graph" in results, "Dependency graph missing from analysis results"
    graph_data = results["dependency_graph"]
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("links", [])

    assert "analyzer_details" in results, "Analyzer details missing from analysis results"
    analyzer_details = results["analyzer_details"]
    local_imports_map = analyzer_details.get("local_imports_map", {})

    # --- Assertions for local_imports_map ---
    # src/main.js imports from @components/Button and $utils/formatter
    # Keys in local_imports_map are relative to the repo_path of the analyzer
    main_js_rel_path = "src/main.js"

    # The values in local_imports_map are sets of resolved relative paths (also relative to repo_path)
    expected_main_js_imports = {"src/components/Button.js", "src/utils/common/formatter.js"}

    assert (
        main_js_rel_path in local_imports_map
    ), f"'{main_js_rel_path}' not found in local_imports_map keys: {list(local_imports_map.keys())}"

    # Convert actual resolved paths (which might be absolute from resolver) to relative for comparison
    # However, RepositoryAnalyzer.local_imports_map stores resolved paths as relative to its own repo_path
    actual_main_js_imports = set(local_imports_map[main_js_rel_path])
    assert actual_main_js_imports == expected_main_js_imports, (
        f"Mismatch in resolved local imports for '{main_js_rel_path}'.\n"
        f"Expected: {expected_main_js_imports}\n"
        f"Found: {actual_main_js_imports}"
    )

    # --- Node Assertions ---
    expected_files = {"src/main.js", "src/components/Button.js", "src/utils/common/formatter.js"}
    actual_files = {n["id"] for n in nodes if n.get("type") == "file"}

    assert actual_files == expected_files, f"Mismatch in file nodes. Expected: {expected_files}, Found: {actual_files}"

    for node_id in expected_files:
        node = next((n for n in nodes if n["id"] == node_id), None)
        assert node is not None, f"Node '{node_id}' not found"
        assert node.get("type") == "file", f"Node '{node_id}' should be type 'file'"
        # Language can be javascript or typescript, so not asserting specific one here
        # as long as it's processed

    # Assert that pseudo-packages like '@components' or '$utils' do NOT appear as package nodes
    pseudo_packages = {"@components", "$utils"}
    for node in nodes:
        if node.get("type") == "package":
            assert (
                node["id"] not in pseudo_packages
            ), f"Pseudo-package '{node['id']}' should not appear as a package node"

    # --- Edge Assertions ---
    def find_edge(source, target, edge_type):
        return any(
            e.get("source") == source and e.get("target") == target and e.get("type") == edge_type for e in edges
        )

    expected_local_imports_edges = [
        ("src/main.js", "src/components/Button.js"),
        ("src/main.js", "src/utils/common/formatter.js"),
    ]

    for src, tgt in expected_local_imports_edges:
        assert find_edge(src, tgt, "imports_local"), f"Missing 'imports_local' edge: {src} -> {tgt}"

    # Ensure no unexpected package imports due to aliases
    for edge in edges:
        if edge.get("type") == "imports_package":
            assert edge.get("target") not in pseudo_packages, (
                f"Edge '{edge.get('source')} -> {edge.get('target')}' is an unexpected "
                f"'imports_package' for a pseudo-package"
            )


@pytest.mark.integration
def test_framework_sveltekit_alias_resolution():
    """
    Verify framework-specific alias resolution for SvelteKit ($app/* and $lib/*)

    Checks that:
    - '$app/environment' (and by extension '$env/*') resolves to '@sveltejs/kit' package
    - Specifically, '$env/static/private' should be handled
    - '$lib/MyComponent.svelte' resolves to the local file if jsconfig/tsconfig maps it
    - Correct 'package' and 'package_component' nodes are created
    - Correct 'imports_package' and 'uses_component' edges are created
    """
    # Convert relative path to absolute to avoid path duplication in SecureFileOps
    fixture_repo_path = os.path.abspath("tests/fixtures/javascript_aliases/framework_sveltekit")
    assert os.path.isdir(fixture_repo_path), f"Fixture directory not found: {fixture_repo_path}"

    results = run_analysis(
        repo_path=fixture_repo_path,
        output_prefix="test_js_framework_alias_output",
        verbose=False,
        minimal_outputs=True,
        focus_languages_str="javascript,typescript,svelte",  # Include svelte
        config_overrides=None,
    )

    assert "dependency_graph" in results, "Dependency graph missing from analysis results"
    graph_data = results["dependency_graph"]
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("links", [])

    assert "analyzer_details" in results, "Analyzer details missing from analysis results"
    analyzer_details = results["analyzer_details"]
    file_imports = analyzer_details.get("file_imports", {})  # file_to_external_dependencies
    file_package_components = analyzer_details.get("file_package_components", {})
    local_imports_map = analyzer_details.get("local_imports_map", {})

    # --- Assertions for app_env_importer.js ($app/environment) ---
    app_env_importer_rel_path = "app_env_importer.js"

    # Check file_imports (file_to_external_dependencies)
    # Keys are relative paths
    assert (
        app_env_importer_rel_path in file_imports
    ), f"'{app_env_importer_rel_path}' not found in file_imports: {list(file_imports.keys())}"
    assert (
        "@sveltejs/kit" in file_imports[app_env_importer_rel_path]
    ), f"'@sveltejs/kit' not found in imports for '{app_env_importer_rel_path}'"

    # Check file_package_components
    # Keys are relative paths
    # Expected: { ('$app/environment', '@sveltejs/kit'), ... }
    # The structure is file_path: set of (package_name, component_name)
    app_env_components = file_package_components.get(app_env_importer_rel_path, set())
    # The actual order from JSImportVisitor for framework aliases is (canonical_package, alias_path)
    # Updated for $env/static/private
    expected_app_env_component_tuple = ("@sveltejs/kit", "$env/static/private")
    assert expected_app_env_component_tuple in app_env_components, (
        f"Component {expected_app_env_component_tuple} not found for '{app_env_importer_rel_path}'. "
        f"Found: {app_env_components}"
    )

    # Graph nodes for $app/environment
    svelte_kit_node = next((n for n in nodes if n["id"] == "@sveltejs/kit" and n.get("type") == "package"), None)
    assert svelte_kit_node is not None, "Package node '@sveltejs/kit' not found"

    # The component node ID is fully qualified: <package_id>.<component_name_from_visitor>
    # Updated for $env/static/private
    expected_app_env_comp_id = "@sveltejs/kit.$env/static/private"
    app_env_comp_node = next(
        (n for n in nodes if n["id"] == expected_app_env_comp_id and n.get("type") == "package_component"), None
    )
    assert (
        app_env_comp_node is not None
    ), f"Package component node '{expected_app_env_comp_id}' not found. Nodes: {nodes}"
    assert (
        app_env_comp_node.get("component") == "$env/static/private"
    ), f"Component node name mismatch. Expected: '$env/static/private', Got: {app_env_comp_node.get('component')}"
    assert (
        app_env_comp_node.get("package") == "@sveltejs/kit"
    ), f"Component node package mismatch. Expected: '@sveltejs/kit', Got: {app_env_comp_node.get('package')}"

    # Graph edges for $app/environment
    def find_edge(source, target, edge_type):
        return any(
            e.get("source") == source and e.get("target") == target and e.get("type") == edge_type for e in edges
        )

    assert find_edge(
        "app_env_importer.js", "@sveltejs/kit", "imports_package"
    ), "Missing 'imports_package' edge: app_env_importer.js -> @sveltejs/kit"
    assert find_edge(
        "app_env_importer.js", expected_app_env_comp_id, "uses_component"
    ), f"Missing 'uses_component' edge: app_env_importer.js -> {expected_app_env_comp_id}"
    assert find_edge(
        "@sveltejs/kit", expected_app_env_comp_id, "contains_component"
    ), f"Missing 'contains_component' edge: @sveltejs/kit -> {expected_app_env_comp_id}"

    # --- Assertions for lib_importer.js ($lib/MyComponent.svelte) ---
    lib_importer_rel_path = "lib_importer.js"

    # Expected resolved path is relative to the fixture_repo_path
    expected_lib_import_resolved_rel = "src/lib/MyComponent.svelte"

    assert (
        lib_importer_rel_path in local_imports_map
    ), f"'{lib_importer_rel_path}' not found in local_imports_map for $lib test: {list(local_imports_map.keys())}"

    # local_imports_map values are already relative to repo_path
    actual_lib_imports = set(local_imports_map[lib_importer_rel_path])
    assert expected_lib_import_resolved_rel in actual_lib_imports, (
        f"Resolved path for '$lib/MyComponent.svelte' ('{expected_lib_import_resolved_rel}') not found "
        f"in local_imports_map for '{lib_importer_rel_path}'. Found: {actual_lib_imports}"
    )

    # Graph nodes for $lib import
    expected_lib_files = {
        "lib_importer.js",
        "src/lib/MyComponent.svelte",
        # app_env_importer.js is also a file node, but checked separately
    }
    for file_id in expected_lib_files:
        file_node = next((n for n in nodes if n["id"] == file_id and n.get("type") == "file"), None)
        assert file_node is not None, f"File node '{file_id}' not found for $lib test"

    # Graph edge for $lib import
    assert find_edge(
        "lib_importer.js", "src/lib/MyComponent.svelte", "imports_local"
    ), "Missing 'imports_local' edge: lib_importer.js -> src/lib/MyComponent.svelte"

    # Ensure $lib itself does not become a package node if it's fully resolved locally
    lib_pseudo_package_node = next((n for n in nodes if n["id"] == "$lib" and n.get("type") == "package"), None)
    assert (
        lib_pseudo_package_node is None
    ), "Pseudo-package '$lib' should not appear as a package node when resolved to local files"

    # General file nodes check for the framework fixture
    all_expected_files_in_framework_fixture = {"app_env_importer.js", "lib_importer.js", "src/lib/MyComponent.svelte"}


@pytest.mark.integration
def test_svelte_lib_fallback_resolution():
    """
    Verify SvelteKit $lib/* alias resolution fallback when not in tsconfig/jsconfig

    Checks that:
    - '$lib/FallbackComponent' resolves to 'src/lib/FallbackComponent.js'
    - Resolved path appears in the local_imports_map
    - The dependency graph shows correct 'file' nodes and 'imports_local' edges
    """
    # Convert relative path to absolute to avoid path duplication in SecureFileOps
    fixture_repo_path = os.path.abspath("tests/fixtures/javascript_aliases/svelte_lib_fallback")
    assert os.path.isdir(fixture_repo_path), f"Fixture directory not found: {fixture_repo_path}"

    results = run_analysis(
        repo_path=fixture_repo_path,
        output_prefix="test_js_svelte_lib_fallback_output",
        verbose=False,
        minimal_outputs=True,
        focus_languages_str="javascript",  # Only JS in this fixture
        config_overrides=None,  # Ensure no jsconfig/tsconfig is loaded externally
    )

    assert "dependency_graph" in results, "Dependency graph missing from analysis results"
    graph_data = results["dependency_graph"]
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("links", [])

    assert "analyzer_details" in results, "Analyzer details missing from analysis results"
    analyzer_details = results["analyzer_details"]
    local_imports_map = analyzer_details.get("local_imports_map", {})

    # --- Assertions for local_imports_map ---
    importer_js_rel_path = "importer.js"
    expected_resolved_path = "src/lib/FallbackComponent.js"

    assert (
        importer_js_rel_path in local_imports_map
    ), f"'{importer_js_rel_path}' not found in local_imports_map keys: {list(local_imports_map.keys())}"

    actual_resolved_imports = set(local_imports_map[importer_js_rel_path])
    assert expected_resolved_path in actual_resolved_imports, (
        f"Mismatch in resolved local imports for '{importer_js_rel_path}'.\n"
        f"Expected '{expected_resolved_path}' to be in {actual_resolved_imports}"
    )

    # --- Node Assertions ---
    expected_files = {"importer.js", "src/lib/FallbackComponent.js"}
    actual_files = {n["id"] for n in nodes if n.get("type") == "file"}

    assert actual_files == expected_files, f"Mismatch in file nodes. Expected: {expected_files}, Found: {actual_files}"

    # --- Edge Assertions ---
    def find_edge(source, target, edge_type):
        return any(
            e.get("source") == source and e.get("target") == target and e.get("type") == edge_type for e in edges
        )

    assert find_edge(
        "importer.js", "src/lib/FallbackComponent.js", "imports_local"
    ), "Missing 'imports_local' edge: importer.js -> src/lib/FallbackComponent.js"

    # Ensure $lib itself does not become a package node
    lib_pseudo_package_node = next((n for n in nodes if n["id"] == "$lib" and n.get("type") == "package"), None)
    assert (
        lib_pseudo_package_node is None
    ), "Pseudo-package '$lib' should not appear as a package node in fallback scenario"
