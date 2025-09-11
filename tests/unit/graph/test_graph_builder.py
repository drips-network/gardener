"""
Unit tests for the DependencyGraphBuilder
"""


def test_build_graph_only_files_no_imports(graph_builder, logger):
    """
    Test building a graph with only file nodes and no imports

    Verifies that file nodes are created correctly
    """
    source_files = {
        "file1.py": "/path/to/repo/file1.py",
        "file2.js": "/path/to/repo/file2.js",
    }
    external_packages = {}
    file_imports = {}
    file_package_components = {}
    local_imports_map = {}

    graph_builder.build_dependency_graph(
        source_files=source_files,
        external_packages=external_packages,
        file_imports=file_imports,
        file_package_components=file_package_components,
        local_imports_map=local_imports_map,
    )
    graph = graph_builder.graph

    assert graph.number_of_nodes() == 2
    assert graph.number_of_edges() == 0

    assert "file1.py" in graph.nodes
    assert graph.nodes["file1.py"]["type"] == "file"
    assert graph.nodes["file1.py"]["language"] == "python"  # Inferred from extension

    assert "file2.js" in graph.nodes
    assert graph.nodes["file2.js"]["type"] == "file"
    assert graph.nodes["file2.js"]["language"] == "javascript"  # Inferred from extension


def test_build_graph_files_importing_external_packages(graph_builder, logger):
    """
    Test building a graph where files import external packages

    Verifies that File -> Package edges of type 'imports_package' are created,
    and package nodes have correct attribute
    """
    source_files = {
        "app.py": "/path/to/repo/app.py",
        "main.js": "/path/to/repo/main.js",
    }
    external_packages = {
        "requests": {"ecosystem": "pypi", "import_names": ["requests"]},
        "lodash": {"ecosystem": "npm", "import_names": ["lodash", "_"]},
    }
    file_imports = {
        "app.py": ["requests"],
        "main.js": ["lodash"],
    }
    file_package_components = {}
    local_imports_map = {}

    graph_builder.build_dependency_graph(
        source_files=source_files,
        external_packages=external_packages,
        file_imports=file_imports,
        file_package_components=file_package_components,
        local_imports_map=local_imports_map,
    )
    graph = graph_builder.graph

    # Expected nodes: 2 files + 2 packages = 4
    assert graph.number_of_nodes() == 4
    # Expected edges: 2 (app.py -> requests, main.js -> lodash)
    assert graph.number_of_edges() == 2

    # File nodes
    assert "app.py" in graph.nodes
    assert graph.nodes["app.py"]["type"] == "file"
    assert graph.nodes["app.py"]["language"] == "python"

    assert "main.js" in graph.nodes
    assert graph.nodes["main.js"]["type"] == "file"
    assert graph.nodes["main.js"]["language"] == "javascript"

    # Package nodes
    assert "requests" in graph.nodes
    assert graph.nodes["requests"]["type"] == "package"
    assert graph.nodes["requests"]["ecosystem"] == "pypi"
    assert graph.nodes["requests"]["distribution_name"] == "requests"
    assert graph.nodes["requests"]["import_names"] == ["requests"]

    assert "lodash" in graph.nodes
    assert graph.nodes["lodash"]["type"] == "package"
    assert graph.nodes["lodash"]["ecosystem"] == "npm"
    assert graph.nodes["lodash"]["distribution_name"] == "lodash"
    assert graph.nodes["lodash"]["import_names"] == ["lodash", "_"]

    # Edges
    assert graph.has_edge("app.py", "requests")
    edge_data_app_requests = graph.get_edge_data("app.py", "requests")
    assert edge_data_app_requests["type"] == "imports_package"

    assert graph.has_edge("main.js", "lodash")
    edge_data_main_lodash = graph.get_edge_data("main.js", "lodash")
    assert edge_data_main_lodash["type"] == "imports_package"


