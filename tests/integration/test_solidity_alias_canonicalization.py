import os

from gardener.analysis.main import analyze_repository


def test_solidity_aliases_canonicalized(tmp_path):
    """
    Ensure alias-like Solidity package names are canonicalized and not queried

    - '@openzeppelin' and '@openzeppelin/' should not appear as packages
    - '@openzeppelin/contracts' should be present
    """
    fixture = os.path.join(os.getcwd(), "tests", "fixtures", "solidity")

    # Provide URL cache to avoid network access during test
    url_cache = {
        "solidity:@openzeppelin/contracts": "https://github.com/OpenZeppelin/openzeppelin-contracts",
        "solidity:forge-std": "https://github.com/shunkakinoki/contracts",
        "solidity:solmate": "https://github.com/transmissions11/solmate",
        "npm:@openzeppelin/contracts": "https://github.com/OpenZeppelin/openzeppelin-contracts",
    }

    results = analyze_repository(fixture, specific_languages=["solidity"], verbose=False, url_cache=url_cache)

    pkgs = results["external_packages"]
    assert "@openzeppelin/contracts" in pkgs
    assert "@openzeppelin" not in pkgs
    assert "@openzeppelin/" not in pkgs
