"""
Package resolution methods
"""

import json
import re
import time
import urllib.error
import urllib.request

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
_RE_GH_OWNER_REPO_COLON_OR_SLASH = re.compile(r"github\.com[:/]([^/\s]+/[^/\s]+?)(?:\.git)?(?:\s|$)")
_RE_GH_OWNER_REPO_SLASH = re.compile(r"github\.com/([^/]+/[^/]+)")
_RE_GH_PAGES = re.compile(r"https?://([^/]+)\.github\.io/([^/]+)")
_RE_GL_PAGES = re.compile(r"https?://([^/]+)\.gitlab\.io/([^/]+)")
_RE_GO_IMPORT_META = re.compile(
    r'<meta\s+name=["\']go-import["\']\s+content=["\']([^ ]+)\s+(git|hg|svn|bzr)\s+([^"\']+)["\']', re.IGNORECASE
)
_RE_GH_CANONICAL = re.compile(r"(https?://(?:www\.)?github\.com/[^/]+/[^/]+)")
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
    # Validate URL for security
    validated = _validate_or_none(url, logger)
    if validated is None:
        return None
    url = validated

    last_exception = None
    delay = RETRY_DELAY
    for attempt in range(RETRY_COUNT + 1):
        try:
            status, data, single_error = _request_once(url, logger)
            if status == 200:
                return data
            if status == 404:
                logger and logger.debug(f"Package not found (404): {url}")
                return None
            if status is not None:
                last_exception = single_error
                logger and logger.warning(f"HTTP error {status} for {url} (attempt {attempt + 1}/{RETRY_COUNT + 1})")

        except urllib.error.HTTPError as e:
            last_exception = e
            if e.code == 404:
                logger and logger.debug(f"Package not found (404): {url}")
                return None  # Explicitly return None on 404
            logger and logger.warning(
                f"HTTP error {e.code} for {url} " f"(attempt {attempt + 1}/{RETRY_COUNT + 1}): {e.reason}"
            )
        except Exception as e:
            last_exception = e
            logger and logger.warning(f"Error fetching {url} (attempt {attempt + 1}/{RETRY_COUNT + 1}): {e}")

        if attempt < RETRY_COUNT:
            logger and logger.debug(f"Retrying in {delay}s...")
            time.sleep(delay)
            delay *= 2  # Exponential backoff

    logger and logger.error(f"Failed to fetch {url} after {RETRY_COUNT + 1} attempts. Last error: {last_exception}")
    return None


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
    if "github.com" in url_str:
        match = _RE_GH_CANONICAL.match(url_str)
        if match:
            return match.group(1)
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
    u = _extract_github_owner_repo(u)
    u = _strip_dot_git(u)

    if u.startswith("http://") or u.startswith("https://"):
        return u

    assumed = _assume_github_from_owner_repo_shorthand(u)
    if assumed:
        return assumed

    return None


# Main resolution logic:


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
    resolved_urls = {}
    cache = cache or {}

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

    for package_name, package_data in packages_dict.items():
        ecosystem = package_data.get("ecosystem", "unknown")
        url = None

        # Check cache first
        cache_key = f"{ecosystem}:{package_name}"
        if cache_key in cache:
            resolved_urls[package_name] = cache[cache_key]
            logger and logger.debug(f"Resolved {package_name} from cache -> {cache[cache_key]}")
            continue

        # Attempt to resolve using .gitmodules URL first
        gitmodules_url_source = package_data.get("gitmodules_url")
        if gitmodules_url_source and isinstance(gitmodules_url_source, str):
            cleaned_gitmodules_url = _clean_repo_url(gitmodules_url_source)
            if cleaned_gitmodules_url:
                url = cleaned_gitmodules_url
                logger and logger.info(f"Resolved {package_name} using .gitmodules URL: {url}")

        # If URL was not resolved from gitmodules, proceed with ecosystem-specific resolution
        if not url:
            try:
                if ecosystem == "npm":
                    url = resolve_npm_package(package_name, logger)
                elif ecosystem == "pypi":
                    url = resolve_pypi_package(package_name, logger)
                elif ecosystem == "cargo":
                    url = resolve_cargo_package(package_name, logger)
                elif ecosystem == "go":
                    url = resolve_go_package(package_name, logger)
                elif ecosystem == "solidity":
                    # Solidity often uses npm. Avoid lookups for alias-like names.
                    if not _is_solidity_alias_like(package_name):
                        url = resolve_npm_package(package_name, logger)
                    if not url:
                        # Placeholder for potential Etherscan/Sourcegraph resolution
                        url = resolve_solidity_contract(package_name, package_data.get("source"), logger)
            except Exception as e:
                logger and logger.warning(f"Error resolving URL for {package_name} ({ecosystem}): {e}")

        if url:
            # Clean the resolved URL before storing
            cleaned_url = _clean_repo_url(url)
            if cleaned_url:
                resolved_urls[package_name] = cleaned_url
                logger and logger.debug(f"Resolved {package_name} ({ecosystem}) -> {cleaned_url}")
            else:
                logger and logger.debug(f"Could not clean URL for {package_name} ({ecosystem}): {url}")
        else:
            logger and logger.debug(f"Could not resolve URL for {package_name} ({ecosystem})")

    return resolved_urls


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


