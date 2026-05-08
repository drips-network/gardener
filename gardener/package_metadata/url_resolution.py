"""
Canonical repository URL resolution receipt helpers
"""

from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

_GITHUB_HOSTS = {"github.com", "www.github.com"}
_GITLAB_HOSTS = {"gitlab.com", "www.gitlab.com"}


URL_RESOLUTION_STATUS_RESOLVED = "resolved"
URL_RESOLUTION_STATUS_UNRESOLVED = "unresolved"
URL_RESOLUTION_STATUS_NOT_APPLICABLE = "not-applicable"

URL_RESOLUTION_CACHE_HIT = "hit"
URL_RESOLUTION_CACHE_MISS = "miss"
URL_RESOLUTION_CACHE_NOT_USED = "not-used"

URL_RESOLUTION_SOURCE_CACHE = "cache"
URL_RESOLUTION_SOURCE_GITMODULES = "gitmodules"
URL_RESOLUTION_SOURCE_NPM_REGISTRY = "npm-registry"
URL_RESOLUTION_SOURCE_PYPI_REGISTRY = "pypi-registry"
URL_RESOLUTION_SOURCE_CRATES_IO = "crates-io"
URL_RESOLUTION_SOURCE_GO_IMPORT_PATH = "go-import-path"
URL_RESOLUTION_SOURCE_GO_GET_META = "go-get-meta"
URL_RESOLUTION_SOURCE_SOLIDITY_SOURCE_HINT = "solidity-source-hint"
URL_RESOLUTION_SOURCE_STATIC_RULE = "static-rule"
URL_RESOLUTION_SOURCE_UNSUPPORTED_ECOSYSTEM = "unsupported-ecosystem"
URL_RESOLUTION_SOURCE_PROVIDED = "provided"
URL_RESOLUTION_SOURCE_NOT_RECORDED = "not-recorded"

URL_RESOLUTION_REASON_NO_DATA_RETURNED = "no-data-returned"
URL_RESOLUTION_REASON_NETWORK_ERROR = "network-error"
URL_RESOLUTION_REASON_INVALID_REGISTRY_RESPONSE = "invalid-registry-response"
URL_RESOLUTION_REASON_VALIDATION_REJECTED = "validation-rejected"
URL_RESOLUTION_REASON_NO_REPOSITORY_URL = "no-repository-url"
URL_RESOLUTION_REASON_NORMALIZATION_FAILED = "normalization-failed"
URL_RESOLUTION_REASON_INVALID_CACHE_ENTRY = "invalid-cache-entry"
URL_RESOLUTION_REASON_UNSUPPORTED_ECOSYSTEM = "unsupported-ecosystem"
URL_RESOLUTION_REASON_RESOLVER_ERROR = "resolver-error"
URL_RESOLUTION_REASON_RESOLUTION_NOT_RECORDED = "resolution-not-recorded"


def utc_now_isoformat() -> str:
    """
    Return the current UTC time as an ISO-8601 string
    """
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_repository_url_resolution(
    *,
    status: str,
    source: str,
    cache: str,
    normalized: bool,
    checked_at: str,
    reason: str | None = None,
) -> dict:
    """
    Build a canonical repository URL resolution receipt
    """
    if status == URL_RESOLUTION_STATUS_UNRESOLVED and not reason:
        raise ValueError("Unresolved URL receipts require a reason")
    if status == URL_RESOLUTION_STATUS_RESOLVED and reason:
        raise ValueError("Resolved URL receipts must not include a reason")

    receipt = {
        "status": status,
        "source": source,
        "cache": cache,
        "normalized": normalized,
        "checked_at": checked_at,
    }
    if reason:
        receipt["reason"] = reason
    return receipt


def build_not_applicable_url_resolution() -> dict:
    """
    Build a URL resolution receipt for dependencies that do not use repository URL resolution
    """
    return build_repository_url_resolution(
        status=URL_RESOLUTION_STATUS_NOT_APPLICABLE,
        source=URL_RESOLUTION_SOURCE_NOT_RECORDED,
        cache=URL_RESOLUTION_CACHE_NOT_USED,
        normalized=False,
        checked_at=utc_now_isoformat(),
    )


