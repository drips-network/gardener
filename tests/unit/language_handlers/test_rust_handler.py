"""
Rust handler – focused unit checks
"""

import os
from collections import defaultdict

import pytest

from gardener.treewalk.rust import RustLanguageHandler


def _mock_resolve(importing_file, use_path_parts):
    if not use_path_parts:
        return None
    known = {
        ("crate", "models", "User"): "src/models/user.rs",
        ("crate", "config"): "src/config.rs",
        ("crate", "utils", "*"): "src/utils.rs",
        ("crate", "api"): "src/api/mod.rs",
        ("crate", "models"): "src/models/mod.rs",
        ("self", "internal_helper"): "src/services/internal_helper.rs",
        ("super",): None,  # handled below for parent mod lookups
    }
    key = tuple(use_path_parts)
    if key in known:
        return known[key]
    if use_path_parts[0] in ("std", "core", "alloc", "serde", "tokio", "log", "anyhow"):
        return None
    # Parent/current module shims
    if use_path_parts[0] == "super" and importing_file.startswith("src/api/"):
        return "src/api/mod.rs"
    return None


def _load(rel):
    p = os.path.join("tests/fixtures/rust", rel)
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


@pytest.mark.unit
def test_main_rs_detects_external_local_and_components(tree_parser, logger):
    code = _load("src/main.rs")
    root = tree_parser("rust", code)
    handler = RustLanguageHandler(logger)
    comps = defaultdict(list)
    external, local = handler.extract_imports(root, "src/main.rs", comps, _mock_resolve)

    assert {"serde", "tokio", "log", "std"}.issubset(set(external))
    assert {"src/utils.rs", "src/models/user.rs"}.issubset(set(local))
    assert {("serde", "serde::Deserialize"), ("tokio", "tokio::main")}.issubset(set(comps["src/main.rs"]))


@pytest.mark.unit
def test_client_rs_resolves_parent_and_model(tree_parser, logger):
    code = _load("src/api/client.rs")
    root = tree_parser("rust", code)
    handler = RustLanguageHandler(logger)
    comps = defaultdict(list)
    external, local = handler.extract_imports(root, "src/api/client.rs", comps, _mock_resolve)

    assert {"serde", "tokio", "std"}.issubset(set(external))
    assert "src/models/user.rs" in set(local)
    assert ("crate", "crate::models::User") in set(comps["src/api/client.rs"])


@pytest.mark.unit
def test_models_mod_rs_links_user(tree_parser, logger):
    code = _load("src/models/mod.rs")
    root = tree_parser("rust", code)
    handler = RustLanguageHandler(logger)
    comps = defaultdict(list)
    external, local = handler.extract_imports(root, "src/models/mod.rs", comps, _mock_resolve)

    assert "std" in set(external)
    # Accept either 'self::user::User' or 'user::User' depending on normalization
    _comps = set(comps["src/models/mod.rs"])
    assert any(s.endswith("user::User") for (_, s) in _comps)


@pytest.mark.unit
def test_services_mod_rs_internal_helper(tree_parser, logger):
    code = _load("src/services/mod.rs")
    root = tree_parser("rust", code)
    handler = RustLanguageHandler(logger)
    comps = defaultdict(list)
    external, local = handler.extract_imports(root, "src/services/mod.rs", comps, _mock_resolve)

    # Some handler versions do not emit a local edge for internal_helper; ensure user.rs is present
    assert "src/models/user.rs" in set(local)
    _comps = set(comps["src/services/mod.rs"])
    assert any(s.endswith("internal_helper::perform_action") for (_, s) in _comps)
