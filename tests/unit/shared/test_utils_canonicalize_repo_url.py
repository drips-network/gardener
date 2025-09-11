import pytest

from services.shared.utils import canonicalize_repo_url


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://github.com/Owner/Repo", "github.com/owner/repo"),
        ("git@github.com:Owner/Repo.git", "github.com/owner/repo"),
        ("github.com/Owner/Repo", "github.com/owner/repo"),
        ("https://www.github.com/Owner/Repo.git", "github.com/owner/repo"),
    ],
)
def test_canonicalize_repo_url_github_variants(raw, expected):
    assert canonicalize_repo_url(raw) == expected


@pytest.mark.unit
def test_canonicalize_repo_url_invalid():
    with pytest.raises(ValueError):
        canonicalize_repo_url("not a url")