def infer_repository_url_resolution_from_existing_url(
    repository_url: str | None,
    *,
    checked_at: str | None = None,
    normalized: bool = False,
) -> dict:
    """
    Infer an explicit receipt for callers that already provided package URL data
    """
    receipt_checked_at = checked_at or utc_now_isoformat()
    if repository_url:
        return build_repository_url_resolution(
            status=URL_RESOLUTION_STATUS_RESOLVED,
            source=URL_RESOLUTION_SOURCE_PROVIDED,
            cache=URL_RESOLUTION_CACHE_NOT_USED,
            normalized=normalized,
            checked_at=receipt_checked_at,
        )
    return build_repository_url_resolution(
        status=URL_RESOLUTION_STATUS_UNRESOLVED,
        source=URL_RESOLUTION_SOURCE_NOT_RECORDED,
        cache=URL_RESOLUTION_CACHE_NOT_USED,
        normalized=normalized,
        checked_at=receipt_checked_at,
        reason=URL_RESOLUTION_REASON_RESOLUTION_NOT_RECORDED,
    )


def sanitize_repository_url(repository_url: str | None) -> str:
    """
    Return a persisted-safe repository URL without credentials, query, or fragment
    """
    if not repository_url or not isinstance(repository_url, str):
        return ""

    try:
        parsed = urlsplit(repository_url)
    except ValueError:
        return ""

    if not parsed.scheme or not parsed.netloc:
        if "@" in repository_url:
            return ""
        return repository_url.split("#", 1)[0].split("?", 1)[0]

    hostname = parsed.hostname
    if not hostname:
        return ""

    try:
        port = parsed.port
    except ValueError:
        return ""

    host = hostname.lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    if host in _GITHUB_HOSTS and len(path_parts) >= 2:
        repo_name = path_parts[1].removesuffix(".git")
        return f"https://github.com/{path_parts[0]}/{repo_name}"
    if host in _GITLAB_HOSTS and len(path_parts) >= 2:
        separator_index = path_parts.index("-") if "-" in path_parts else len(path_parts)
        project_parts = path_parts[:separator_index]
        if len(project_parts) >= 2:
            project_parts[-1] = project_parts[-1].removesuffix(".git")
            return f"https://gitlab.com/{'/'.join(project_parts)}"

    netloc = host
    if port:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def ensure_repository_url_resolution(
    package_info: dict,
    *,
    checked_at: str | None = None,
) -> dict:
    """
    Return a shallow package-info copy with URL and URL-resolution receipt fields present
    """
    normalized_info = dict(package_info)
    repository_url = normalized_info.get("repository_url") or ""
    repository_url = repository_url if isinstance(repository_url, str) else str(repository_url)
    sanitized_url = sanitize_repository_url(repository_url)
    existing_receipt = normalized_info.get("repository_url_resolution")
    normalized_info["repository_url"] = sanitized_url

    if repository_url and not sanitized_url:
        receipt = existing_receipt if isinstance(existing_receipt, dict) else {}
        normalized_info["repository_url_resolution"] = build_repository_url_resolution(
            status=URL_RESOLUTION_STATUS_UNRESOLVED,
            source=receipt.get("source") or URL_RESOLUTION_SOURCE_PROVIDED,
            cache=receipt.get("cache") or URL_RESOLUTION_CACHE_NOT_USED,
            normalized=True,
            checked_at=receipt.get("checked_at") or checked_at or utc_now_isoformat(),
            reason=URL_RESOLUTION_REASON_NORMALIZATION_FAILED,
        )
        return normalized_info

    normalized_info.setdefault(
        "repository_url_resolution",
        infer_repository_url_resolution_from_existing_url(
            sanitized_url,
            checked_at=checked_at,
            normalized=sanitized_url != repository_url,
        ),
    )
    if sanitized_url != repository_url and isinstance(normalized_info.get("repository_url_resolution"), dict):
        normalized_info["repository_url_resolution"] = dict(normalized_info["repository_url_resolution"])
        normalized_info["repository_url_resolution"]["normalized"] = True
    return normalized_info
