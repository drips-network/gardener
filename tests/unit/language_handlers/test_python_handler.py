import os
from collections import defaultdict

import pytest

from gardener.treewalk.python import PythonLanguageHandler

from .python_test_fixtures import EXPECTED_IMPORTS, create_mock_resolver


@pytest.mark.parametrize("fixture_rel_path", ["main.py", "utils.py", "config.py", "models/user.py", "services/api.py"])
def test_fixture_imports(tree_parser, logger, fixture_rel_path):
    """
    Extract imports from Python fixtures; assert representative invariants
    """
    fixture_abs_path = os.path.join("tests/fixtures/python", fixture_rel_path)

    try:
        with open(fixture_abs_path, "r") as f:
            code_content = f.read()
    except FileNotFoundError:
        pytest.fail(f"Fixture file not found: {fixture_abs_path}")

    root_node = tree_parser("python", code_content)
    handler = PythonLanguageHandler(logger=logger)
    components_dict = defaultdict(list)

    mock_resolver = create_mock_resolver()

    external_imports, local_imports = handler.extract_imports(
        root_node, fixture_rel_path, components_dict, mock_resolver
    )

    # Get expected values from fixture data
    expected_data = EXPECTED_IMPORTS[fixture_rel_path]
    expected_external_imports = expected_data["external"]
    expected_local_imports = expected_data["local"]
    expected_components = expected_data["components"]

    # Expected sets are minima
    assert set(expected_external_imports).issubset(set(external_imports))
    assert set(expected_local_imports).issubset(set(local_imports))
    actual_components = set(components_dict.get(fixture_rel_path, []))
    for comp in expected_components.get(fixture_rel_path, []):
        assert comp in actual_components

    # Additional checks for main.py
    if fixture_rel_path == "main.py":
        # Check that commented out imports are not present
        assert "unused_package" not in external_imports
        assert "commented_item_in_multi_line" not in local_imports  # e.g. '# product'


# Note: Aliased imports are already covered by the main parameterized test through fixture files:
# - main.py contains: import numpy as np, import pandas as pd, from datetime import datetime as dt
# - models/user.py contains: from datetime import datetime as dt


def test_from_future_import(tree_parser, logger):
    """Test 'from __future__ import annotations' which should be ignored or handled as std lib"""
    fixture_rel_path = "test_future.py"
    code_content = "from __future__ import annotations\nimport os"

    root_node = tree_parser("python", code_content)
    handler = PythonLanguageHandler(logger=logger)
    components_dict = defaultdict(list)
    external_imports, local_imports = handler.extract_imports(
        root_node, fixture_rel_path, components_dict, lambda rel_path, ms, l: None
    )

    # __future__ is a pseudo-module, part of stdlib
    assert {"__future__", "os"}.issubset(set(external_imports))
    assert not local_imports
    assert not components_dict.get(fixture_rel_path)
