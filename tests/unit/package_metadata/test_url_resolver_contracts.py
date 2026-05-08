import json

import pytest

from gardener.package_metadata import url_resolver
from gardener.package_metadata.url_resolver import resolve_package_url_receipts, resolve_package_urls


CHECKED_AT = "2026-04-30T00:00:00Z"


def _npm_meta(repository=None, *, bugs=None, homepage=None):
    version = {}
    if repository is not None:
        version["repository"] = repository
    if bugs is not None:
        version["bugs"] = bugs
    if homepage is not None:
        version["homepage"] = homepage
    return {"dist-tags": {"latest": "1.0.0"}, "versions": {"1.0.0": version}}


def _resolution_for(package_name, packages, offline_mode, responses, *, cache=None):
    with offline_mode.set_responses(responses):
        return resolve_package_url_receipts(packages, logger=None, cache=cache, checked_at=CHECKED_AT)[package_name]


@pytest.mark.unit
def test_npm_url_resolution_normalizes_git_urls(offline_mode):
    packages = {"lodash": {"ecosystem": "npm"}}
    npm_meta = _npm_meta({"type": "git", "url": "git+https://github.com/lodash/lodash.git"})

    url = "https://registry.npmjs.org/lodash"
    with offline_mode.set_responses({url: json.dumps(npm_meta)}):
        resolved = resolve_package_urls(packages, logger=None, cache={})
    assert resolved["lodash"] == "https://github.com/lodash/lodash"


@pytest.mark.unit
def test_npm_receipt_records_registry_success_and_normalization(offline_mode):
    packages = {"lodash": {"ecosystem": "npm"}}
    npm_meta = _npm_meta({"type": "git", "url": "git+https://github.com/lodash/lodash.git"})

    entry = _resolution_for(
        "lodash",
        packages,
        offline_mode,
        {"https://registry.npmjs.org/lodash": json.dumps(npm_meta)},
        cache={},
    )

    assert entry["repository_url"] == "https://github.com/lodash/lodash"
    assert entry["repository_url_resolution"] == {
        "status": "resolved",
        "source": "npm-registry",
        "cache": "miss",
        "normalized": True,
        "checked_at": CHECKED_AT,
    }


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
def test_pypi_github_substrings_are_not_treated_as_repository_hosts(offline_mode):
    packages = {"not-github": {"ecosystem": "pypi"}}
    pypi_meta = {
        "info": {
            "home_page": "https://example.com/github.com/owner/repo",
            "project_urls": {"Repository": "https://evil-github.com/owner/repo"},
        }
    }

    entry = _resolution_for(
        "not-github",
        packages,
        offline_mode,
        {"https://pypi.org/pypi/not-github/json": json.dumps(pypi_meta)},
        cache={},
    )

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"]["reason"] == "no-repository-url"


@pytest.mark.unit
def test_gitlab_nested_group_repository_url_is_preserved(offline_mode):
    packages = {"gitlab-project": {"ecosystem": "pypi"}}
    pypi_meta = {
        "info": {
            "project_urls": {
                "Repository": "https://www.gitlab.com/group/subgroup/project.git?token=secret#frag",
            }
        }
    }

    entry = _resolution_for(
        "gitlab-project",
        packages,
        offline_mode,
        {"https://pypi.org/pypi/gitlab-project/json": json.dumps(pypi_meta)},
        cache={},
    )

    assert entry["repository_url"] == "https://gitlab.com/group/subgroup/project"
    assert entry["repository_url_resolution"]["normalized"] is True


@pytest.mark.unit
def test_cargo_homepage_nested_gitlab_repository_is_preserved(offline_mode):
    packages = {"gitlab-project": {"ecosystem": "cargo"}}
    crate_meta = {
        "crate": {
            "homepage": "https://www.gitlab.com/group/subgroup/project.git?token=secret#frag",
        }
    }

    entry = _resolution_for(
        "gitlab-project",
        packages,
        offline_mode,
        {"https://crates.io/api/v1/crates/gitlab-project": json.dumps(crate_meta)},
        cache={},
    )

    assert entry["repository_url"] == "https://gitlab.com/group/subgroup/project"
    assert entry["repository_url_resolution"]["normalized"] is True


@pytest.mark.unit
def test_npm_types_package_maps_to_definitely_typed(offline_mode):
    packages = {"@types/react": {"ecosystem": "npm"}}
    with offline_mode.set_responses({}):
        resolved = resolve_package_urls(packages, logger=None, cache={})
    assert resolved["@types/react"] == "https://github.com/DefinitelyTyped/DefinitelyTyped"


