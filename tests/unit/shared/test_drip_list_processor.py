from decimal import Decimal

import pytest

from services.shared.drip_list_processor import (
    aggregate_by_repository_url,
    build_normalized_drip_list,
    filter_valid_github_items,
    truncate_and_normalize,
)


@pytest.mark.unit
def test_filter_valid_github_items_self_filtered():
    items = [
        {"package_name": "self", "package_url": "https://github.com/acme/app", "percentage": 10},
        {"package_name": "other", "package_url": "https://github.com/org/dep1", "percentage": 20},
        {"package_name": "nonhub", "package_url": "https://gitlab.com/org/dep2", "percentage": 30},
    ]
    out = filter_valid_github_items(items, analyzed_repo_url="https://github.com/acme/app")
    assert all("github.com/" in x["package_url"] for x in out)
    assert not any("acme/app" in x["package_url"] for x in out)
    assert len(out) == 1


@pytest.mark.unit
def test_aggregate_by_repository_url_sums_scores():
    items = [
        {"package_name": "a", "package_url": "https://github.com/org/dep", "percentage": 10},
        {"package_name": "b", "package_url": "https://github.com/org/dep", "percentage": 5},
        {"package_name": "c", "package_url": "https://github.com/org/other", "percentage": 2.5},
    ]
    aggs = aggregate_by_repository_url(items)
    by_url = {a["package_url"]: a for a in aggs}
    assert by_url["https://github.com/org/dep"]["raw_score"] == Decimal("15")
    assert by_url["https://github.com/org/other"]["raw_score"] == Decimal("2.5")


@pytest.mark.unit
def test_truncate_and_normalize_exactly_100_percent():
    aggregates = [
        {"package_url": "https://github.com/org/x", "raw_score": Decimal("1"), "package_names": ["x"]},
        {"package_url": "https://github.com/org/y", "raw_score": Decimal("1"), "package_names": ["y"]},
        {"package_url": "https://github.com/org/z", "raw_score": Decimal("1"), "package_names": ["z"]},
    ]
    out = truncate_and_normalize(aggregates, max_length=3)
    total = sum(i["split_percentage"] for i in out)
    assert total == Decimal("100.0000")
    # Sorted by score desc; with ties, original order preserved → last receives residual
    assert len(out) == 3
    assert out[-1]["split_percentage"] + sum(i["split_percentage"] for i in out[:-1]) == Decimal("100.0000")


@pytest.mark.unit
def test_build_normalized_drip_list_end_to_end():
    items = [
        {"package_name": "a", "package_url": "https://github.com/org/dep1", "percentage": 10},
        {"package_name": "b", "package_url": "https://github.com/org/dep1", "percentage": 10},
        {"package_name": "c", "package_url": "https://github.com/org/dep2", "percentage": 5},
    ]
    out = build_normalized_drip_list(items, max_length=10, analyzed_repo_url=None)
    assert len(out) == 2
    assert sum(i["split_percentage"] for i in out) == Decimal("100.0000")
