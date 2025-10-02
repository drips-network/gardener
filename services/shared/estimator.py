"""
Minimalistic duration estimator from GitHub metadata

Computes a best-effort prediction of total analysis duration using a
parsimonious log-linear model loaded from the DURATION_MODEL_JSON
environment variable. Feature values are gathered via two fast GitHub
API calls per repository: `/languages` and root `/contents`.
"""

import json
import math
import os
import time
from decimal import Decimal

import requests

from services.shared.utils import canonicalize_repo_url

# Constants
GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
MODEL_ENV = "DURATION_MODEL_JSON"

# Supported language set mirrors Gardener core support
SUPPORTED_LANGS = {"JavaScript", "TypeScript", "Python", "Go", "Rust", "Solidity"}

# Root-level manifest filenames to scan in /contents response
ROOT_FILENAMES = {
    "package.json",
    "tsconfig.json",
    "jsconfig.json",
    "go.mod",
    "Cargo.toml",
    "foundry.toml",
    "remappings.txt",
    "hardhat.config.js",
    "hardhat.config.ts",
    "hardhat.config.cjs",
    "hardhat.config.mjs",
    "requirements.txt",
    "requirements-dev.txt",
    "dev-requirements.txt",
    "requirements-test.txt",
    "requirements-pinned.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "Pipfile.lock",
    "environment.yml",
    "environment.yaml",
}


def _gh_headers():
    """
    Build GitHub request headers with optional auth

    Returns:
        dict: Headers for GitHub API requests
    """
    token = os.getenv(GITHUB_TOKEN_ENV, "")
    hdr = {"Accept": "application/vnd.github+json", "User-Agent": "gardener-estimator/1.0"}
    if token:
        hdr["Authorization"] = f"Bearer {token}"
    return hdr


def _parse_owner_repo(url):
    """
    Convert repo URL to GitHub (owner, repo)

    Args:
        url (str): Repository URL in any accepted form

    Returns:
        tuple[str,str]: (owner, repo)

    Raises:
        ValueError: If the URL is not a GitHub URL
    """
    canon = canonicalize_repo_url(url)  # e.g., github.com/owner/repo
    parts = canon.split("/")
    if len(parts) < 3 or parts[0] != "github.com":
        raise ValueError("Only GitHub is supported by the estimator")
    return parts[1], parts[2]


def _gh_get(path):
    """
    Perform a simple GET with brief retries and naive rate-limit backoff

    Args:
        path (str): API path like "/repos/{o}/{r}/languages"

    Returns:
        Any|None: Parsed JSON or None on failure
    """
    url = f"{GITHUB_API_BASE}{path}"
    for _ in range(3):
        try:
            r = requests.get(url, headers=_gh_headers(), timeout=15)
        except Exception:
            time.sleep(1)
            continue
        if r.status_code == 200:
            try:
                return r.json()
            except Exception:
                return None
        if r.status_code in (403, 429):
            time.sleep(5)
            continue
        if r.status_code == 404:
            return None
        time.sleep(1)
    return None


def _fetch_languages(owner, repo):
    data = _gh_get(f"/repos/{owner}/{repo}/languages")
    return data or {}


def _fetch_root_contents(owner, repo):
    data = _gh_get(f"/repos/{owner}/{repo}/contents")
    return data if isinstance(data, list) else []


def _build_features_from_github(repo_url):
    """
    Build the exact features required by the model JSON

    Args:
        repo_url (str): Repository URL

    Returns:
        dict[str,float]: Feature name → value
    """
    owner, repo = _parse_owner_repo(repo_url)
    langs = _fetch_languages(owner, repo) or {}
    contents = _fetch_root_contents(owner, repo) or []

    total_lang_bytes = sum(int(v) for v in langs.values())
    supported_bytes = sum(int(langs.get(k, 0)) for k in SUPPORTED_LANGS)

    # Shares (guard div by zero)
    js_share = (langs.get("JavaScript", 0) / total_lang_bytes) if total_lang_bytes else 0.0
    ts_share = (langs.get("TypeScript", 0) / total_lang_bytes) if total_lang_bytes else 0.0
    py_share = (langs.get("Python", 0) / total_lang_bytes) if total_lang_bytes else 0.0

    # Root manifest sizes
    name_to_size = {}
    for item in contents:
        try:
            if item.get("type") == "file":
                name_to_size[item["name"]] = int(item.get("size", 0))
        except Exception:
            # Ignore malformed entries defensively
            continue
    manifest_bytes = sum(size for name, size in name_to_size.items() if name in ROOT_FILENAMES)
    manifest_count = sum(1 for name in name_to_size if name in ROOT_FILENAMES)

    return {
        "log1p_supported_code_total_bytes": math.log1p(supported_bytes),
        "log1p_manifests_total_bytes": math.log1p(manifest_bytes),
        "manifests_present_count": manifest_count,
        "lang_share__JavaScript": js_share,
        "lang_share__TypeScript": ts_share,
        "lang_share__Python": py_share,
    }


def _load_model():
    """
    Load model JSON from environment

    Returns:
        dict|None: Parsed model or None
    """
    raw = os.getenv(MODEL_ENV, "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _predict_seconds(model, feat_map):
    """
    Apply standardized log-linear model with bias correction and safety multiplier

    Args:
        model (dict): Model json blob
        feat_map (dict): Feature values computed for repo

    Returns:
        Decimal: Predicted seconds as Decimal
    """
    feats = model["features"]
    x = [feat_map.get(f, 0.0) for f in feats]
    mu = model["mu"]
    sigma = [s if s else 1.0 for s in model["sigma"]]
    z = [(xi - mi) / si for xi, mi, si in zip(x, mu, sigma)]

    yhat = float(model["intercept"])
    for b, zi in zip(model["beta"], z):
        yhat += float(b) * float(zi)

    bias = float(model.get("bias_correction", 0.5)) * (float(model.get("s_res", 0.0)) ** 2)
    safety = float(model.get("safety_multiplier", 1.10))
    seconds = math.exp(yhat + bias) * safety
    return Decimal(seconds)


def estimate_duration_seconds(repo_url):
    """
    Best-effort duration estimate

    Args:
        repo_url (str): Repository URL

    Returns:
        Decimal|None: Predicted seconds, or None on failure/missing model
    """
    model = _load_model()
    if not model:
        return None
    try:
        feats = _build_features_from_github(repo_url)
        return _predict_seconds(model, feats)
    except Exception:
        return None
