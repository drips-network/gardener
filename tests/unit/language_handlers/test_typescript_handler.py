"""
TypeScript handler – focused unit checks
"""

import os
from collections import defaultdict

import pytest

from gardener.treewalk.typescript import TypeScriptLanguageHandler

TS_DIR = "tests/fixtures/typescript"
KNOWN = {"types.ts", "config.ts", "utils/helpers.ts", "utils/index.ts", "components/Button.tsx", "main.ts"}
ALIASES = {"@utils": "utils", "@components": "components"}


def _mock_resolve(importing_file, module_str):
    if not module_str:
        return None
    for a, prefix in ALIASES.items():
        if module_str.startswith(a + "/"):
            module_str = module_str.replace(a + "/", prefix + "/", 1)
            break
    base = os.path.dirname(importing_file)
    resolved = os.path.normpath(os.path.join(base, module_str)) if module_str.startswith(".") else module_str
    candidates = [
        resolved if resolved.endswith((".ts", ".tsx")) else None,
        f"{resolved}.ts",
        f"{resolved}.tsx",
        f"{resolved}/index.ts",
    ]
    for c in candidates:
        if c and c in KNOWN:
            return c
    return None


def _load(rel):
    p = os.path.join(TS_DIR, rel)
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


@pytest.mark.unit
def test_main_ts_recognizes_external_and_locals(tree_parser, logger):
    code = _load("main.ts")
    root = tree_parser("typescript", code)
    handler = TypeScriptLanguageHandler(logger)
    comps = defaultdict(list)
    external, local = handler.extract_imports(root, "main.ts", comps, _mock_resolve)

    assert {"react", "axios", "lodash", "path", "fs"}.issubset(set(external))
    assert {"types.ts", "config.ts", "utils/index.ts", "components/Button.tsx", "utils/helpers.ts"}.issubset(set(local))
    assert {("react", "react.Component"), ("axios", "axios.AxiosRequestConfig")}.issubset(set(comps["main.ts"]))


@pytest.mark.unit
def test_button_tsx_local_and_external(tree_parser, logger):
    code = _load("components/Button.tsx")
    root = tree_parser("typescript", code)
    handler = TypeScriptLanguageHandler(logger)
    comps = defaultdict(list)
    external, local = handler.extract_imports(root, "components/Button.tsx", comps, _mock_resolve)

    assert {"react", "lodash"}.issubset(set(external))
    assert {"utils/index.ts", "utils/helpers.ts"}.issubset(set(local))
