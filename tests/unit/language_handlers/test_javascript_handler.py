"""
JavaScript handler – focused unit checks
"""

import os
from collections import defaultdict

import pytest

from gardener.treewalk.javascript import JavaScriptLanguageHandler


def _mock_resolve_local(importing_file, module_str):
    table = {
        ("server.js", "./utils"): "utils.js",
        ("server.js", "./config"): "config/index.js",
        ("server.js", "./lib"): "lib/index.js",
        ("server.js", "./data.json"): "data.json",
        ("server.js", "./helpers.mjs"): "helpers.mjs",
        ("server.js", "./lib/stringUtils.cjs"): "lib/stringUtils.cjs",
        ("server.js", "./config/settings"): "config/settings.js",
        ("server.js", "./api/client.mjs"): "api/client.mjs",
        ("utils.js", "../config"): "config/index.js",
        ("utils.js", "./helpers.mjs"): "helpers.mjs",
        ("utils.js", "./constants.mjs"): "constants.mjs",
        ("utils.js", "./dynamicModule.js"): "dynamicModule.js",
        ("config/index.js", "./settings"): "config/settings.js",
        ("lib/index.js", "./math"): "lib/math.js",
        ("lib/index.js", "./stringUtils.cjs"): "lib/stringUtils.cjs",
        ("api/client.mjs", "../helpers.mjs"): "helpers.mjs",
        ("api/client.mjs", "../config"): "config/index.js",
        ("api/client.mjs", "../constants.mjs"): "constants.mjs",
        ("dynamic_importer.js", "./utils"): "utils.js",
    }
    return table.get((importing_file, module_str))


def _load(rel):
    p = os.path.join("tests/fixtures/javascript", rel)
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


@pytest.mark.unit
def test_server_js_detects_external_and_local(tree_parser, logger):
    code = _load("server.js")
    root = tree_parser("javascript", code)
    handler = JavaScriptLanguageHandler(logger)
    comps = defaultdict(list)
    external, local = handler.extract_imports(root, "server.js", comps, _mock_resolve_local, logger=logger)

    assert {"express", "lodash", "fs", "path"}.issubset(set(external))
    assert {"utils.js", "config/index.js", "helpers.mjs"}.issubset(set(local))
    assert {("express", "express.Router"), ("chalk", "chalk.chalk")}.issubset(set(comps["server.js"]))


@pytest.mark.unit
def test_client_mjs_handles_es_imports(tree_parser, logger):
    code = _load("api/client.mjs")
    root = tree_parser("javascript", code)
    handler = JavaScriptLanguageHandler(logger)
    comps = defaultdict(list)
    external, local = handler.extract_imports(root, "api/client.mjs", comps, _mock_resolve_local, logger=logger)

    assert "axios" in external
    assert {"helpers.mjs", "config/index.js"}.issubset(set(local))


@pytest.mark.unit
def test_utils_js_mixed_styles(tree_parser, logger):
    code = _load("utils.js")
    root = tree_parser("javascript", code)
    handler = JavaScriptLanguageHandler(logger)
    comps = defaultdict(list)
    external, local = handler.extract_imports(root, "utils.js", comps, _mock_resolve_local, logger=logger)

    assert {"express", "lodash", "fs"}.issubset(set(external))
    assert {"config/index.js", "helpers.mjs", "constants.mjs", "dynamicModule.js"}.issubset(set(local))
    assert ("express", "express.Router") in set(comps["utils.js"])


@pytest.mark.unit
def test_no_imports_file_has_none(tree_parser, logger):
    code = _load("no_imports_fixture.mjs")
    root = tree_parser("javascript", code)
    handler = JavaScriptLanguageHandler(logger)
    comps = defaultdict(list)
    external, local = handler.extract_imports(root, "no_imports_fixture.mjs", comps, _mock_resolve_local, logger=logger)
    assert not external and not local and not comps.get("no_imports_fixture.mjs")