def _npm_from_repository(repo_info, logger=None):
    """
    Interpret 'repository' field (dict or str) to a GitHub/GitLab URL

    Returns:
        Cleaned URL or None
    """
    if not repo_info:
        return None
    logger and logger.debug(f"Repository info: {repo_info}")

    if isinstance(repo_info, dict):
        repo_url = _clean_repo_url(repo_info.get("url"))
        if repo_url:
            return repo_url
        for key, value in repo_info.items():
            if isinstance(value, str) and "github.com" in value:
                match = _RE_GH_OWNER_REPO_COLON_OR_SLASH.search(value)
                if match:
                    return f"https://github.com/{match.group(1)}"
        return None

    if isinstance(repo_info, str):
        repo_url = _clean_repo_url(repo_info)
        if repo_url:
            return repo_url
        if "github.com" in repo_info:
            match = _RE_GH_OWNER_REPO_COLON_OR_SLASH.search(repo_info)
            if match:
                return f"https://github.com/{match.group(1)}"
        elif repo_info.startswith("github:"):
            return f"https://github.com/{repo_info[7:]}"
    return None


def _npm_from_bugs(bugs_info):
    """
    Extract GitHub URL from 'bugs' dict or string using existing regex

    Args:
        bugs_info: Bugs field value

    Returns:
        str or None
    """
    if not bugs_info:
        return None
    if isinstance(bugs_info, dict) and "url" in bugs_info:
        bugs_url = bugs_info["url"]
        if isinstance(bugs_url, str) and "github.com" in bugs_url:
            match = _RE_GH_OWNER_REPO_SLASH.search(bugs_url)
            if match:
                return f"https://github.com/{match.group(1)}"
    elif isinstance(bugs_info, str) and "github.com" in bugs_info:
        match = _RE_GH_OWNER_REPO_SLASH.search(bugs_info)
        if match:
            return f"https://github.com/{match.group(1)}"
    return None


def _npm_from_homepage(homepage):
    """
    Extract GitHub URL from 'homepage' string using existing regex

    Args:
        homepage: Homepage field value

    Returns:
        str or None
    """
    if homepage and isinstance(homepage, str) and "github.com" in homepage:
        match = _RE_GH_OWNER_REPO_SLASH.search(homepage)
        if match:
            return f"https://github.com/{match.group(1)}"
    return None


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


def resolve_npm_package(package_name, logger=None):
    """
    Resolve npm package to repository URL

    Args:
        package_name (str): The NPM package name to resolve
        logger (Logger): Optional logger instance

    Returns:
        Repository URL string or None if not found
    """
    # Special handling for TypeScript definition packages (@types/*)
    u = _npm_is_types_package(package_name)
    if u:
        return u

    # Fast-path: known monorepo scope fallback when registry metadata is incomplete
    if package_name.startswith("@docusaurus/"):
        return "https://github.com/facebook/docusaurus"

    data = _npm_fetch_metadata(package_name, logger)

    if not data:
        logger and logger.warning(f"No data returned from npm registry for {package_name}")
        return None

    version_data = _npm_pick_version_metadata(data)

    # Try to find repository information in version metadata first, then fall back to top-level
    for metadata in [version_data, data]:
        if not metadata:
            continue
        u = _npm_from_repository(metadata.get("repository"), logger)
        if u:
            return u
        u = _npm_from_bugs(metadata.get("bugs"))
        if u:
            return u
        u = _npm_from_homepage(metadata.get("homepage"))
        if u:
            return u

    # 4. Infer from package name for other scoped packages
    u = _npm_infer_from_scoped_text(package_name, data, logger)
    if u:
        return u

    logger and logger.debug(f"Couldn't resolve GitHub URL for {package_name}")
    return None


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


