"""
Tests for the services.shared.utils module
"""

from decimal import Decimal

import pytest

from services.shared.utils import normalize_drip_list


@pytest.mark.unit
def test_empty_list():
    assert normalize_drip_list([]) == []


@pytest.mark.unit
def test_single_item():
    items = [{"package_name": "lodash", "package_url": "https://github.com/lodash/lodash", "percentage": "100.0"}]
    result = normalize_drip_list(items)
    assert len(result) == 1
    assert result[0]["package_name"] == "lodash/lodash"
    assert result[0]["package_url"] == "https://github.com/lodash/lodash"
    assert result[0]["split_percentage"] == Decimal("100.0000")


@pytest.mark.unit
def test_multiple_packages_same_url():
    items = [
        {
            "package_name": "@types/node",
            "package_url": "https://github.com/DefinitelyTyped/DefinitelyTyped",
            "percentage": "25.5",
        },
        {
            "package_name": "@types/jest",
            "package_url": "https://github.com/DefinitelyTyped/DefinitelyTyped",
            "percentage": "30.2",
        },
        {"package_name": "lodash", "package_url": "https://github.com/lodash/lodash", "percentage": "44.3"},
    ]
    result = normalize_drip_list(items)
    assert len(result) == 2
    definitely_typed = next(r for r in result if "DefinitelyTyped" in r["package_url"])
    assert definitely_typed["package_name"] == "DefinitelyTyped/DefinitelyTyped"
    assert definitely_typed["package_url"] == "https://github.com/DefinitelyTyped/DefinitelyTyped"
    lodash = next(r for r in result if "lodash" in r["package_url"])
    assert lodash["package_name"] == "lodash/lodash"
    assert lodash["package_url"] == "https://github.com/lodash/lodash"
    total = sum(r["split_percentage"] for r in result)
    assert total == Decimal("100.0000")


@pytest.mark.unit
def test_non_github_urls_filtered():
    items = [
        {"package_name": "local-package", "package_url": "file:///some/local/path", "percentage": "20.0"},
        {
            "package_name": "private-package",
            "package_url": "https://private.registry.com/package",
            "percentage": "30.0",
        },  # noqa
        {"package_name": "lodash", "package_url": "https://github.com/lodash/lodash", "percentage": "50.0"},
    ]
    result = normalize_drip_list(items)
    assert len(result) == 1
    assert result[0]["package_name"] == "lodash/lodash"
    assert result[0]["split_percentage"] == Decimal("100.0000")


@pytest.mark.unit
def test_precision_handling():
    items = [
        {"package_name": "package1", "package_url": "https://github.com/owner1/repo1", "percentage": "33.3333"},
        {"package_name": "package2", "package_url": "https://github.com/owner2/repo2", "percentage": "33.3333"},
        {"package_name": "package3", "package_url": "https://github.com/owner3/repo3", "percentage": "33.3334"},
    ]
    result = normalize_drip_list(items)
    assert len(result) == 3
    total = sum(r["split_percentage"] for r in result)
    assert total == Decimal("100.0000")
    for item in result:
        value_str = str(item["split_percentage"])
        if "." in value_str:
            assert len(value_str.split(".")[1]) == 4


@pytest.mark.unit
def test_sorting_by_percentage():
    items = [
        {"package_name": "small", "package_url": "https://github.com/owner/small", "percentage": "10.0"},
        {"package_name": "large", "package_url": "https://github.com/owner/large", "percentage": "60.0"},
        {"package_name": "medium", "package_url": "https://github.com/owner/medium", "percentage": "30.0"},
    ]
    result = normalize_drip_list(items)
    assert len(result) == 3
    assert result[0]["package_name"] == "owner/large"
    assert result[1]["package_name"] == "owner/medium"
    assert result[2]["package_name"] == "owner/small"


@pytest.mark.unit
def test_all_non_github_filtered():
    items = [
        {"package_name": "local-package", "package_url": "file:///some/local/path", "percentage": "50.0"},
        {
            "package_name": "private-package",
            "package_url": "https://private.registry.com/package",
            "percentage": "50.0",
        },
    ]
    result = normalize_drip_list(items)
    assert result == []


@pytest.mark.unit
def test_zero_percentage_handling():
    items = [
        {"package_name": "package1", "package_url": "https://github.com/owner/repo1", "percentage": "0"},
        {"package_name": "package2", "package_url": "https://github.com/owner/repo2", "percentage": "0"},
    ]
    result = normalize_drip_list(items)
    assert len(result) == 2
    for item in result:
        assert item["split_percentage"] == Decimal("0.0000")


@pytest.mark.unit
def test_package_name_extraction_edge_cases():
    items = [
        {"package_name": "original-name", "package_url": "https://github.com/owner/repo/", "percentage": "25.0"},
        {"package_name": "another-name", "package_url": "https://github.com/owner", "percentage": "25.0"},
        {"package_name": "third-name", "package_url": "https://github.com/", "percentage": "25.0"},
        {"package_name": "fourth-name", "package_url": "https://github.com/owner/repo/tree/main", "percentage": "25.0"},
    ]
    result = normalize_drip_list(items)
    assert len(result) == 4
    for item in result:
        if "/owner/repo" in item["package_url"] and item["package_url"].endswith("repo/"):
            assert item["package_name"] == "owner/repo"
        elif item["package_url"] == "https://github.com/owner":
            assert item["package_name"] == "another-name"
        elif item["package_url"] == "https://github.com/":
            assert item["package_name"] == "third-name"
        elif "tree/main" in item["package_url"]:
            assert item["package_name"] == "owner/repo"
