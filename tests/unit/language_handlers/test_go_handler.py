"""
Go handler – focused unit checks
"""

import os
from collections import defaultdict

import pytest

from gardener.treewalk.go import GoLanguageHandler


def mock_resolve_local_go(importing_file_rel_path, module_str):
    """
    Mocks the behavior of _resolve_local_import_go for testing

    Args:
        importing_file_rel_path: The repository-relative path of the importing file
        module_str: The import string (e.g., "./utils")

    Returns:
        The resolved path string if it's a known local import, else None
    """
    # These paths are relative to the 'tests/fixtures/go' directory,
    # matching the expected output for local_imports
    if module_str == "./utils":
        return "utils/helpers.go"
    elif module_str == "./config":
        return "config/settings.go"
    return None


def test_main_go_fixture_imports_extracted(tree_parser, logger):
    """Extract imports from main.go and assert representative invariants"""
    fixture_rel_path = "main.go"
    fixture_abs_path = os.path.join("tests/fixtures/go", fixture_rel_path)

    try:
        with open(fixture_abs_path, "r") as f:
            code_content = f.read()
    except FileNotFoundError:
        pytest.fail(f"Fixture file not found: {fixture_abs_path}")
        return

    root_node = tree_parser("go", code_content)
    handler = GoLanguageHandler(logger=logger)
    components_dict = defaultdict(list)  # Ensure this is defaultdict

    external_imports, local_imports = handler.extract_imports(
        root_node,
        # The extract_imports method expects the path of the importing file,
        # relative to the project root
        # For fixtures, this would be 'tests/fixtures/go/main.go'
        f"tests/fixtures/go/{fixture_rel_path}",
        components_dict,
        mock_resolve_local_go,
    )

    # Representative checks
    assert {"fmt", "os", "net/http", "github.com/gin-gonic/gin"}.issubset(set(external_imports))
    assert {"utils/helpers.go", "config/settings.go"}.issubset(set(local_imports))

    file_key = f"tests/fixtures/go/{fixture_rel_path}"
    assert file_key in components_dict
    assert ("github.com/gin-gonic/gin", "github.com/gin-gonic/gin.gin") in set(components_dict[file_key])
