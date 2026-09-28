"""Python import-name resolution through the production resolver"""

import io
import json
import tarfile
from pathlib import Path

import pytest

from gardener.common.secure_file_ops import SecureFileOps
from gardener.common.utils import Logger
from gardener.package_metadata.name_resolvers.python import PythonResolver
from gardener.package_metadata.name_resolvers.python_metadata import PythonEnvironment

pytestmark = pytest.mark.unit


def test_metadata_names_replace_guesses_and_keep_all_names(fake_pypi):
    names = ["alpha", "beta", "delta", "epsilon", "gamma"]
    fake_pypi.add_release("python-foo-bar", "1", {"pkg.dist-info/top_level.txt": "\n".join(names)})
    assert PythonResolver().resolve_package_imports("python-foo-bar") == names


def test_wheel_paths_keep_more_than_three_packages(fake_pypi):
    names = ["alpha", "beta", "delta", "gamma"]
    fake_pypi.add_release("pkg", "1", {f"{name}/__init__.py": "" for name in names})
    assert PythonResolver().resolve_package_imports("pkg") == names


@pytest.mark.parametrize("archive_format", ["wheel", "sdist"])
def test_invalid_archive_inference_returns_labeled_guesses(archive_format, tmp_path, fake_pypi):
    archive_url = fake_pypi.add_release("python-widget", "1", {"widget.py": "", "widget.dist-info/METADATA": ""})
    if archive_format == "sdist":
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            archive.addfile(tarfile.TarInfo("python-widget-1/widget.py"), io.BytesIO(b""))
        fake_pypi.responses[archive_url] = buffer.getvalue()
        metadata_url = "https://pypi.org/pypi/python-widget/json"
        metadata = json.loads(fake_pypi.responses[metadata_url])
        metadata["releases"]["1"][0]["filename"] = "python-widget-1.tar.gz"
        fake_pypi.responses[metadata_url] = json.dumps(metadata).encode()
    names, receipt = resolve(tmp_path, name="python-widget")
    assert names == ["python_widget", "widget"]
    assert receipt["source"] == "name-guess"
    assert receipt["versions"] == []
    assert receipt["reason"] == "pypi-metadata-unavailable"


def write_lock(root, filename="uv.lock", version="1", name="pkg"):
    array = "packages" if filename == "pylock.toml" else "package"
    source = '\nsource = { registry = "https://pypi.org/simple" }' if filename == "uv.lock" else ""
    path = root / filename
    path.write_text(f'[[{array}]]\nname = "{name}"\nversion = "{version}"{source}\n')
    return path


def resolve(root, name="pkg", environment=None, manifests=None):
    manifest = root / "requirements.txt"
    manifest.touch()
    return PythonResolver(SecureFileOps(str(root)), environment).resolve_import_names(
        name, manifests or [str(manifest.resolve())]
    )


@pytest.mark.parametrize("filename", ["uv.lock", "poetry.lock", "pylock.toml"])
def test_locked_version_replaces_latest(filename, tmp_path, fake_pypi):
    write_lock(tmp_path, filename)
    old = fake_pypi.add_release("pkg", "1", {"p.dist-info/top_level.txt": "old"})
    latest = fake_pypi.add_release("pkg", "2", {"p.dist-info/top_level.txt": "new"})
    names, receipt = resolve(tmp_path)
    assert names == ["old"]
    assert receipt == {"source": "pypi:locked-version", "versions": ["1"], "lockfiles": [filename]}
    assert old in fake_pypi.requested_urls
    assert latest not in fake_pypi.requested_urls


def test_no_matching_entry_uses_latest(tmp_path, fake_pypi):
    write_lock(tmp_path, name="unrelated")
    fake_pypi.add_release("pkg", "2", {"p.dist-info/top_level.txt": "new"})
    assert resolve(tmp_path) == (
        ["new"],
        {"source": "pypi:latest", "versions": ["2"], "lockfiles": []},
    )