def test_build_graph_files_importing_package_components(graph_builder, logger):
    """
    Test building a graph where files import specific components from external packages

    Verifies that File -> PackageComponent ('uses_component') and
    Package -> PackageComponent ('contains_component') edges are created,
    and component nodes have correct attributes
    """
    source_files = {
        "script.py": "/path/to/repo/script.py",
    }
    # 'os' is a standard library, typically not in external_packages but treated as one for this test
    # 'pandas' is a typical external package
    external_packages = {
        "os": {"ecosystem": "standard library", "import_names": ["os"]},  # Simplified for test
        "pandas": {"ecosystem": "pypi", "import_names": ["pandas"]},
    }
    file_imports = {"script.py": ["os", "pandas"]}  # Even if importing component, the base package might be listed here
    file_package_components = {
        "script.py": [("os", "os.path"), ("pandas", "pandas.DataFrame")],
    }
    local_imports_map = {}

    graph_builder.build_dependency_graph(
        source_files=source_files,
        external_packages=external_packages,
        file_imports=file_imports,
        file_package_components=file_package_components,
        local_imports_map=local_imports_map,
    )
    graph = graph_builder.graph

    # Expected nodes: 1 file + 2 packages ('os', 'pandas') + 2 components ('os.path', 'pandas.DataFrame') = 5
    assert graph.number_of_nodes() == 5
    # Expected edges:
    # script.py -> os.path (uses_component)
    # script.py -> pandas.DataFrame (uses_component)
    # os -> os.path (contains_component)
    # pandas -> pandas.DataFrame (contains_component)
    # script.py -> os (imports_package)
    # script.py -> pandas (imports_package)
    # Total = 6 edges
    assert graph.number_of_edges() == 6

    # File node
    assert "script.py" in graph.nodes
    assert graph.nodes["script.py"]["type"] == "file"

    # Package nodes
    assert "os" in graph.nodes
    assert graph.nodes["os"]["type"] == "package"
    assert graph.nodes["os"]["distribution_name"] == "os"  # Assuming dist name is same as import name

    assert "pandas" in graph.nodes
    assert graph.nodes["pandas"]["type"] == "package"
    assert graph.nodes["pandas"]["distribution_name"] == "pandas"

    # Package component nodes
    assert "os.path" in graph.nodes
    assert graph.nodes["os.path"]["type"] == "package_component"
    assert graph.nodes["os.path"]["distribution_name"] == "os"  # Component belongs to 'os' package

    assert "pandas.DataFrame" in graph.nodes
    assert graph.nodes["pandas.DataFrame"]["type"] == "package_component"
    assert graph.nodes["pandas.DataFrame"]["distribution_name"] == "pandas"  # Component belongs to 'pandas' package

    # Edges: File -> Component (uses_component)
    assert graph.has_edge("script.py", "os.path")
    edge_data_script_os_path = graph.get_edge_data("script.py", "os.path")
    assert edge_data_script_os_path["type"] == "uses_component"

    assert graph.has_edge("script.py", "pandas.DataFrame")
    edge_data_script_pandas_df = graph.get_edge_data("script.py", "pandas.DataFrame")
    assert edge_data_script_pandas_df["type"] == "uses_component"

    # Edges: Package -> Component (contains_component)
    assert graph.has_edge("os", "os.path")
    edge_data_os_os_path = graph.get_edge_data("os", "os.path")
    assert edge_data_os_os_path["type"] == "contains_component"

    assert graph.has_edge("pandas", "pandas.DataFrame")
    edge_data_pandas_pandas_df = graph.get_edge_data("pandas", "pandas.DataFrame")
    assert edge_data_pandas_pandas_df["type"] == "contains_component"