@pytest.mark.unit
def test_github_shorthand_owner_repo_is_canonicalized(offline_mode):
    packages = {"my-lib": {"ecosystem": "npm"}}
    meta = _npm_meta("github:user/my-lib.git")
    url = "https://registry.npmjs.org/my-lib"
    with offline_mode.set_responses({url: json.dumps(meta)}):
        resolved = resolve_package_urls(packages, logger=None, cache={})
    assert resolved["my-lib"] == "https://github.com/user/my-lib"


@pytest.mark.unit
@pytest.mark.parametrize(
    "repository_url",
    [
        "git+ssh://git@github.com/owner/repo.git",
        "git+ssh://git@github.com:owner/repo.git",
        "git@github.com:owner/repo.git",
    ],
)
def test_npm_ssh_repository_urls_are_canonicalized_for_url_projection(offline_mode, repository_url):
    packages = {"ssh-lib": {"ecosystem": "npm"}}
    meta = _npm_meta(repository_url)
    url = "https://registry.npmjs.org/ssh-lib"

    with offline_mode.set_responses({url: json.dumps(meta)}):
        resolved = resolve_package_urls(packages, logger=None, cache={})

    assert resolved["ssh-lib"] == "https://github.com/owner/repo"


@pytest.mark.unit
def test_npm_repository_dict_uses_valid_alternate_value_when_url_is_invalid(offline_mode):
    packages = {"dict-fallback": {"ecosystem": "npm"}}
    meta = _npm_meta({"url": "not a url", "web": "https://github.com/owner/repo"})
    url = "https://registry.npmjs.org/dict-fallback"

    with offline_mode.set_responses({url: json.dumps(meta)}):
        resolved = resolve_package_urls(packages, logger=None, cache={})

    assert resolved["dict-fallback"] == "https://github.com/owner/repo"


@pytest.mark.unit
def test_npm_repository_dict_directory_shorthand_does_not_create_false_github_resolution(offline_mode):
    packages = {"dict-directory": {"ecosystem": "npm"}}
    meta = _npm_meta({"url": "not a url", "directory": "packages/foo"})

    entry = _resolution_for(
        "dict-directory",
        packages,
        offline_mode,
        {"https://registry.npmjs.org/dict-directory": json.dumps(meta)},
        cache={},
    )

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"]["reason"] == "normalization-failed"


@pytest.mark.unit
def test_malformed_repository_field_falls_back_to_valid_bugs_url(offline_mode):
    packages = {"malformed-fallback": {"ecosystem": "npm"}}
    meta = _npm_meta("https://[github.com/owner/repo", bugs={"url": "https://github.com/owner/repo/issues"})

    entry = _resolution_for(
        "malformed-fallback",
        packages,
        offline_mode,
        {"https://registry.npmjs.org/malformed-fallback": json.dumps(meta)},
        cache={},
    )

    assert entry["repository_url"] == "https://github.com/owner/repo"
    assert entry["repository_url_resolution"]["status"] == "resolved"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("repository_url", "expected_url"),
    [
        ("https://evil-github.com/owner/repo.git", "https://evil-github.com/owner/repo"),
        ("https://example.com/github.com/owner/repo.git", "https://example.com/github.com/owner/repo"),
    ],
)
def test_github_substring_urls_are_not_rewritten_to_github(offline_mode, repository_url, expected_url):
    packages = {"not-github": {"ecosystem": "npm"}}
    meta = _npm_meta(repository_url)
    url = "https://registry.npmjs.org/not-github"

    with offline_mode.set_responses({url: json.dumps(meta)}):
        resolved = resolve_package_urls(packages, logger=None, cache={})

    assert resolved["not-github"] == expected_url


@pytest.mark.unit
@pytest.mark.parametrize(
    ("bugs", "homepage"),
    [
        ({"url": "https://evil-github.com/owner/repo"}, None),
        (None, "https://example.com/github.com/owner/repo"),
    ],
)
def test_bugs_and_homepage_github_substrings_are_not_rewritten_to_github(offline_mode, bugs, homepage):
    packages = {"no-host-match": {"ecosystem": "npm"}}
    meta = _npm_meta(bugs=bugs, homepage=homepage)

    entry = _resolution_for(
        "no-host-match",
        packages,
        offline_mode,
        {"https://registry.npmjs.org/no-host-match": json.dumps(meta)},
        cache={},
    )

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"]["reason"] == "no-repository-url"