def _pypi_fetch_metadata(package_name, logger=None):
    """
    Fetch PyPI metadata JSON using _make_request

    Args:
        package_name (str): Package name
        logger: Optional logger

    Returns:
        dict or None
    """
    normalized = _pep503_normalize(package_name)
    url = f"https://pypi.org/pypi/{normalized}/json"
    return _make_request(url, logger)


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


def _pypi_preferred_url(lowercase_urls):
    """
    Iterate preferred keys and return cleaned GitHub/GitLab URL if any

    Args:
        lowercase_urls (dict): Lowercased project URLs

    Returns:
        str or None
    """
    preferred_keys = [
        "repository",
        "source",
        "source code",
        "github",
        # Common alternatives seen in the wild
        "repo",
        "code",
        "code repository",
        "vc",
        # Fall back to homepage after these
        "homepage",
        "home",
    ]
    for key in preferred_keys:
        proj_url = _clean_repo_url(lowercase_urls.get(key))
        if proj_url and ("github.com" in proj_url or "gitlab.com" in proj_url):
            return proj_url
    return None


def _pypi_home_page(info):
    """
    Return cleaned 'home_page' URL if it is GitHub/GitLab, else None

    Args:
        info (dict): Info dict from PyPI

    Returns:
        str or None
    """
    homepage = _clean_repo_url(info.get("home_page"))
    if homepage and ("github.com" in homepage or "gitlab.com" in homepage):
        return homepage
    return None


def _pypi_find_any_repo_in_urls(lowercase_urls):
    """
    Scan all project_urls values for a GitHub/GitLab URL regardless of key

    Args:
        lowercase_urls (dict): Lowercased project URLs

    Returns:
        str or None
    """
    if not lowercase_urls:
        return None
    for v in lowercase_urls.values():
        u = _clean_repo_url(v)
        if isinstance(u, str) and ("github.com" in u or "gitlab.com" in u):
            return u
    return None


def resolve_pypi_package(package_name, logger=None):
    """
    Resolve PyPI package to repository URL

    Args:
        package_name (str): The PyPI package name to resolve
        logger (Logger): Optional logger instance

    Returns:
        Repository URL string or None if not found
    """
    data = _pypi_fetch_metadata(package_name, logger)
    if not data:
        return None

    info = _pypi_extract_info(data)

    # Prioritize common repo URLs in project_urls
    lowercase_urls = _pypi_lowercase_urls(info.get("project_urls") or {}, logger, package_name)

    # Prefer explicit repo/source keys first
    preferred = _pypi_preferred_url(lowercase_urls)
    if preferred:
        return preferred

    # Fallback to top-level home_page
    homepage = _pypi_home_page(info)
    if homepage:
        return homepage

    # As a final attempt, scan any project_urls value for a GitHub/GitLab link
    any_repo = _pypi_find_any_repo_in_urls(lowercase_urls)
    if any_repo:
        return any_repo

    # Targeted fallbacks for well-known projects missing metadata on PyPI
    special = {
        "vispy": "https://github.com/vispy/vispy",
    }
    if package_name in special:
        return special[package_name]

    return None


def _cargo_fetch_metadata(package_name, logger=None):
    """
    Fetch crates.io metadata JSON using _make_request

    Args:
        package_name (str): Crate name
        logger: Optional logger

    Returns:
        dict or None
    """
    url = f"https://crates.io/api/v1/crates/{package_name}"
    return _make_request(url, logger)


def _cargo_from_repository(crate):
    """
    Return cleaned 'repository' URL if present

    Args:
        crate (dict): Crate metadata

    Returns:
        str or None
    """
    return _clean_repo_url(crate.get("repository")) if crate else None