def test_build_graph_files_with_local_imports(graph_builder, logger):
    """
    Test building a graph where files import other local files

    Verifies that File -> File edges of type 'imports_local' are created
    """
    source_files = {
        "main.py": "/path/to/repo/main.py",
        "utils.py": "/path/to/repo/utils.py",
        "config.py": "/path/to/repo/config.py",
    }
    external_packages = {}
    file_imports = {}
    file_package_components = {}
    local_imports_map = {
        "main.py": ["utils.py", "config.py"],
        "utils.py": ["config.py"],
    }

    graph_builder.build_dependency_graph(
        source_files=source_files,
        external_packages=external_packages,
        file_imports=file_imports,
        file_package_components=file_package_components,
        local_imports_map=local_imports_map,
    )
    graph = graph_builder.graph

    # Expected nodes: 3 files
    assert graph.number_of_nodes() == 3
    # Expected edges:
    # main.py -> utils.py
    # main.py -> config.py
    # utils.py -> config.py
    # Total = 3 edges
    assert graph.number_of_edges() == 3

    # File nodes
    assert "main.py" in graph.nodes
    assert graph.nodes["main.py"]["type"] == "file"
    assert "utils.py" in graph.nodes
    assert graph.nodes["utils.py"]["type"] == "file"
    assert "config.py" in graph.nodes
    assert graph.nodes["config.py"]["type"] == "file"

    # Edges: File -> File (imports_local)
    assert graph.has_edge("main.py", "utils.py")
    edge_data_main_utils = graph.get_edge_data("main.py", "utils.py")
    assert edge_data_main_utils["type"] == "imports_local"

    assert graph.has_edge("main.py", "config.py")
    edge_data_main_config = graph.get_edge_data("main.py", "config.py")
    assert edge_data_main_config["type"] == "imports_local"

    assert graph.has_edge("utils.py", "config.py")
    edge_data_utils_config = graph.get_edge_data("utils.py", "config.py")
    assert edge_data_utils_config["type"] == "imports_local"


def test_build_graph_mixed_imports_in_one_file(graph_builder, logger):
    """
    Test building a graph with mixed import types (external, component, local)
    originating from a single file
    """
    source_files = {
        "app.py": "/path/to/repo/app.py",
        "helpers.py": "/path/to/repo/helpers.py",
    }
    external_packages = {
        "requests": {"ecosystem": "pypi", "import_names": ["requests"]},
        "pandas": {"ecosystem": "pypi", "import_names": ["pandas"]},
    }
    file_imports = {
        "app.py": ["requests", "pandas"],  # Direct import of requests, pandas for component
    }
    file_package_components = {
        "app.py": [("pandas", "pandas.Series")],
    }
    local_imports_map = {
        "app.py": ["helpers.py"],
    }

    graph_builder.build_dependency_graph(
        source_files=source_files,
        external_packages=external_packages,
        file_imports=file_imports,
        file_package_components=file_package_components,
        local_imports_map=local_imports_map,
    )
    graph = graph_builder.graph

    # Expected nodes:
    # 2 files: app.py, helpers.py
    # 2 packages: requests, pandas
    # 1 component: pandas.Series
    # Total = 5 nodes
    assert graph.number_of_nodes() == 5

    # Expected edges:
    # app.py -> helpers.py (imports_local)
    # app.py -> requests (imports_package)
    # app.py -> pandas.Series (uses_component)
    # pandas -> pandas.Series (contains_component)
    # app.py -> pandas (imports_package) - created because 'pandas' is in file_imports for app.py
    # Total = 5 edges
    assert graph.number_of_edges() == 5

    # File nodes
    assert "app.py" in graph.nodes
    assert graph.nodes["app.py"]["type"] == "file"
    assert "helpers.py" in graph.nodes
    assert graph.nodes["helpers.py"]["type"] == "file"

    # Package nodes
    assert "requests" in graph.nodes
    assert graph.nodes["requests"]["type"] == "package"
    assert "pandas" in graph.nodes
    assert graph.nodes["pandas"]["type"] == "package"

    # Component node
    assert "pandas.Series" in graph.nodes
    assert graph.nodes["pandas.Series"]["type"] == "package_component"
    assert graph.nodes["pandas.Series"]["distribution_name"] == "pandas"

    # Edges
    assert graph.has_edge("app.py", "helpers.py")
    assert graph.get_edge_data("app.py", "helpers.py")["type"] == "imports_local"

    assert graph.has_edge("app.py", "requests")
    assert graph.get_edge_data("app.py", "requests")["type"] == "imports_package"

    assert graph.has_edge("app.py", "pandas.Series")
    assert graph.get_edge_data("app.py", "pandas.Series")["type"] == "uses_component"

    assert graph.has_edge("pandas", "pandas.Series")
    assert graph.get_edge_data("pandas", "pandas.Series")["type"] == "contains_component"