def test_forked_versions_union_names_and_deduplicate_repeated_entries(tmp_path, fake_pypi):
    lock = write_lock(tmp_path)
    first = lock.read_text()
    lock.write_text(first + first + first.replace('version = "1"', 'version = "2"'))
    old = fake_pypi.add_release("pkg", "1", {"p.dist-info/top_level.txt": "old\nshared"})
    new = fake_pypi.add_release("pkg", "2", {"p.dist-info/top_level.txt": "new\nshared"})
    names, receipt = resolve(tmp_path)
    assert names == ["new", "old", "shared"]
    assert receipt["versions"] == ["1", "2"]
    assert fake_pypi.requested_urls.count(old) == 1
    assert fake_pypi.requested_urls.count(new) == 1


def test_registry_entry_without_version_never_requests_pypi(tmp_path, fake_pypi):
    (tmp_path / "uv.lock").write_text('[[package]]\nname="pkg"\nsource={registry="https://pypi.org/simple"}')
    names, receipt = resolve(tmp_path)
    assert names == ["pkg"]
    assert receipt["source"] == "name-guess"
    assert receipt["reason"] == "lock-entry-not-pypi-release"
    assert receipt["versions"] == []
    assert fake_pypi.requested_urls == []


def test_mixed_registry_and_direct_entries_do_not_claim_pypi(tmp_path, fake_pypi):
    path = write_lock(tmp_path)
    path.write_text(path.read_text() + '\n[[package]]\nname="pkg"\nversion="2"\nsource={git="x"}')
    assert resolve(tmp_path)[1]["reason"] == "lock-entry-not-pypi-release"
    assert fake_pypi.requested_urls == []


@pytest.mark.parametrize("failure", ["missing-release", "archive", "json", "download"])
def test_pinned_lookup_failure_has_no_actual_versions_or_latest_substitution(failure, tmp_path, fake_pypi):
    write_lock(tmp_path)
    old = fake_pypi.add_release("pkg", "1", {"p.dist-info/top_level.txt": "old"})
    latest = fake_pypi.add_release("pkg", "2", {"p.dist-info/top_level.txt": "new"})
    if failure == "missing-release":
        write_lock(tmp_path, version="0")
    elif failure == "archive":
        fake_pypi.responses[old] = b"not a zip"
    elif failure == "json":
        fake_pypi.responses["https://pypi.org/pypi/pkg/json"] = b"not json"
    else:
        del fake_pypi.responses[old]
    _, receipt = resolve(tmp_path)
    assert receipt == {
        "source": "name-guess",
        "versions": [],
        "lockfiles": ["uv.lock"],
        "reason": "pypi-metadata-unavailable",
    }
    assert latest not in fake_pypi.requested_urls


@pytest.mark.parametrize("bad_lock", ["toml", "directory", "external", "encoding"])
def test_unreadable_lock_never_becomes_latest(bad_lock, tmp_path, fake_pypi):
    repo = tmp_path / "repo"
    repo.mkdir()
    lock = repo / "uv.lock"
    if bad_lock == "toml":
        lock.write_text("[[")
    elif bad_lock == "directory":
        lock.mkdir()
    elif bad_lock == "encoding":
        lock.write_bytes(b"\xff")
    else:
        target = tmp_path / "external.lock"
        target.write_text("[[package]]\nname='pkg'\nversion='1'")
        lock.symlink_to(target)
    _, receipt = resolve(repo)
    assert receipt["reason"] == "lockfile-unreadable"
    assert receipt["lockfiles"] == ["uv.lock"]
    assert fake_pypi.requested_urls == []


def test_nearest_lock_owns_each_manifest_and_missing_entries_stop_search(tmp_path, fake_pypi):
    write_lock(tmp_path)
    nested = tmp_path / "service"
    nested.mkdir()
    manifest = nested / "requirements.txt"
    manifest.touch()
    fake_pypi.add_release("pkg", "1", {"p.dist-info/top_level.txt": "root"})
    fake_pypi.add_release("pkg", "2", {"p.dist-info/top_level.txt": "nested"})
    manifests = [str(manifest.resolve())]
    assert resolve(tmp_path, manifests=manifests)[0] == ["root"]
    write_lock(nested, "poetry.lock", version="2")
    names, receipt = resolve(tmp_path, manifests=manifests)
    assert names == ["nested"]
    assert receipt["lockfiles"] == ["service/poetry.lock"]
    write_lock(nested, "poetry.lock", name="other")
    assert resolve(tmp_path, manifests=manifests)[1]["source"] == "pypi:latest"


