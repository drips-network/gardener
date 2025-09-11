"""
Drip list processing pipeline helpers
"""

import re
from decimal import ROUND_HALF_UP, Decimal
from urllib.parse import urlparse


def _canonicalize_repo_url_local(url):
    """
    Converts various Git URL formats to 'host/owner/repo'

    This is a local helper to avoid import cycles with services.shared.utils.
    """
    url = url.lower().strip()

    # Handle git@host:path/repo.git format
    if url.startswith("git@"):
        url = "https://" + url[4:].replace(":", "/", 1)

    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    path = re.sub(r"\.git$", "", parsed.path.strip("/"))

    if not host:
        if ":" in url and "/" in url and url.find(":") < url.find("/"):
            host, path = url.split(":", 1)
            path = path.strip("/")
        else:
            raise ValueError("Could not determine host from URL")

    return f"{host}/{path}"


def filter_valid_github_items(items, analyzed_repo_url):
    """
    Keep only GitHub items; drop self-references if analyzed_repo_url is canonicalizable

    Args:
        items (list): Raw drip list-like items with percentage
        analyzed_repo_url (str|None): Canonical or full repo URL for self-filtering

    Returns:
        list[dict]
    """
    if not items:
        return []

    canonical_analyzed_url = None
    if analyzed_repo_url:
        if "://" in analyzed_repo_url:
            try:
                canonical_analyzed_url = _canonicalize_repo_url_local(analyzed_repo_url)
            except ValueError:
                canonical_analyzed_url = None
        else:
            canonical_analyzed_url = analyzed_repo_url.lower()

    out = []
    for item in items:
        package_url = item.get("package_url", "")
        if "github.com/" not in package_url:
            continue
        if canonical_analyzed_url and package_url:
            try:
                item_canonical_url = _canonicalize_repo_url_local(package_url)
                if item_canonical_url == canonical_analyzed_url:
                    continue
            except ValueError:
                pass
        out.append(item)
    return out


def aggregate_by_repository_url(items):
    """
    Aggregate 'percentage' across identical package_url

    Returns:
        list[dict]: each with keys: package_url, raw_score (Decimal), package_names, ecosystem
    """
    url_aggregates = {}
    for item in items:
        url = item.get("package_url", "")
        score = Decimal(str(item.get("percentage", "0")))
        if url not in url_aggregates:
            url_aggregates[url] = {
                "package_url": url,
                "raw_score": score,
                "package_names": [],
                "ecosystem": item.get("ecosystem", "unknown"),
            }
        else:
            url_aggregates[url]["raw_score"] += score
        package_name = item.get("package_name", "")
        if package_name:
            url_aggregates[url]["package_names"].append(package_name)
    return list(url_aggregates.values())


def derive_package_name(package_url, package_names):
    """
    Prefer 'owner/repo' from GitHub URL; fallback to first provided name or the URL itself

    Returns:
        str
    """
    package_name = None
    if "github.com/" in package_url:
        try:
            parts = package_url.split("github.com/")[1].strip("/").split("/")
            if len(parts) >= 2:
                package_name = f"{parts[0]}/{parts[1]}"
        except Exception:
            package_name = None
    if not package_name and package_names:
        return package_names[0]
    if not package_name:
        return package_url
    return package_name


def truncate_and_normalize(aggregates, max_length):
    """
    Sort desc by raw_score, truncate, and normalize to 100.0000 using Decimal(quantize)

    Returns:
        list[dict]: each includes 'split_percentage'
    """
    if not aggregates:
        return []

    # Derive final items with names
    processed = []
    for agg in aggregates:
        processed.append(
            {
                "package_name": derive_package_name(agg["package_url"], agg.get("package_names", [])),
                "package_url": agg["package_url"],
                "raw_score": agg["raw_score"],
                "ecosystem": agg.get("ecosystem", "unknown"),
            }
        )

    processed.sort(key=lambda x: x["raw_score"], reverse=True)
    truncated = processed[:max_length]
    if not truncated:
        return []

    total = sum(item["raw_score"] for item in truncated)
    if total == 0:
        for item in truncated:
            item["split_percentage"] = Decimal("0.0000")
            del item["raw_score"]
        return truncated

    running_total = Decimal("0")
    for item in truncated[:-1]:
        pct = item["raw_score"] / total * 100
        rounded = pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        item["split_percentage"] = rounded
        running_total += rounded
    truncated[-1]["split_percentage"] = Decimal("100.0000") - running_total

    for item in truncated:
        del item["raw_score"]
    return truncated


def build_normalized_drip_list(items, max_length, analyzed_repo_url):
    """
    End-to-end pipeline glued from the above helpers

    Returns:
        list[dict]: matches current normalize_drip_list output
    """
    filtered = filter_valid_github_items(items, analyzed_repo_url)
    if not filtered:
        return []
    aggregates = aggregate_by_repository_url(filtered)
    return truncate_and_normalize(aggregates, max_length)