def test_build_graph_multiple_files_various_imports(graph_builder, logger):
    """
    Test building a graph with multiple files having various import relationships,
    including local, external package, and package component imports
    """
    source_files = {
        "main.py": "/path/to/repo/main.py",
        "utils.py": "/path/to/repo/utils.py",
        "services.py": "/path/to/repo/services.py",
        "config.py": "/path/to/repo/config.py",
    }
    external_packages = {
        "requests": {"ecosystem": "pypi", "import_names": ["requests"]},
        "numpy": {"ecosystem": "pypi", "import_names": ["numpy", "np"]},
        "fastapi": {"ecosystem": "pypi", "import_names": ["fastapi"]},
    }
    file_imports = {
        "main.py": ["numpy", "fastapi"],  # Imports numpy (as np) and fastapi
        "services.py": ["requests"],  # Imports requests
        "utils.py": ["numpy"],  # Imports numpy (direct)
    }
    file_package_components = {
        "main.py": [("fastapi", "fastapi.Depends")],  # main.py uses fastapi.Depends
    }
    local_imports_map = {
        "main.py": ["utils.py", "services.py"],  # main.py imports utils.py and services.py
        "services.py": ["config.py"],  # services.py imports config.py
        "utils.py": ["config.py"],  # utils.py imports config.py
    }

    graph_builder.build_dependency_graph(
        source_files=source_files,
        external_packages=external_packages,
        file_imports=file_imports,
        file_package_components=file_package_components,
        local_imports_map=local_imports_map,
    )
    graph = graph_builder.graph

    # Expected nodes:
    # 4 files: main.py, utils.py, services.py, config.py
    # 3 packages: requests, numpy, fastapi
    # 1 component: fastapi.Depends
    # Total = 8 nodes
    assert graph.number_of_nodes() == 8

    # Expected edges:
    # Local imports:
    # main.py -> utils.py (imports_local)
    # main.py -> services.py (imports_local)
    # services.py -> config.py (imports_local)
    # utils.py -> config.py (imports_local)
    # External package imports:
    # main.py -> numpy (imports_package)
    # main.py -> fastapi (imports_package) - this might be redundant if component implies package import too
    # services.py -> requests (imports_package)
    # utils.py -> numpy (imports_package)
    # Component imports:
    # main.py -> fastapi.Depends (uses_component)
    # fastapi -> fastapi.Depends (contains_component)
    # Total edges = 4 (local) + 4 (package, assuming main->fastapi is created even with component) + 2 (component related) = 10
    # If main.py -> fastapi is not created due to component import, then 9 edges
    # The current implementation creates the package import edge even if only a component is used
    assert graph.number_of_edges() == 10

    # File nodes
    for f in ["main.py", "utils.py", "services.py", "config.py"]:
        assert f in graph.nodes
        assert graph.nodes[f]["type"] == "file"

    # Package nodes
    assert "requests" in graph.nodes and graph.nodes["requests"]["type"] == "package"
    assert "numpy" in graph.nodes and graph.nodes["numpy"]["type"] == "package"
    assert "fastapi" in graph.nodes and graph.nodes["fastapi"]["type"] == "package"

    # Component node
    assert "fastapi.Depends" in graph.nodes
    assert graph.nodes["fastapi.Depends"]["type"] == "package_component"
    assert graph.nodes["fastapi.Depends"]["distribution_name"] == "fastapi"

    # Local import edges
    assert (
        graph.has_edge("main.py", "utils.py") and graph.get_edge_data("main.py", "utils.py")["type"] == "imports_local"
    )  # noqa
    assert (
        graph.has_edge("main.py", "services.py")
        and graph.get_edge_data("main.py", "services.py")["type"] == "imports_local"
    )  # noqa
    assert (
        graph.has_edge("services.py", "config.py")
        and graph.get_edge_data("services.py", "config.py")["type"] == "imports_local"
    )  # noqa
    assert (
        graph.has_edge("utils.py", "config.py")
        and graph.get_edge_data("utils.py", "config.py")["type"] == "imports_local"
    )  # noqa

    # External package import edges
    assert graph.has_edge("main.py", "numpy") and graph.get_edge_data("main.py", "numpy")["type"] == "imports_package"
    assert (
        graph.has_edge("main.py", "fastapi") and graph.get_edge_data("main.py", "fastapi")["type"] == "imports_package"
    )  # noqa
    assert (
        graph.has_edge("services.py", "requests")
        and graph.get_edge_data("services.py", "requests")["type"] == "imports_package"
    )  # noqa
    assert graph.has_edge("utils.py", "numpy") and graph.get_edge_data("utils.py", "numpy")["type"] == "imports_package"

    # Component related edges
    assert (
        graph.has_edge("main.py", "fastapi.Depends")
        and graph.get_edge_data("main.py", "fastapi.Depends")["type"] == "uses_component"
    )  # noqa
    assert (
        graph.has_edge("fastapi", "fastapi.Depends")
        and graph.get_edge_data("fastapi", "fastapi.Depends")["type"] == "contains_component"
    )  # noqa


