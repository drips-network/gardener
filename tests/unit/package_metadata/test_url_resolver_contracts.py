import json

import pytest

from gardener.package_metadata.url_resolver import resolve_package_urls


@pytest.mark.unit
def test_npm_url_resolution_normalizes_git_urls(offline_mode):
    packages = {"lodash": {"ecosystem": "npm"}}

    # Minimal npm registry payload with repository.url
    npm_meta = {
        "dist-tags": {"latest": "4.17.21"},
        "versions": {"4.17.21": {"repository": {"type": "git", "url": "git+https://github.com/lodash/lodash.git"}}},
    }

    url = "https://registry.npmjs.org/lodash"
    with offline_mode.set_responses({url: json.dumps(npm_meta)}):
        resolved = resolve_package_urls(packages, logger=None, cache={})
    assert resolved["lodash"] == "https://github.com/lodash/lodash"


@pytest.mark.unit
def test_pypi_url_resolution_prefers_project_urls(offline_mode):
    packages = {"requests": {"ecosystem": "pypi"}}

    pypi_meta = {
        "info": {
            "project_urls": {
                "Repository": "https://github.com/psf/requests",
                "Homepage": "https://requests.readthedocs.io",
            }
        }
    }

    url = "https://pypi.org/pypi/requests/json"
    with offline_mode.set_responses({url: json.dumps(pypi_meta)}):
        resolved = resolve_package_urls(packages, logger=None, cache={})
    assert resolved["requests"] == "https://github.com/psf/requests"


@pytest.mark.unit
def test_npm_types_package_maps_to_definitely_typed(offline_mode):
    packages = {"@types/react": {"ecosystem": "npm"}}
    # No network fetch required; resolver uses a fast-path
    with offline_mode.set_responses({}):
        resolved = resolve_package_urls(packages, logger=None, cache={})
    assert resolved["@types/react"] == "https://github.com/DefinitelyTyped/DefinitelyTyped"


@pytest.mark.unit
def test_github_shorthand_owner_repo_is_canonicalized(offline_mode):
    packages = {"my-lib": {"ecosystem": "npm"}}
    # Simulate npm metadata with repository string using GitHub shorthand
    meta = {"dist-tags": {"latest": "1.0.0"}, "versions": {"1.0.0": {"repository": "github:user/my-lib.git"}}}
    url = "https://registry.npmjs.org/my-lib"
    with offline_mode.set_responses({url: json.dumps(meta)}):
        resolved = resolve_package_urls(packages, logger=None, cache={})
    assert resolved["my-lib"] == "https://github.com/user/my-lib"


@pytest.mark.unit
def test_go_go_get_meta_tag_parsing(offline_mode):
    packages = {"golang.org/x/crypto": {"ecosystem": "go"}}
    # Simulate HTML with go-import meta
    html = (
        "<html><head>"
        '<meta name="go-import" content="golang.org/x/crypto git https://github.com/golang/crypto">'
        "</head><body></body></html>"
    )
    fetch_url = "https://golang.org/x/crypto?go-get=1"
    with offline_mode.set_responses({fetch_url: html}):
        resolved = resolve_package_urls(packages, logger=None, cache={})
    assert resolved["golang.org/x/crypto"] == "https://github.com/golang/crypto"