@pytest.mark.unit
def test_supported_ecosystem_resolver_error_uses_attempted_source(monkeypatch):
    packages = {"broken": {"ecosystem": "npm"}}

    def _raise_error(package_name, logger=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(url_resolver, "_resolve_npm_package_attempt", _raise_error)

    entry = resolve_package_url_receipts(packages, logger=None, cache={}, checked_at=CHECKED_AT)["broken"]

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"]["source"] == "npm-registry"
    assert entry["repository_url_resolution"]["reason"] == "resolver-error"


@pytest.mark.unit
def test_package_shape_error_becomes_per_package_resolver_error_receipt():
    entry = resolve_package_url_receipts({"broken": None}, logger=None, cache={}, checked_at=CHECKED_AT)["broken"]

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"]["source"] == "unsupported-ecosystem"
    assert entry["repository_url_resolution"]["reason"] == "resolver-error"


@pytest.mark.unit
def test_cache_hit_receipt_uses_cache_source_and_sanitizes_url(offline_mode):
    packages = {"cached": {"ecosystem": "npm"}}

    entry = _resolution_for(
        "cached",
        packages,
        offline_mode,
        {},
        cache={"npm:cached": "https://user:token@github.com/owner/repo.git"},
    )

    assert entry["repository_url"] == "https://github.com/owner/repo"
    assert entry["repository_url_resolution"] == {
        "status": "resolved",
        "source": "cache",
        "cache": "hit",
        "normalized": True,
        "checked_at": CHECKED_AT,
    }


@pytest.mark.unit
def test_invalid_cache_entry_records_invalid_cache_entry(offline_mode):
    packages = {"cached": {"ecosystem": "npm"}}

    entry = _resolution_for("cached", packages, offline_mode, {}, cache={"npm:cached": "not a url"})

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"] == {
        "status": "unresolved",
        "source": "cache",
        "cache": "hit",
        "normalized": False,
        "checked_at": CHECKED_AT,
        "reason": "invalid-cache-entry",
    }


@pytest.mark.unit
def test_cache_none_records_not_used_while_empty_cache_records_miss(offline_mode):
    packages = {"lodash": {"ecosystem": "npm"}}
    meta = _npm_meta("https://github.com/lodash/lodash")
    responses = {"https://registry.npmjs.org/lodash": json.dumps(meta)}

    miss_entry = _resolution_for("lodash", packages, offline_mode, responses, cache={})
    not_used_entry = _resolution_for("lodash", packages, offline_mode, responses, cache=None)

    assert miss_entry["repository_url_resolution"]["cache"] == "miss"
    assert not_used_entry["repository_url_resolution"]["cache"] == "not-used"


@pytest.mark.unit
def test_registry_no_data_receipt_records_no_data_reason(offline_mode):
    packages = {"missing": {"ecosystem": "npm"}}

    entry = _resolution_for("missing", packages, offline_mode, {}, cache={})

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"] == {
        "status": "unresolved",
        "source": "npm-registry",
        "cache": "miss",
        "normalized": False,
        "checked_at": CHECKED_AT,
        "reason": "no-data-returned",
    }


@pytest.mark.unit
def test_network_failure_receipt_records_network_error(offline_mode, monkeypatch):
    packages = {"flaky": {"ecosystem": "npm"}}
    monkeypatch.setattr(url_resolver, "RETRY_COUNT", 0)

    entry = _resolution_for(
        "flaky",
        packages,
        offline_mode,
        {"https://registry.npmjs.org/flaky": ConnectionError("boom")},
        cache={},
    )

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"]["reason"] == "network-error"
    assert entry["repository_url_resolution"]["source"] == "npm-registry"


@pytest.mark.unit
def test_invalid_registry_response_records_invalid_response_reason(offline_mode):
    packages = {"invalid-json": {"ecosystem": "npm"}}

    entry = _resolution_for(
        "invalid-json",
        packages,
        offline_mode,
        {"https://registry.npmjs.org/invalid-json": "{not-json"},
        cache={},
    )

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"]["reason"] == "invalid-registry-response"
    assert entry["repository_url_resolution"]["source"] == "npm-registry"


@pytest.mark.unit
def test_metadata_without_repository_url_records_no_repository_url(offline_mode):
    packages = {"no-repo": {"ecosystem": "npm"}}

    entry = _resolution_for(
        "no-repo",
        packages,
        offline_mode,
        {"https://registry.npmjs.org/no-repo": json.dumps(_npm_meta())},
        cache={},
    )

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"]["reason"] == "no-repository-url"
    assert entry["repository_url_resolution"]["source"] == "npm-registry"