def test_build_graph_import_to_dist_mapping(graph_builder, logger):
    """
    Test handling of packages where import name differs from distribution name

    Ensures package nodes use distribution names and components correctly reference them
    """
    source_files = {
        "bot.py": "/path/to/repo/bot.py",
        "analyzer.py": "/path/to/repo/analyzer.py",
    }
    external_packages = {
        "python-telegram-bot": {"ecosystem": "pypi", "import_names": ["telegram"]},
        "beautifulsoup4": {"ecosystem": "pypi", "import_names": ["bs4"]},
        "scikit-learn": {"ecosystem": "pypi", "import_names": ["sklearn"]},
    }
    file_imports = {
        "bot.py": ["telegram"],  # Imports 'python-telegram-bot' via 'telegram'
        "analyzer.py": ["bs4", "sklearn"],  # Imports 'beautifulsoup4' via 'bs4' and 'scikit-learn' via 'sklearn'
    }
    file_package_components = {
        "bot.py": [("telegram", "telegram.ext.CommandHandler")],  # Uses a component from 'python-telegram-bot'
        "analyzer.py": [("sklearn", "sklearn.cluster.KMeans")],  # Uses a component from 'scikit-learn'
    }
    local_imports_map = {}

    graph_builder.build_dependency_graph(
        source_files=source_files,
        external_packages=external_packages,
        file_imports=file_imports,
        file_package_components=file_package_components,
        local_imports_map=local_imports_map,
    )
    graph = graph_builder.graph

    # Expected nodes:
    # 2 files: bot.py, analyzer.py
    # 3 packages: python-telegram-bot, beautifulsoup4, scikit-learn
    # 2 components: telegram.ext.CommandHandler, sklearn.cluster.KMeans
    # Total = 7 nodes
    assert graph.number_of_nodes() == 7

    # Expected edges:
    # bot.py -> python-telegram-bot (imports_package)
    # bot.py -> telegram.ext.CommandHandler (uses_component)
    # python-telegram-bot -> telegram.ext.CommandHandler (contains_component)
    # analyzer.py -> beautifulsoup4 (imports_package)
    # analyzer.py -> scikit-learn (imports_package)
    # analyzer.py -> sklearn.cluster.KMeans (uses_component)
    # scikit-learn -> sklearn.cluster.KMeans (contains_component)
    # Total = 7 edges
    assert graph.number_of_edges() == 7

    # File nodes
    assert "bot.py" in graph.nodes and graph.nodes["bot.py"]["type"] == "file"
    assert "analyzer.py" in graph.nodes and graph.nodes["analyzer.py"]["type"] == "file"

    # Package nodes (keyed by distribution name)
    assert "python-telegram-bot" in graph.nodes
    ptb_node = graph.nodes["python-telegram-bot"]
    assert ptb_node["type"] == "package"
    assert ptb_node["distribution_name"] == "python-telegram-bot"
    assert ptb_node["import_names"] == ["telegram"]
    assert ptb_node["ecosystem"] == "pypi"

    assert "beautifulsoup4" in graph.nodes
    bs4_node = graph.nodes["beautifulsoup4"]
    assert bs4_node["type"] == "package"
    assert bs4_node["distribution_name"] == "beautifulsoup4"
    assert bs4_node["import_names"] == ["bs4"]

    assert "scikit-learn" in graph.nodes
    sklearn_node = graph.nodes["scikit-learn"]
    assert sklearn_node["type"] == "package"
    assert sklearn_node["distribution_name"] == "scikit-learn"
    assert sklearn_node["import_names"] == ["sklearn"]

    # Component nodes
    assert "telegram.ext.CommandHandler" in graph.nodes
    tg_comp_node = graph.nodes["telegram.ext.CommandHandler"]
    assert tg_comp_node["type"] == "package_component"
    assert tg_comp_node["distribution_name"] == "python-telegram-bot"  # References parent package by dist name

    assert "sklearn.cluster.KMeans" in graph.nodes
    sklearn_comp_node = graph.nodes["sklearn.cluster.KMeans"]
    assert sklearn_comp_node["type"] == "package_component"
    assert sklearn_comp_node["distribution_name"] == "scikit-learn"  # References parent package by dist name

    # Edges for bot.py
    assert graph.has_edge("bot.py", "python-telegram-bot")
    assert graph.get_edge_data("bot.py", "python-telegram-bot")["type"] == "imports_package"
    assert graph.has_edge("bot.py", "telegram.ext.CommandHandler")
    assert graph.get_edge_data("bot.py", "telegram.ext.CommandHandler")["type"] == "uses_component"
    assert graph.has_edge("python-telegram-bot", "telegram.ext.CommandHandler")
    assert graph.get_edge_data("python-telegram-bot", "telegram.ext.CommandHandler")["type"] == "contains_component"

    # Edges for analyzer.py
    assert graph.has_edge("analyzer.py", "beautifulsoup4")
    assert graph.get_edge_data("analyzer.py", "beautifulsoup4")["type"] == "imports_package"
    assert graph.has_edge("analyzer.py", "scikit-learn")
    assert graph.get_edge_data("analyzer.py", "scikit-learn")["type"] == "imports_package"
    assert graph.has_edge("analyzer.py", "sklearn.cluster.KMeans")
    assert graph.get_edge_data("analyzer.py", "sklearn.cluster.KMeans")["type"] == "uses_component"
    assert graph.has_edge("scikit-learn", "sklearn.cluster.KMeans")
    assert graph.get_edge_data("scikit-learn", "sklearn.cluster.KMeans")["type"] == "contains_component"


