"""
Shared utility functions for the Gardener microservice
"""

import re
from urllib.parse import urlparse


def normalize_drip_list(items, max_length=200, analyzed_repo_url=None):
    """
    Backwards-compatible façade around the drip list processing pipeline

    Args:
        items (list): List of dictionaries containing 'percentage' key
        max_length (int): Maximum number of dependencies to return in normalized list
        analyzed_repo_url (str): The canonical URL of the repository being analyzed, to
                                 filter out self-references

    Returns:
        List of dictionaries with normalized 'split_percentage' key
    """
    # Lazy import to avoid circular dependency
    from services.shared.drip_list_processor import build_normalized_drip_list

    return build_normalized_drip_list(items, max_length, analyzed_repo_url)


def canonicalize_repo_url(url):
    """
    Converts various Git URL formats to 'host/owner/repo'

    Args:
        url (str): Git repository URL in any format

    Returns:
        str: Canonicalized URL in format 'host/owner/repo'

    Raises:
        ValueError: If URL format cannot be parsed
    """
    url = url.lower().strip()

    # Handle 'github.com/owner/repo' without scheme, or generic 'host/owner/repo'
    if url.startswith("github.com/"):
        url = "https://" + url
    elif re.match(r"^[\w\.-]+\.[\w\.-]+/[\w\.-]+/[\w\.-]+", url):
        url = "https://" + url

    # Handle git@host:path/repo.git format
    if url.startswith("git@"):
        url = "https://" + url[4:].replace(":", "/", 1)

    # Use urlparse for robust handling of protocols and paths
    parsed = urlparse(url)
    host = parsed.netloc.replace("www.", "")
    path = re.sub(r"\.git$", "", parsed.path.strip("/"))

    if not host:
        # Handle scp-like syntax that urlparse misses e.g., 'github.com:user/repo.git'
        if ":" in url and "/" in url and url.find(":") < url.find("/"):
            host, path = url.split(":", 1)
            path = path.strip("/")
        else:
            raise ValueError("Could not determine host from URL")

    return f"{host}/{path}"