def test_declaring_projects_and_colocated_locks_combine(tmp_path, fake_pypi):
    manifests = []
    for directory, version in [("a", "1"), ("b", "2")]:
        root = tmp_path / directory
        root.mkdir()
        manifest = root / "requirements.txt"
        manifest.touch()
        manifests.append(str(manifest.resolve()))
        write_lock(root, version=version)
        fake_pypi.add_release("pkg", version, {"p.dist-info/top_level.txt": directory})
    write_lock(tmp_path / "a", "pylock.toml")
    names, receipt = resolve(tmp_path, manifests=manifests)
    assert names == ["a", "b"]
    assert receipt["versions"] == ["1", "2"]
    assert receipt["lockfiles"] == ["a/pylock.toml", "a/uv.lock", "b/uv.lock"]


def test_explicit_environment_wins_without_network(tmp_path, fake_pypi):
    write_lock(tmp_path, name="PyYAML")
    metadata = tmp_path / ".venv/lib/python3.11/site-packages/pyyaml-6.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "top_level.txt").write_text("yaml\n_yaml")
    environment = PythonEnvironment(str(tmp_path / ".venv"))
    assert resolve(tmp_path, "PyYAML", environment) == (
        ["_yaml", "yaml"],
        {"source": "installed-environment", "versions": ["6"], "lockfiles": []},
    )
    assert fake_pypi.requested_urls == []


@pytest.mark.parametrize("installed", ["missing", "pth", "duplicate", "encoding"])
def test_unusable_environment_continues_to_locked_version(installed, tmp_path, fake_pypi, capsys):
    write_lock(tmp_path)
    site = tmp_path / ".venv/lib/python3.11/site-packages"
    site.mkdir(parents=True)
    if installed != "missing":
        metadata = site / "pkg-2.dist-info"
        metadata.mkdir()
        (metadata / "RECORD").write_text("editable.pth,,\n")
        if installed == "duplicate":
            (site / "pkg-3.dist-info").mkdir()
            (metadata / "top_level.txt").write_text("wrong_two")
            (site / "pkg-3.dist-info/top_level.txt").write_text("wrong_three")
        if installed == "encoding":
            (metadata / "top_level.txt").write_bytes(b"\xff")
    fake_pypi.add_release("pkg", "1", {"p.dist-info/top_level.txt": "locked"})
    environment = PythonEnvironment(str(tmp_path / ".venv"), Logger(verbose=False))
    assert resolve(tmp_path, environment=environment)[1]["source"] == "pypi:locked-version"
    if installed == "duplicate":
        assert "Warning: Python environment has 2 metadata entries for pkg" in capsys.readouterr().err


def test_unsearchable_installed_metadata_uses_locked_resolution(tmp_path, fake_pypi, monkeypatch, capsys):
    write_lock(tmp_path)
    metadata = tmp_path / ".venv/lib/python3.11/site-packages/pkg-2.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "top_level.txt").write_text("installed")
    environment = PythonEnvironment(str(tmp_path / ".venv"), Logger(verbose=False))
    original_is_file = Path.is_file

    def denied_metadata(path):
        if path.parent == metadata:
            raise PermissionError("metadata is not searchable")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", denied_metadata)
    fake_pypi.add_release("pkg", "1", {"p.dist-info/top_level.txt": "locked"})
    names, receipt = resolve(tmp_path, environment=environment)
    assert names == ["locked"]
    assert receipt["source"] == "pypi:locked-version"
    assert "metadata is not searchable" in capsys.readouterr().err


def test_environment_is_not_autodetected(tmp_path, fake_pypi):
    metadata = tmp_path / ".venv/lib/python3.11/site-packages/pkg-2.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "top_level.txt").write_text("installed")
    fake_pypi.add_release("pkg", "1", {"p.dist-info/top_level.txt": "remote"})
    assert resolve(tmp_path)[0] == ["remote"]
