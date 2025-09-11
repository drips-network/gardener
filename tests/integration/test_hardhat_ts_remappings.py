import os
import shutil

import pytest

from gardener.analysis.main import analyze_repository


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not available")
def test_hardhat_ts_remappings_detected(tmp_path):
    """
    Validate that TS hardhat.config remappings are detected via the Node helper
    and that '@openzeppelin/contracts' shows up among external packages.
    """
    fixture = os.path.join(os.getcwd(), "tests", "fixtures", "solidity_hardhat_ts")

    # Avoid network by giving cache for the expected package
    url_cache = {
        "solidity:@openzeppelin/contracts": "https://github.com/OpenZeppelin/openzeppelin-contracts",
        "npm:@openzeppelin/contracts": "https://github.com/OpenZeppelin/openzeppelin-contracts",
    }

    results = analyze_repository(fixture, specific_languages=["solidity"], verbose=False, url_cache=url_cache)

    pkgs = results["external_packages"]
    assert "@openzeppelin/contracts" in pkgs