def _cargo_from_homepage(crate):
    """
    Return cleaned 'homepage' URL if it matches anchored owner/repo regex

    Args:
        crate (dict): Crate metadata

    Returns:
        str or None
    """
    if not crate:
        return None
    homepage = _clean_repo_url(crate.get("homepage"))
    if homepage and ("github.com" in homepage or "gitlab.com" in homepage):
        if re.match(r"https?://(?:www\.)?(?:github|gitlab)\.com/[^/]+/[^/]+/?$", homepage):
            return homepage
    return None


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


def resolve_cargo_package(package_name, logger=None):
    """
    Resolve Cargo crate to repository URL

    Args:
        package_name (str): The Cargo crate name to resolve
        logger (Logger): Optional logger instance

    Returns:
        Repository URL string or None if not found
    """
    data = _cargo_fetch_metadata(package_name, logger)  # User-Agent is handled by helper

    if data:
        crate = data.get("crate", {})

        # 1. Try repository field
        repository = _cargo_from_repository(crate)
        if repository:
            return repository

        # 2. Try homepage field
        homepage = _cargo_from_homepage(crate)
        if homepage:
            return homepage

        # 3. Try to infer from documentation URL (less reliable)
        inferred = _cargo_from_documentation(crate)
        if inferred:
            return inferred

    return None


def _go_direct_repo_from_path(package_name):
    """
    Infer https URL from import path containing github.com/ or gitlab.com/

    Args:
        package_name (str): Go import path

    Returns:
        str or None: 'https://<host>/<org>/<repo>' or None
    """
    if "github.com/" in package_name or "gitlab.com/" in package_name:
        parts = package_name.split("/")
        if len(parts) >= 3:
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


def _go_meta_tag_repo_url(fetch_url, logger=None):
    """
    Request page and extract repo URL from go-import meta tag using _RE_GO_IMPORT_META
    Return cleaned URL or None

    Args:
        fetch_url (str): Validated URL to fetch
        logger: Optional logger

    Returns:
        str or None
    """
    # Use hook if present to fetch HTML content
    if _REQUEST_FN is not None:
        try:
            raw = _REQUEST_FN(fetch_url)
            if raw is None:
                return None
            if isinstance(raw, bytes):
                content = raw.decode("utf-8", errors="ignore")
            else:
                content = str(raw)
            match = _RE_GO_IMPORT_META.search(content)
            if match:
                repo_url = _clean_repo_url(match.group(3))
                if repo_url:
                    return repo_url
            return None
        except Exception:
            return None

    req = urllib.request.Request(fetch_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        if response.status == 200:
            content = response.read().decode("utf-8", errors="ignore")
            match = _RE_GO_IMPORT_META.search(content)
            if match:
                repo_url = _clean_repo_url(match.group(3))
                if repo_url:
                    return repo_url
    return None


def resolve_go_package(package_name, logger=None):
    """
    Resolve Go package to repository URL

    Args:
        package_name (str): The Go package name to resolve
        logger (Logger): Optional logger instance

    Returns:
        Repository URL string or None if not found
    """
    # For Go packages, the import path often IS the repo URL path
    direct = _go_direct_repo_from_path(package_name)
    if direct:
        return direct

    # Attempting the go-get=1 meta tag approach
    try:
        fetch_url = _go_meta_tag_fetch_url(package_name)

        # Validate URL for security
        if SECURITY_AVAILABLE:
            try:
                validated_url = InputValidator.validate_url(fetch_url, allowed_schemes={"https"})
                fetch_url = validated_url
            except ValidationError as e:
                logger and logger.debug(f"Go package URL validation failed: {fetch_url} - {e}")
                return None

        inferred = _go_meta_tag_repo_url(fetch_url, logger)
        if inferred:
            return inferred
    except Exception as e:
        logger and logger.debug(f"Go package lookup via 'go-get=1' failed for {package_name}: {e}")
        pass

    return None  # If direct URL and go-get meta tag failed


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
    # If source is provided (e.g., from foundry.toml), use it
    # 1. Use source hint if provided and valid
    if source:
        cleaned_source = _clean_repo_url(source)
        if cleaned_source and ("github.com" in cleaned_source or "gitlab.com" in cleaned_source):
            return cleaned_source

    # 2. Placeholder for future Etherscan/Sourcegraph/etc. API integration
    # For now, we rely on npm resolution which is attempted earlier in resolve_package_urls
    logger and logger.debug(f"No direct source hint or specific resolver for Solidity package: {package_name}")
    return None
