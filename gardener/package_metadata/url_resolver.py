"""
Package resolution methods
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from gardener.package_metadata.url_resolution import (
    URL_RESOLUTION_CACHE_HIT,
    URL_RESOLUTION_CACHE_MISS,
    URL_RESOLUTION_CACHE_NOT_USED,
    URL_RESOLUTION_REASON_INVALID_CACHE_ENTRY,
    URL_RESOLUTION_REASON_INVALID_REGISTRY_RESPONSE,
    URL_RESOLUTION_REASON_NETWORK_ERROR,
    URL_RESOLUTION_REASON_NO_DATA_RETURNED,
    URL_RESOLUTION_REASON_NO_REPOSITORY_URL,
    URL_RESOLUTION_REASON_NORMALIZATION_FAILED,
    URL_RESOLUTION_REASON_RESOLVER_ERROR,
    URL_RESOLUTION_REASON_UNSUPPORTED_ECOSYSTEM,
    URL_RESOLUTION_REASON_VALIDATION_REJECTED,
    URL_RESOLUTION_SOURCE_CACHE,
    URL_RESOLUTION_SOURCE_CRATES_IO,
    URL_RESOLUTION_SOURCE_GITMODULES,
    URL_RESOLUTION_SOURCE_GO_GET_META,
    URL_RESOLUTION_SOURCE_GO_IMPORT_PATH,
    URL_RESOLUTION_SOURCE_NPM_REGISTRY,
    URL_RESOLUTION_SOURCE_PYPI_REGISTRY,
    URL_RESOLUTION_SOURCE_SOLIDITY_SOURCE_HINT,
    URL_RESOLUTION_SOURCE_STATIC_RULE,
    URL_RESOLUTION_SOURCE_UNSUPPORTED_ECOSYSTEM,
    URL_RESOLUTION_STATUS_RESOLVED,
    URL_RESOLUTION_STATUS_UNRESOLVED,
    build_repository_url_resolution,
    sanitize_repository_url,
    utc_now_isoformat,
)

try:
    from gardener.common.input_validation import InputValidator, ValidationError

    SECURITY_AVAILABLE = True
except ImportError:
    SECURITY_AVAILABLE = False
    ValidationError = Exception  # Fallback


USER_AGENT = "Gardener/0.1 (https://drips.network)"
REQUEST_TIMEOUT = 10  # seconds
RETRY_COUNT = 3
RETRY_DELAY = 1  # seconds (initial delay)

# Allowed registry domains
ALLOWED_REGISTRY_DOMAINS = {
    "registry.npmjs.org",
    "pypi.org",
    "files.pythonhosted.org",
    "crates.io",
    "proxy.golang.org",
    "api.github.com",
    "raw.githubusercontent.com",
}

# Optional request hook for testing. When set via set_request_fn, functions should
# call this to obtain raw response bytes for the given URL instead of performing
# real network I/O. The function signature is: fn(url: str) -> bytes | str | None
_REQUEST_FN = None


def set_request_fn(fn):
    """
    Set a custom request function for testing to avoid outbound network calls

    Args:
        fn (callable): Function taking url string and returning bytes/str/None
    """
    global _REQUEST_FN
    _REQUEST_FN = fn


# Module-internal regex patterns for repository URL parsing
# Underscore-prefixed to indicate non-public API usage
_RE_GH_PAGES = re.compile(r"https?://([^/]+)\.github\.io/([^/]+)")
_RE_GL_PAGES = re.compile(r"https?://([^/]+)\.gitlab\.io/([^/]+)")
_RE_GO_IMPORT_META = re.compile(
    r'<meta\s+name=["\']go-import["\']\s+content=["\']([^ ]+)\s+(git|hg|svn|bzr)\s+([^"\']+)["\']', re.IGNORECASE
)
_RE_OWNER_REPO_SHORTHAND = re.compile(r"^[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$")


def _validate_or_none(url, logger=None):
    """
    Validate URL against allowed domains/schemes using InputValidator

    Args:
        url (str): URL to validate
        logger: Optional logger

    Returns:
        str: validated URL or None if rejected (also logs the same error string)
    """
    if not SECURITY_AVAILABLE:
        return url
    try:
        validated_url = InputValidator.validate_url(
            url, allowed_schemes={"https"}, allowed_domains=ALLOWED_REGISTRY_DOMAINS
        )
        return validated_url
    except ValidationError as e:
        logger and logger.error(f"Invalid URL rejected: {url} - {e}")
        return None


def _request_once(url, logger=None):
    """
    Perform a single HTTP GET with headers and decode JSON if status == 200

    Args:
        url (str): Validated URL
        logger: Optional logger

    Returns:
        tuple: (status_code_or_None, json_dict_or_None, exception_or_None)
    """
    # If a request hook is provided, use it to get raw content (JSON expected here)
    if _REQUEST_FN is not None:
        try:
            raw = _REQUEST_FN(url)
            if raw is None:
                return 404, None, None
            if isinstance(raw, bytes):
                text = raw.decode("utf-8", errors="ignore")
            else:
                text = str(raw)
            return 200, json.loads(text), None
        except json.JSONDecodeError as e:
            return 200, None, e
        except Exception as e:
            return None, None, e

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        if response.status == 200:
            return 200, json.loads(response.read().decode("utf-8")), None
        if response.status == 404:
            return 404, None, None
        http_err = urllib.error.HTTPError(url, response.status, response.reason, response.headers, None)
        return response.status, None, http_err


def _make_request_outcome(url, logger=None):
    """
    Make an HTTP GET request and return data with a stable failure reason
    """
    validated = _validate_or_none(url, logger)
    if validated is None:
        return {"data": None, "reason": URL_RESOLUTION_REASON_VALIDATION_REJECTED}
    url = validated

    last_exception = None
    last_reason = URL_RESOLUTION_REASON_NETWORK_ERROR
    delay = RETRY_DELAY
    for attempt in range(RETRY_COUNT + 1):
        try:
            status, data, single_error = _request_once(url, logger)
            if status == 200:
                if isinstance(data, dict):
                    return {"data": data, "reason": None}
                last_exception = single_error
                last_reason = URL_RESOLUTION_REASON_INVALID_REGISTRY_RESPONSE
                logger and logger.warning(f"Invalid JSON registry response for {url}")
                break
            if status == 404:
                logger and logger.debug(f"Package not found (404): {url}")
                return {"data": None, "reason": URL_RESOLUTION_REASON_NO_DATA_RETURNED}
            if status is not None:
                last_exception = single_error
                last_reason = URL_RESOLUTION_REASON_NETWORK_ERROR
                logger and logger.warning(f"HTTP error {status} for {url} (attempt {attempt + 1}/{RETRY_COUNT + 1})")

        except urllib.error.HTTPError as e:
            last_exception = e
            if e.code == 404:
                logger and logger.debug(f"Package not found (404): {url}")
                return {"data": None, "reason": URL_RESOLUTION_REASON_NO_DATA_RETURNED}
            last_reason = URL_RESOLUTION_REASON_NETWORK_ERROR
            logger and logger.warning(
                f"HTTP error {e.code} for {url} " f"(attempt {attempt + 1}/{RETRY_COUNT + 1}): {e.reason}"
            )
        except json.JSONDecodeError as e:
            last_exception = e
            last_reason = URL_RESOLUTION_REASON_INVALID_REGISTRY_RESPONSE
            logger and logger.warning(f"Invalid JSON registry response for {url}: {e}")
            break
        except Exception as e:
            last_exception = e
            last_reason = URL_RESOLUTION_REASON_NETWORK_ERROR
            logger and logger.warning(f"Error fetching {url} (attempt {attempt + 1}/{RETRY_COUNT + 1}): {e}")

        if attempt < RETRY_COUNT:
            logger and logger.debug(f"Retrying in {delay}s...")
            time.sleep(delay)
            delay *= 2  # Exponential backoff

    logger and logger.error(f"Failed to fetch {url} after {RETRY_COUNT + 1} attempts. Last error: {last_exception}")
    return {"data": None, "reason": last_reason}


def _make_request(url, logger=None):
    """
    Make an HTTP GET request with retries, security validation, and proper headers

    Validates URLs against allowed registry domains and implements exponential
    backoff retry logic with comprehensive error handling

    Args:
        url (str): URL to request (must be from allowed domains)
        logger (Logger): Optional logger instance

    Returns:
        JSON response data as dict, or None if request fails or returns 404
    """
    return _make_request_outcome(url, logger)["data"]


def _strip_fragment(url_str):
    """
    Remove fragment part after '#' from repo URL string

    Args:
        url_str (str): Repository URL string

    Returns:
        URL string without fragment
    """
    if not isinstance(url_str, str):
        return url_str
    if "#" in url_str:
        return url_str.split("#")[0]
    return url_str


def _normalize_git_prefixes(url_str):
    """
    Convert 'git+' and 'git://' prefixes to standard https forms

    Args:
        url_str (str): Repository URL string

    Returns:
        Normalized URL string
    """
    if not isinstance(url_str, str):
        return url_str
    u = url_str
    if u.startswith("git+"):
        u = u[4:]
    if u.startswith("git://"):
        u = "https://" + u[6:]
    return u


def _safe_urlsplit(url_str):
    """
    Parse a URL-like string without allowing malformed metadata to raise
    """
    try:
        return urllib.parse.urlsplit(url_str)
    except ValueError:
        return None


def _strip_url_credentials(url_str):
    """
    Remove username/password credentials from URL-like strings

    Args:
        url_str (str): Repository URL string

    Returns:
        URL string without userinfo
    """
    if not isinstance(url_str, str):
        return url_str
    parsed = _safe_urlsplit(url_str)
    if parsed is None:
        return None
    if not parsed.scheme or not parsed.netloc or "@" not in parsed.netloc:
        return url_str
    netloc = parsed.netloc.rsplit("@", 1)[1]
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _extract_github_owner_repo(url_str):
    """
    Trim GitHub URL to 'https://github.com/<owner>/<repo>' if present

    Args:
        url_str (str): Repository URL string

    Returns:
        Canonical GitHub owner/repo URL if matched, else original string
    """
    if not isinstance(url_str, str):
        return url_str

    scp_match = re.match(r"^(?:ssh://)?(?:git@)?github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?(?:\s|$)", url_str)
    if scp_match:
        return f"https://github.com/{scp_match.group(1)}"

    parsed = _safe_urlsplit(url_str)
    if parsed is None:
        return None
    if parsed.scheme not in {"http", "https"}:
        return url_str

    host = (parsed.hostname or "").lower()
    if host not in {"github.com", "www.github.com"}:
        return url_str

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        return f"https://github.com/{parts[0]}/{parts[1]}"
    return url_str


def _strip_dot_git(url_str):
    """
    Remove trailing '.git' suffix

    Args:
        url_str (str): Repository URL string

    Returns:
        URL without .git suffix
    """
    if not isinstance(url_str, str):
        return url_str
    if url_str.endswith(".git"):
        return url_str[:-4]
    return url_str


def _assume_github_from_owner_repo_shorthand(url_str):
    """
    If string looks like 'owner/repo', return 'https://github.com/owner/repo'
    Else return None

    Args:
        url_str (str): Owner/repo shorthand or other string

    Returns:
        Canonical GitHub URL or None
    """
    if not isinstance(url_str, str):
        return None
    if _RE_OWNER_REPO_SHORTHAND.match(url_str):
        return f"https://github.com/{url_str}"
    return None


def _clean_repo_url(repo_url):
    """
    Clean and normalize repository URLs for consistent formatting

    Removes common prefixes, suffixes, and fragments while extracting
    the canonical repository URL. Handles GitHub URL normalization
    and various git protocol conversions

    Args:
        repo_url (str): Raw repository URL string

    Returns:
        Cleaned repository URL string, or None if URL is invalid
    """
    if not repo_url or not isinstance(repo_url, str):
        return None

    u = _strip_fragment(repo_url)
    u = _normalize_git_prefixes(u)
    u = _strip_url_credentials(u)
    if not u:
        return None
    u = _extract_github_owner_repo(u)
    if not u:
        return None
    u = _strip_dot_git(u)

    if u.startswith("http://") or u.startswith("https://"):
        return sanitize_repository_url(u) or None

    assumed = _assume_github_from_owner_repo_shorthand(u)
    if assumed:
        return assumed

    return None


# Main resolution logic:


def _is_solidity_alias_like(name):
    """
    Heuristic: skip npm lookups for Solidity alias tokens

    - Trailing slash (e.g., '@openzeppelin/') indicates a remapping prefix
    - Bare scope '@scope' without a package segment
    """
    if not isinstance(name, str):
        return False
    if name.endswith("/"):
        return True
    if name.startswith("@") and "/" not in name:
        return True
    return False


def _finalize_url_attempt(
    *,
    raw_url,
    source,
    cache_state,
    checked_at,
    unresolved_reason,
    invalid_url_reason=URL_RESOLUTION_REASON_NORMALIZATION_FAILED,
):
    """
    Convert a raw URL candidate into the canonical resolver entry shape
    """
    if raw_url:
        cleaned_url = _clean_repo_url(raw_url)
        if cleaned_url:
            return {
                "repository_url": cleaned_url,
                "repository_url_resolution": build_repository_url_resolution(
                    status=URL_RESOLUTION_STATUS_RESOLVED,
                    source=source,
                    cache=cache_state,
                    normalized=cleaned_url != raw_url,
                    checked_at=checked_at,
                ),
            }
        return {
            "repository_url": "",
            "repository_url_resolution": build_repository_url_resolution(
                status=URL_RESOLUTION_STATUS_UNRESOLVED,
                source=source,
                cache=cache_state,
                normalized=False,
                checked_at=checked_at,
                reason=invalid_url_reason,
            ),
        }

    return {
        "repository_url": "",
        "repository_url_resolution": build_repository_url_resolution(
            status=URL_RESOLUTION_STATUS_UNRESOLVED,
            source=source,
            cache=cache_state,
            normalized=False,
            checked_at=checked_at,
            reason=unresolved_reason,
        ),
    }


def _attempt_to_resolution_entry(attempt, cache_state, checked_at):
    """
    Finalize a source attempt dict into a resolver entry
    """
    return _finalize_url_attempt(
        raw_url=attempt.get("raw_url"),
        source=attempt["source"],
        cache_state=cache_state,
        checked_at=checked_at,
        unresolved_reason=attempt.get("reason") or URL_RESOLUTION_REASON_NO_REPOSITORY_URL,
    )


def _select_decisive_unresolved_entry(entries):
    """
    Pick the unresolved receipt that best represents a failed multi-attempt resolution
    """
    error_reasons = {
        URL_RESOLUTION_REASON_NETWORK_ERROR,
        URL_RESOLUTION_REASON_VALIDATION_REJECTED,
        URL_RESOLUTION_REASON_INVALID_REGISTRY_RESPONSE,
        URL_RESOLUTION_REASON_NORMALIZATION_FAILED,
        URL_RESOLUTION_REASON_RESOLVER_ERROR,
    }
    for entry in entries:
        receipt = entry["repository_url_resolution"]
        if receipt.get("reason") in error_reasons:
            return entry
    return entries[-1]


def _source_for_resolver_error(ecosystem):
    """
    Return the most accurate source taxonomy value for an unexpected resolver error
    """
    return {
        "npm": URL_RESOLUTION_SOURCE_NPM_REGISTRY,
        "pypi": URL_RESOLUTION_SOURCE_PYPI_REGISTRY,
        "cargo": URL_RESOLUTION_SOURCE_CRATES_IO,
        "go": URL_RESOLUTION_SOURCE_GO_GET_META,
        "solidity": URL_RESOLUTION_SOURCE_SOLIDITY_SOURCE_HINT,
    }.get(ecosystem, URL_RESOLUTION_SOURCE_UNSUPPORTED_ECOSYSTEM)


def _resolve_package_url_receipt(package_name, package_data, logger, cache_state, checked_at):
    """
    Resolve one package to a canonical resolver entry
    """
    ecosystem = package_data.get("ecosystem", "unknown")
    attempts = []

    gitmodules_url_source = package_data.get("gitmodules_url")
    if gitmodules_url_source and isinstance(gitmodules_url_source, str):
        gitmodules_entry = _finalize_url_attempt(
            raw_url=gitmodules_url_source,
            source=URL_RESOLUTION_SOURCE_GITMODULES,
            cache_state=cache_state,
            checked_at=checked_at,
            unresolved_reason=URL_RESOLUTION_REASON_NORMALIZATION_FAILED,
        )
        if gitmodules_entry["repository_url"]:
            logger and logger.info(f"Resolved {package_name} using .gitmodules URL: {gitmodules_entry['repository_url']}")
            return gitmodules_entry
        attempts.append(gitmodules_entry)

    try:
        if ecosystem == "npm":
            attempts.append(_attempt_to_resolution_entry(_resolve_npm_package_attempt(package_name, logger), cache_state, checked_at))
        elif ecosystem == "pypi":
            attempts.append(_attempt_to_resolution_entry(_resolve_pypi_package_attempt(package_name, logger), cache_state, checked_at))
        elif ecosystem == "cargo":
            attempts.append(_attempt_to_resolution_entry(_resolve_cargo_package_attempt(package_name, logger), cache_state, checked_at))
        elif ecosystem == "go":
            attempts.append(_attempt_to_resolution_entry(_resolve_go_package_attempt(package_name, logger), cache_state, checked_at))
        elif ecosystem == "solidity":
            attempts.extend(
                _attempt_to_resolution_entry(attempt, cache_state, checked_at)
                for attempt in _resolve_solidity_package_attempts(package_name, package_data, logger)
            )
        else:
            attempts.append(
                _finalize_url_attempt(
                    raw_url=None,
                    source=URL_RESOLUTION_SOURCE_UNSUPPORTED_ECOSYSTEM,
                    cache_state=cache_state,
                    checked_at=checked_at,
                    unresolved_reason=URL_RESOLUTION_REASON_UNSUPPORTED_ECOSYSTEM,
                )
            )
    except Exception as e:
        logger and logger.warning(f"Error resolving URL for {package_name} ({ecosystem}): {e}")
        attempts.append(
            _finalize_url_attempt(
                raw_url=None,
                source=_source_for_resolver_error(ecosystem),
                cache_state=cache_state,
                checked_at=checked_at,
                unresolved_reason=URL_RESOLUTION_REASON_RESOLVER_ERROR,
            )
        )

    for entry in attempts:
        if entry["repository_url"]:
            logger and logger.debug(f"Resolved {package_name} ({ecosystem}) -> {entry['repository_url']}")
            return entry
    logger and logger.debug(f"Could not resolve URL for {package_name} ({ecosystem})")
    return _select_decisive_unresolved_entry(attempts)


def resolve_package_url_receipts(packages_dict, logger=None, cache=None, *, checked_at=None):
    """
    Resolve package names to repository URLs with canonical resolution receipts
    """
    receipt_checked_at = checked_at or utc_now_isoformat()
    cache_was_supplied = cache is not None
    cache_map = cache if cache_was_supplied else {}
    resolved_entries = {}

    for package_name, package_data in packages_dict.items():
        try:
            ecosystem = package_data.get("ecosystem", "unknown")
            cache_key = f"{ecosystem}:{package_name}"
            if cache_was_supplied and cache_key in cache_map:
                resolved_entries[package_name] = _finalize_url_attempt(
                    raw_url=cache_map[cache_key],
                    source=URL_RESOLUTION_SOURCE_CACHE,
                    cache_state=URL_RESOLUTION_CACHE_HIT,
                    checked_at=receipt_checked_at,
                    unresolved_reason=URL_RESOLUTION_REASON_INVALID_CACHE_ENTRY,
                    invalid_url_reason=URL_RESOLUTION_REASON_INVALID_CACHE_ENTRY,
                )
                logger and logger.debug(
                    f"Resolved {package_name} from cache -> {resolved_entries[package_name]['repository_url']}"
                )
                continue

            cache_state = URL_RESOLUTION_CACHE_MISS if cache_was_supplied else URL_RESOLUTION_CACHE_NOT_USED
            resolved_entries[package_name] = _resolve_package_url_receipt(
                package_name,
                package_data,
                logger,
                cache_state,
                receipt_checked_at,
            )
        except Exception as e:
            ecosystem = package_data.get("ecosystem", "unknown") if isinstance(package_data, dict) else "unknown"
            cache_state = URL_RESOLUTION_CACHE_MISS if cache_was_supplied else URL_RESOLUTION_CACHE_NOT_USED
            logger and logger.warning(f"Error resolving URL for {package_name} ({ecosystem}): {e}")
            resolved_entries[package_name] = _finalize_url_attempt(
                raw_url=None,
                source=_source_for_resolver_error(ecosystem),
                cache_state=cache_state,
                checked_at=receipt_checked_at,
                unresolved_reason=URL_RESOLUTION_REASON_RESOLVER_ERROR,
            )

    return resolved_entries


def resolve_package_urls(packages_dict, logger=None, cache=None):
    """
    Resolve package names to repository URLs for all ecosystems

    Args:
        packages_dict (dict): Dictionary of packages to resolve
        logger (Logger): Optional logger instance
        cache (dict): Optional pre-populated dictionary for URL caching

    Returns:
        Dictionary containing resolved package URLs
    """
    resolution_entries = resolve_package_url_receipts(packages_dict, logger=logger, cache=cache)
    return {
        package_name: entry["repository_url"]
        for package_name, entry in resolution_entries.items()
        if entry["repository_url"]
    }


def _npm_is_types_package(package_name):
    """
    Return DefinitelyTyped URL if package is '@types/*', else None

    Args:
        package_name (str): Package name

    Returns:
        str or None: URL if @types, else None
    """
    if package_name.startswith("@types/"):
        return "https://github.com/DefinitelyTyped/DefinitelyTyped"
    return None


def _npm_registry_url(package_name):
    """
    Return npm registry URL with '/' encoded as '%2F'

    Args:
        package_name (str): Package name

    Returns:
        str: Registry URL
    """
    safe_package_name = package_name.replace("/", "%2F")
    return f"https://registry.npmjs.org/{safe_package_name}"


def _npm_fetch_metadata(package_name, logger=None):
    """
    Use _make_request to fetch npm metadata JSON

    Args:
        package_name (str): Package name
        logger: Optional logger

    Returns:
        dict or None: Metadata
    """
    url = _npm_registry_url(package_name)
    return _make_request(url, logger)


def _npm_pick_version_metadata(data):
    """
    Return metadata dict for 'dist-tags.latest' version if present

    Args:
        data (dict): Registry data

    Returns:
        dict or None: Version metadata
    """
    latest_version = data.get("dist-tags", {}).get("latest")
    if latest_version and "versions" in data and latest_version in data["versions"]:
        return data["versions"][latest_version]
    return None


def _is_github_url(url_str):
    """
    Return whether a cleaned URL points at GitHub
    """
    parsed = _safe_urlsplit(url_str)
    return bool(parsed and (parsed.hostname or "").lower() == "github.com")


def _is_repository_host_url(url_str):
    """
    Return whether a cleaned URL points at a supported repository host
    """
    parsed = _safe_urlsplit(url_str)
    repository_hosts = {"github.com", "www.github.com", "gitlab.com", "www.gitlab.com"}
    return bool(parsed and (parsed.hostname or "").lower() in repository_hosts)


def _explicit_github_raw_candidate(candidate):
    """
    Return raw candidate only for explicit URL/SCM forms with an anchored GitHub host
    """
    if not isinstance(candidate, str):
        return None
    normalized = _normalize_git_prefixes(_strip_fragment(candidate))
    parsed = _safe_urlsplit(normalized)
    if parsed is None:
        return None
    has_explicit_scheme = parsed.scheme in {"http", "https", "ssh"}
    is_scp_like = normalized.startswith("git@github.com:")
    if not has_explicit_scheme and not is_scp_like:
        return None
    cleaned = _clean_repo_url(candidate)
    if cleaned and _is_github_url(cleaned):
        return candidate
    return None


def _npm_from_repository_raw(repo_info, logger=None):
    """
    Interpret 'repository' field and return a raw repository URL candidate
    """
    if not repo_info:
        return None
    logger and logger.debug("Repository metadata present")

    if isinstance(repo_info, dict):
        repo_url = repo_info.get("url")
        if isinstance(repo_url, str) and repo_url and _clean_repo_url(repo_url):
            return repo_url
        for key, value in repo_info.items():
            if key == "url":
                continue
            explicit_candidate = _explicit_github_raw_candidate(value)
            if explicit_candidate:
                return explicit_candidate
        if isinstance(repo_url, str) and repo_url:
            return repo_url
        return None

    if isinstance(repo_info, str):
        if repo_info.startswith("github:"):
            return f"https://github.com/{repo_info[7:]}"
        if repo_info:
            return repo_info
    return None


def _npm_cleanable_repository_raw(repo_info, logger=None):
    """
    Return a repository candidate immediately only when it can be normalized
    """
    raw_url = _npm_from_repository_raw(repo_info, logger)
    if raw_url and _clean_repo_url(raw_url):
        return raw_url
    return None


def _github_raw_candidate(candidate):
    """
    Return raw candidate only when it cleans to an actual GitHub URL
    """
    if not isinstance(candidate, str):
        return None
    cleaned = _clean_repo_url(candidate)
    if cleaned and _is_github_url(cleaned):
        return candidate
    return None


def _npm_from_bugs(bugs_info):
    """
    Extract raw GitHub URL candidate from 'bugs' dict or string

    Args:
        bugs_info: Bugs field value

    Returns:
        str or None
    """
    if not bugs_info:
        return None
    if isinstance(bugs_info, dict) and "url" in bugs_info:
        return _github_raw_candidate(bugs_info["url"])
    if isinstance(bugs_info, str):
        return _github_raw_candidate(bugs_info)
    return None


def _npm_from_homepage(homepage):
    """
    Extract raw GitHub URL candidate from 'homepage' string

    Args:
        homepage: Homepage field value

    Returns:
        str or None
    """
    return _github_raw_candidate(homepage)


def _npm_infer_from_scoped_text(package_name, data, logger=None):
    """
    For scoped packages, scan description/readme for URLs under same org

    Returns:
        Inferred https://github.com/<org>/<repo> URL or None
    """
    if not (package_name.startswith("@") and "/" in package_name):
        return None
    org = package_name.split("/")[0][1:]
    for field in ["description", "readme"]:
        content = data.get(field)
        if content and isinstance(content, str):
            matches = re.findall(r"https?://(?:www\.)?github\.com/([^/\s]+)/([^/\s]+)", content)
            for match_org, match_repo in matches:
                if match_org.lower() == org.lower():
                    logger and logger.debug(f"Found potential GitHub repo match: {match_org}/{match_repo}")
                    return f"https://github.com/{match_org}/{match_repo}"
    return None


def _url_from_attempt(attempt):
    """
    Project a raw attempt dict to a URL-only value for existing public helpers
    """
    return _attempt_to_resolution_entry(attempt, URL_RESOLUTION_CACHE_NOT_USED, utc_now_isoformat())["repository_url"] or None


def _resolve_npm_package_attempt(package_name, logger=None):
    """
    Resolve npm package to a raw URL attempt
    """
    u = _npm_is_types_package(package_name)
    if u:
        return {"raw_url": u, "source": URL_RESOLUTION_SOURCE_STATIC_RULE, "reason": None}

    if package_name.startswith("@docusaurus/"):
        return {
            "raw_url": "https://github.com/facebook/docusaurus",
            "source": URL_RESOLUTION_SOURCE_STATIC_RULE,
            "reason": None,
        }

    outcome = _make_request_outcome(_npm_registry_url(package_name), logger)
    data = outcome["data"]

    if not data:
        logger and logger.warning(f"No data returned from npm registry for {package_name}")
        return {
            "raw_url": None,
            "source": URL_RESOLUTION_SOURCE_NPM_REGISTRY,
            "reason": outcome["reason"] or URL_RESOLUTION_REASON_NO_DATA_RETURNED,
        }

    version_data = _npm_pick_version_metadata(data)
    invalid_repository_candidate = None

    for metadata in [version_data, data]:
        if not metadata:
            continue
        repository_info = metadata.get("repository")
        u = _npm_cleanable_repository_raw(repository_info, logger)
        if u:
            return {"raw_url": u, "source": URL_RESOLUTION_SOURCE_NPM_REGISTRY, "reason": None}
        if invalid_repository_candidate is None:
            invalid_repository_candidate = _npm_from_repository_raw(repository_info, logger)
        u = _npm_from_bugs(metadata.get("bugs"))
        if u:
            return {"raw_url": u, "source": URL_RESOLUTION_SOURCE_NPM_REGISTRY, "reason": None}
        u = _npm_from_homepage(metadata.get("homepage"))
        if u:
            return {"raw_url": u, "source": URL_RESOLUTION_SOURCE_NPM_REGISTRY, "reason": None}

    u = _npm_infer_from_scoped_text(package_name, data, logger)
    if u:
        return {"raw_url": u, "source": URL_RESOLUTION_SOURCE_NPM_REGISTRY, "reason": None}

    if invalid_repository_candidate:
        return {"raw_url": invalid_repository_candidate, "source": URL_RESOLUTION_SOURCE_NPM_REGISTRY, "reason": None}

    logger and logger.debug(f"Couldn't resolve GitHub URL for {package_name}")
    return {
        "raw_url": None,
        "source": URL_RESOLUTION_SOURCE_NPM_REGISTRY,
        "reason": URL_RESOLUTION_REASON_NO_REPOSITORY_URL,
    }


def resolve_npm_package(package_name, logger=None):
    """
    Resolve npm package to repository URL

    Args:
        package_name (str): The NPM package name to resolve
        logger (Logger): Optional logger instance

    Returns:
        Repository URL string or None if not found
    """
    return _url_from_attempt(_resolve_npm_package_attempt(package_name, logger))


def _pep503_normalize(name):
    """
    Normalize distribution name per PEP 503 (simple repository API)

    Args:
        name (str): Candidate name

    Returns:
        str: normalized name (lowercased, runs of [-_.]+ collapsed to '-')
    """
    if not isinstance(name, str):
        return name
    # Collapse runs of -, _, . into '-'; lowercase
    return re.sub(r"[-_.]+", "-", name.strip()).lower()


def _pypi_extract_info(data):
    """
    Return 'info' dict from PyPI metadata or {}

    Args:
        data (dict): PyPI metadata

    Returns:
        dict
    """
    return data.get("info", {}) if data else {}


def _pypi_lowercase_urls(project_urls, logger, package_name):
    """
    Lowercase keys and log the original keys exactly as today

    Args:
        project_urls (dict): Project URLs
        logger: Optional logger
        package_name (str): Package name for logging

    Returns:
        dict: lowercase-keyed project URLs
    """
    project_urls = project_urls or {}
    lowercase_urls = {k.lower(): v for k, v in project_urls.items()}
    logger and logger.debug(f"Project URL keys for {package_name}: {list(project_urls.keys())}")
    return lowercase_urls


def _pypi_preferred_url_raw(lowercase_urls):
    """
    Iterate preferred keys and return a raw GitHub/GitLab URL candidate if any
    """
    preferred_keys = [
        "repository",
        "source",
        "source code",
        "github",
        "repo",
        "code",
        "code repository",
        "vc",
        "homepage",
        "home",
    ]
    for key in preferred_keys:
        raw_url = lowercase_urls.get(key)
        cleaned = _clean_repo_url(raw_url)
        if cleaned and _is_repository_host_url(cleaned):
            return raw_url
    return None


def _pypi_home_page_raw(info):
    """
    Return raw 'home_page' URL if it cleans to GitHub/GitLab, else None
    """
    raw_homepage = info.get("home_page")
    homepage = _clean_repo_url(raw_homepage)
    if homepage and _is_repository_host_url(homepage):
        return raw_homepage
    return None


def _pypi_find_any_repo_in_urls_raw(lowercase_urls):
    """
    Scan all project_urls values for a raw GitHub/GitLab URL candidate
    """
    if not lowercase_urls:
        return None
    for raw_url in lowercase_urls.values():
        u = _clean_repo_url(raw_url)
        if isinstance(u, str) and _is_repository_host_url(u):
            return raw_url
    return None


def _resolve_pypi_package_attempt(package_name, logger=None):
    """
    Resolve PyPI package to a raw URL attempt
    """
    outcome = _make_request_outcome(f"https://pypi.org/pypi/{_pep503_normalize(package_name)}/json", logger)
    data = outcome["data"]
    if not data:
        return {
            "raw_url": None,
            "source": URL_RESOLUTION_SOURCE_PYPI_REGISTRY,
            "reason": outcome["reason"] or URL_RESOLUTION_REASON_NO_DATA_RETURNED,
        }

    info = _pypi_extract_info(data)
    lowercase_urls = _pypi_lowercase_urls(info.get("project_urls") or {}, logger, package_name)

    preferred = _pypi_preferred_url_raw(lowercase_urls)
    if preferred:
        return {"raw_url": preferred, "source": URL_RESOLUTION_SOURCE_PYPI_REGISTRY, "reason": None}

    homepage = _pypi_home_page_raw(info)
    if homepage:
        return {"raw_url": homepage, "source": URL_RESOLUTION_SOURCE_PYPI_REGISTRY, "reason": None}

    any_repo = _pypi_find_any_repo_in_urls_raw(lowercase_urls)
    if any_repo:
        return {"raw_url": any_repo, "source": URL_RESOLUTION_SOURCE_PYPI_REGISTRY, "reason": None}

    special = {
        "vispy": "https://github.com/vispy/vispy",
    }
    if package_name in special:
        return {"raw_url": special[package_name], "source": URL_RESOLUTION_SOURCE_STATIC_RULE, "reason": None}

    return {
        "raw_url": None,
        "source": URL_RESOLUTION_SOURCE_PYPI_REGISTRY,
        "reason": URL_RESOLUTION_REASON_NO_REPOSITORY_URL,
    }


def resolve_pypi_package(package_name, logger=None):
    """
    Resolve PyPI package to repository URL

    Args:
        package_name (str): The PyPI package name to resolve
        logger (Logger): Optional logger instance

    Returns:
        Repository URL string or None if not found
    """
    return _url_from_attempt(_resolve_pypi_package_attempt(package_name, logger))


def _cargo_from_documentation(crate):
    """
    Infer repo from GitHub/GitLab Pages documentation URL patterns

    Args:
        crate (dict): Crate metadata

    Returns:
        str or None
    """
    if not crate:
        return None
    documentation = crate.get("documentation")
    if documentation and isinstance(documentation, str):
        match_gh_pages = _RE_GH_PAGES.match(documentation)
        if match_gh_pages:
            user, repo = match_gh_pages.groups()
            return f"https://github.com/{user}/{repo}"
        match_gl_pages = _RE_GL_PAGES.match(documentation)
        if match_gl_pages:
            user, repo = match_gl_pages.groups()
            return f"https://gitlab.com/{user}/{repo}"
    return None


def _cargo_from_repository_raw(crate):
    """
    Return raw 'repository' URL if it can be cleaned
    """
    raw_url = crate.get("repository") if crate else None
    return raw_url if _clean_repo_url(raw_url) else None


def _cargo_from_homepage_raw(crate):
    """
    Return raw 'homepage' URL if it cleans to an anchored GitHub/GitLab repository
    """
    if not crate:
        return None
    raw_homepage = crate.get("homepage")
    homepage = _clean_repo_url(raw_homepage)
    if homepage and _is_repository_host_url(homepage):
        return raw_homepage
    return None


def _resolve_cargo_package_attempt(package_name, logger=None):
    """
    Resolve Cargo crate to a raw URL attempt
    """
    outcome = _make_request_outcome(f"https://crates.io/api/v1/crates/{package_name}", logger)
    data = outcome["data"]
    if not data:
        return {
            "raw_url": None,
            "source": URL_RESOLUTION_SOURCE_CRATES_IO,
            "reason": outcome["reason"] or URL_RESOLUTION_REASON_NO_DATA_RETURNED,
        }

    crate = data.get("crate", {})
    repository = _cargo_from_repository_raw(crate)
    if repository:
        return {"raw_url": repository, "source": URL_RESOLUTION_SOURCE_CRATES_IO, "reason": None}

    homepage = _cargo_from_homepage_raw(crate)
    if homepage:
        return {"raw_url": homepage, "source": URL_RESOLUTION_SOURCE_CRATES_IO, "reason": None}

    inferred = _cargo_from_documentation(crate)
    if inferred:
        return {"raw_url": inferred, "source": URL_RESOLUTION_SOURCE_CRATES_IO, "reason": None}

    return {
        "raw_url": None,
        "source": URL_RESOLUTION_SOURCE_CRATES_IO,
        "reason": URL_RESOLUTION_REASON_NO_REPOSITORY_URL,
    }


def resolve_cargo_package(package_name, logger=None):
    """
    Resolve Cargo crate to repository URL

    Args:
        package_name (str): The Cargo crate name to resolve
        logger (Logger): Optional logger instance

    Returns:
        Repository URL string or None if not found
    """
    return _url_from_attempt(_resolve_cargo_package_attempt(package_name, logger))


def _go_direct_repo_from_path(package_name):
    """
    Infer https URL from import path containing github.com/ or gitlab.com/

    Args:
        package_name (str): Go import path

    Returns:
        str or None: 'https://<host>/<org>/<repo>' or None
    """
    parts = package_name.split("/")
    if len(parts) >= 3 and parts[0] in {"github.com", "gitlab.com"}:
        return f"https://{parts[0]}/{parts[1]}/{parts[2]}"
    return None


def _go_meta_tag_fetch_url(package_name):
    """
    Return 'https://{package_name}?go-get=1'

    Args:
        package_name (str): Go import path

    Returns:
        str: URL to fetch meta tags
    """
    return f"https://{package_name}?go-get=1"


def _go_meta_tag_outcome(fetch_url, logger=None):
    """
    Fetch Go go-import HTML metadata without JSON registry-domain validation
    """
    if SECURITY_AVAILABLE:
        try:
            fetch_url = InputValidator.validate_url(fetch_url, allowed_schemes={"https"})
        except ValidationError as e:
            logger and logger.debug(f"Go package URL validation failed: {fetch_url} - {e}")
            return {"raw_url": None, "reason": URL_RESOLUTION_REASON_VALIDATION_REJECTED}

    if _REQUEST_FN is not None:
        try:
            raw = _REQUEST_FN(fetch_url)
            if raw is None:
                return {"raw_url": None, "reason": URL_RESOLUTION_REASON_NO_DATA_RETURNED}
            content = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
            match = _RE_GO_IMPORT_META.search(content)
            if match:
                return {"raw_url": match.group(3), "reason": None}
            return {"raw_url": None, "reason": URL_RESOLUTION_REASON_NO_DATA_RETURNED}
        except Exception as e:
            logger and logger.debug(f"Go package lookup via 'go-get=1' failed for {fetch_url}: {e}")
            return {"raw_url": None, "reason": URL_RESOLUTION_REASON_NETWORK_ERROR}

    req = urllib.request.Request(fetch_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
            if response.status == 200:
                content = response.read().decode("utf-8", errors="ignore")
                match = _RE_GO_IMPORT_META.search(content)
                if match:
                    return {"raw_url": match.group(3), "reason": None}
            if response.status == 404:
                return {"raw_url": None, "reason": URL_RESOLUTION_REASON_NO_DATA_RETURNED}
            return {"raw_url": None, "reason": URL_RESOLUTION_REASON_NETWORK_ERROR}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"raw_url": None, "reason": URL_RESOLUTION_REASON_NO_DATA_RETURNED}
        logger and logger.debug(f"Go package lookup via 'go-get=1' failed for {fetch_url}: {e}")
        return {"raw_url": None, "reason": URL_RESOLUTION_REASON_NETWORK_ERROR}
    except Exception as e:
        logger and logger.debug(f"Go package lookup via 'go-get=1' failed for {fetch_url}: {e}")
        return {"raw_url": None, "reason": URL_RESOLUTION_REASON_NETWORK_ERROR}


def _resolve_go_package_attempt(package_name, logger=None):
    """
    Resolve Go package to a raw URL attempt
    """
    direct = _go_direct_repo_from_path(package_name)
    if direct:
        return {"raw_url": direct, "source": URL_RESOLUTION_SOURCE_GO_IMPORT_PATH, "reason": None}

    fetch_url = _go_meta_tag_fetch_url(package_name)
    outcome = _go_meta_tag_outcome(fetch_url, logger)
    return {
        "raw_url": outcome["raw_url"],
        "source": URL_RESOLUTION_SOURCE_GO_GET_META,
        "reason": outcome["reason"] or URL_RESOLUTION_REASON_NO_DATA_RETURNED,
    }


def resolve_go_package(package_name, logger=None):
    """
    Resolve Go package to repository URL

    Args:
        package_name (str): The Go package name to resolve
        logger (Logger): Optional logger instance

    Returns:
        Repository URL string or None if not found
    """
    return _url_from_attempt(_resolve_go_package_attempt(package_name, logger))


def _resolve_solidity_contract_attempt(package_name, source=None, logger=None):
    """
    Resolve Solidity contract/library to a raw URL attempt from a source hint
    """
    if source:
        cleaned_source = _clean_repo_url(source)
        if cleaned_source and _is_repository_host_url(cleaned_source):
            return {"raw_url": source, "source": URL_RESOLUTION_SOURCE_SOLIDITY_SOURCE_HINT, "reason": None}

    logger and logger.debug(f"No direct source hint or specific resolver for Solidity package: {package_name}")
    return {
        "raw_url": None,
        "source": URL_RESOLUTION_SOURCE_SOLIDITY_SOURCE_HINT,
        "reason": URL_RESOLUTION_REASON_NO_REPOSITORY_URL,
    }


def _resolve_solidity_package_attempts(package_name, package_data, logger=None):
    """
    Resolve Solidity package through npm when appropriate, then source hints
    """
    attempts = []
    if not _is_solidity_alias_like(package_name):
        attempts.append(_resolve_npm_package_attempt(package_name, logger))
    attempts.append(_resolve_solidity_contract_attempt(package_name, package_data.get("source"), logger))
    return attempts


def resolve_solidity_contract(package_name, source=None, logger=None):
    """
    Resolve Solidity contract/library to repository URL

    Args:
        package_name (str): The Solidity package name to resolve
        source (str): Optional source URL hint
        logger (Logger): Optional logger instance

    Returns:
        Repository URL string or None if not found
    """
    return _url_from_attempt(_resolve_solidity_contract_attempt(package_name, source, logger))
