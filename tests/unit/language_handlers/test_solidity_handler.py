"""
Solidity handler – focused unit checks
"""

import os

import pytest

from gardener.treewalk.solidity import SolidityLanguageHandler

BASE = "tests/fixtures/solidity"
REMAPPINGS = {
    "@openzeppelin/": "node_modules/@openzeppelin/contracts/",
    "forge-std/": "lib/forge-std/src/",
    "solmate/": "lib/solmate/src/",
}


def _mock_resolve(importing_file_rel_path, import_path_str):
    for prefix, base in REMAPPINGS.items():
        if import_path_str.startswith(prefix):
            if base + "Test.sol" == "lib/forge-std/src/Test.sol":
                return "lib/forge-std/src/Test.sol"
            return None
    if import_path_str.startswith("."):
        base_dir = os.path.dirname(importing_file_rel_path)
        resolved = os.path.normpath(os.path.join(base_dir, import_path_str))
        known = {
            "contracts/MyToken.sol": {
                "contracts/BaseToken.sol",
                "contracts/interfaces/IMyToken.sol",
                "contracts/libraries/MathUtils.sol",
                "contracts/Constants.sol",
            },
            "contracts/BaseToken.sol": {
                "interfaces/IMyToken.sol",
                "contracts/Config.sol",
            },
        }
        for k, vals in known.items():
            if importing_file_rel_path == k and resolved in vals:
                return resolved
    return None


def _load(rel):
    p = os.path.join(BASE, rel)
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


@pytest.mark.unit
def test_my_token_relative_and_remapped(tree_parser, logger):
    code = _load("contracts/MyToken.sol")
    root = tree_parser("solidity", code)
    handler = SolidityLanguageHandler(logger)
    comps = {}
    external, local = handler.extract_imports(root, "contracts/MyToken.sol", comps, _mock_resolve)

    assert {
        "contracts/BaseToken.sol",
        "contracts/interfaces/IMyToken.sol",
        "contracts/libraries/MathUtils.sol",
        "contracts/Constants.sol",
    }.issubset(set(local))
    assert "solmate" in set(external)
    assert ("solmate", "solmate.src/tokens/ERC20.sol as SolmateERC20") in set(comps["contracts/MyToken.sol"])


@pytest.mark.unit
def test_base_token_local_and_oz(tree_parser, logger):
    code = _load("contracts/BaseToken.sol")
    root = tree_parser("solidity", code)
    handler = SolidityLanguageHandler(logger)
    comps = {}
    external, local = handler.extract_imports(root, "contracts/BaseToken.sol", comps, _mock_resolve)

    assert {"interfaces/IMyToken.sol", "contracts/Config.sol"}.issubset(set(local))
    assert "@openzeppelin/contracts" in set(external)
    assert ("@openzeppelin/contracts", "@openzeppelin/contracts.token/ERC20/ERC20") in set(
        comps["contracts/BaseToken.sol"]
    )