def test_build_graph_ambiguous_imports_choose_lexicographic(graph_builder, logger, mocker):
    """
    Test handling of ambiguous imports where an import name maps to multiple packages

    It should log a warning and pick one of the packages (e.g., the first one encountered)
    """
    # Spy on the logger's warning method to check calls
    # This assumes 'logger' fixture is a real logger, and we use mocker to spy
    # If 'logger' is already a MagicMock, this spy might not be strictly necessary
    # and direct assertions on logger.warning could be used
    # Given the prompt implies using the 'logger' fixture directly for checks,
    # we'll prepare for asserting calls on it
    # For this example, let's assume 'logger' is a standard logger and we need to spy,
    # or if it's a mock, these assertions will work
    # If logger is a mock: mock_warning = logger.warning
    # If logger is real:
    mock_warning = mocker.spy(logger, "warning")

    source_files = {
        "app.py": "/path/to/repo/app.py",
    }
    # Define external_packages with an ambiguous import name 'shared_api'
    # 'package_alpha' is defined first, so it should be chosen by default if iteration order is preserved
    external_packages = {
        "package_alpha": {"ecosystem": "pypi", "import_names": ["shared_api"], "version": "1.0"},
        "package_beta": {"ecosystem": "pypi", "import_names": ["shared_api"], "version": "2.0"},
        "another_package": {"ecosystem": "pypi", "import_names": ["specific_api"], "version": "1.0"},
    }
    file_imports = {
        "app.py": ["shared_api", "specific_api"],
    }
    file_package_components = {}
    local_imports_map = {}

    graph_builder.build_dependency_graph(
        source_files=source_files,
        external_packages=external_packages,
        file_imports=file_imports,
        file_package_components=file_package_components,
        local_imports_map=local_imports_map,  # Pass the logger fixture
    )
    graph = graph_builder.graph

    # Expected nodes: 1 file (app.py) + 3 packages (package_alpha, package_beta, another_package) = 4
    # Both ambiguous packages will have nodes created
    assert graph.number_of_nodes() == 4
    # Expected edges: app.py -> package_alpha (lexicographically smallest), app.py -> another_package = 2
    assert graph.number_of_edges() == 2

    # File node
    assert "app.py" in graph.nodes

    # Package nodes: Both ambiguous packages should exist as nodes
    # The import_to_node map will determine which one 'shared_api' links to
    # Given dict iteration order, 'package_beta' is processed last for 'shared_api' in import_to_node
    assert "package_alpha" in graph.nodes
    assert graph.nodes["package_alpha"]["type"] == "package"
    assert graph.nodes["package_alpha"]["distribution_name"] == "package_alpha"

    assert "package_beta" in graph.nodes  # Verify the other ambiguous package IS in the graph
    assert graph.nodes["package_beta"]["type"] == "package"
    assert graph.nodes["package_beta"]["distribution_name"] == "package_beta"

    assert "another_package" in graph.nodes  # The non-ambiguous package
    assert graph.nodes["another_package"]["type"] == "package"

    # Edges
    # 'shared_api' import should resolve to 'package_alpha' by lexicographic rule
    assert graph.has_edge("app.py", "package_alpha")
    edge_data_alpha = graph.get_edge_data("app.py", "package_alpha")
    assert edge_data_alpha["type"] == "imports_package"
    assert edge_data_alpha["ident"] == "shared_api"
    assert edge_data_alpha.get("ambiguity_resolution") == "lexicographic"

    assert graph.has_edge("app.py", "another_package")
    edge_data_specific = graph.get_edge_data("app.py", "another_package")
    assert edge_data_specific["type"] == "imports_package"

    # Check for warning log
    # This assertion depends on the exact warning message format
    # For pytest, if logger is a MagicMock, use logger.warning.assert_any_call(...)
    # If using mocker.spy:
    found_warning = False
    for call_args in mock_warning.call_args_list:
        log_message = call_args[0][0] if call_args and call_args[0] else ""
        if (
            "Ambiguous import 'shared_api' has candidates:" in log_message
            and "package_alpha" in log_message
            and "package_beta" in log_message
            and "choosing 'package_alpha'" in log_message
        ):
            found_warning = True
            break
    assert found_warning, "Expected warning for ambiguous import was not logged"
    # A more specific check on which packages were listed in the warning:
    # e.g., assert "'package_alpha'" in logged_message and "'package_beta'" in logged_message
    # and f"Choosing 'package_alpha'" in logged_message


def test_build_graph_empty_inputs(graph_builder, logger):
    """
    Test building a graph with completely empty input data

    Verifies that an empty graph is produced without errors
    """
    source_files = {}
    external_packages = {}
    file_imports = {}
    file_package_components = {}
    local_imports_map = {}

    graph_builder.build_dependency_graph(
        source_files=source_files,
        external_packages=external_packages,
        file_imports=file_imports,
        file_package_components=file_package_components,
        local_imports_map=local_imports_map,
    )
    graph = graph_builder.graph

    # Expected: An empty graph
    assert graph.number_of_nodes() == 0
    assert graph.number_of_edges() == 0