@pytest.mark.unit
def test_invalid_repository_field_falls_back_to_valid_bugs_url(offline_mode):
    packages = {"fallback-bugs": {"ecosystem": "npm"}}
    meta = _npm_meta("not a url", bugs={"url": "https://github.com/owner/repo/issues"})

    entry = _resolution_for(
        "fallback-bugs",
        packages,
        offline_mode,
        {"https://registry.npmjs.org/fallback-bugs": json.dumps(meta)},
        cache={},
    )

    assert entry["repository_url"] == "https://github.com/owner/repo"
    assert entry["repository_url_resolution"]["status"] == "resolved"


@pytest.mark.unit
def test_invalid_repository_field_falls_back_to_valid_homepage(offline_mode):
    packages = {"fallback-homepage": {"ecosystem": "npm"}}
    meta = _npm_meta("not a url", homepage="https://github.com/owner/homepage#readme")

    entry = _resolution_for(
        "fallback-homepage",
        packages,
        offline_mode,
        {"https://registry.npmjs.org/fallback-homepage": json.dumps(meta)},
        cache={},
    )

    assert entry["repository_url"] == "https://github.com/owner/homepage"
    assert entry["repository_url_resolution"]["status"] == "resolved"


@pytest.mark.unit
def test_invalid_raw_url_candidate_records_normalization_failed(offline_mode):
    packages = {"bad-url": {"ecosystem": "npm"}}

    entry = _resolution_for(
        "bad-url",
        packages,
        offline_mode,
        {"https://registry.npmjs.org/bad-url": json.dumps(_npm_meta("not a url"))},
        cache={},
    )

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"]["reason"] == "normalization-failed"


@pytest.mark.unit
def test_credential_bearing_registry_url_is_sanitized_in_receipt(offline_mode):
    packages = {"secret-url": {"ecosystem": "npm"}}
    meta = _npm_meta({"type": "git", "url": "https://user:token@github.com/owner/repo.git"})

    entry = _resolution_for(
        "secret-url",
        packages,
        offline_mode,
        {"https://registry.npmjs.org/secret-url": json.dumps(meta)},
        cache={},
    )

    assert entry["repository_url"] == "https://github.com/owner/repo"
    assert "user:token" not in entry["repository_url"]


@pytest.mark.unit
def test_go_go_get_meta_tag_parsing(offline_mode):
    packages = {"golang.org/x/crypto": {"ecosystem": "go"}}
    html = (
        "<html><head>"
        '<meta name="go-import" content="golang.org/x/crypto git https://github.com/golang/crypto">'
        "</head><body></body></html>"
    )
    fetch_url = "https://golang.org/x/crypto?go-get=1"
    with offline_mode.set_responses({fetch_url: html}):
        resolved = resolve_package_urls(packages, logger=None, cache={})
    assert resolved["golang.org/x/crypto"] == "https://github.com/golang/crypto"


@pytest.mark.unit
def test_go_go_get_html_resolution_allows_arbitrary_https_import_domains(offline_mode):
    packages = {"go.example.test/team/module": {"ecosystem": "go"}}
    html = (
        "<html><head>"
        '<meta name="go-import" content="go.example.test/team/module git https://github.com/team/module">'
        "</head><body></body></html>"
    )

    entry = _resolution_for(
        "go.example.test/team/module",
        packages,
        offline_mode,
        {"https://go.example.test/team/module?go-get=1": html},
        cache={},
    )

    assert entry["repository_url"] == "https://github.com/team/module"
    assert entry["repository_url_resolution"]["source"] == "go-get-meta"
    assert entry["repository_url_resolution"]["cache"] == "miss"


@pytest.mark.unit
def test_solidity_source_hint_github_substring_is_not_treated_as_repository_host(offline_mode):
    packages = {"@bad/": {"ecosystem": "solidity", "source": "https://evil-github.com/owner/repo"}}

    entry = _resolution_for("@bad/", packages, offline_mode, {}, cache={})

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"]["source"] == "solidity-source-hint"
    assert entry["repository_url_resolution"]["reason"] == "no-repository-url"


@pytest.mark.unit
def test_go_direct_import_path_requires_exact_repository_host(offline_mode):
    packages = {"evil-github.com/owner/repo": {"ecosystem": "go"}}

    entry = _resolution_for("evil-github.com/owner/repo", packages, offline_mode, {}, cache={})

    assert entry["repository_url"] == ""
    assert entry["repository_url_resolution"]["source"] == "go-get-meta"
