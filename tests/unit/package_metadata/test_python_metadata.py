"""Static lock and environment input contracts"""

import pytest

from gardener.package_metadata.name_resolvers.python_metadata import (
    LockEntry,
    PythonEnvironment,
    PythonEnvironmentError,
    parse_python_lockfile,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "filename,entry,supported",
    [
        ("uv.lock", 'source={registry="https://pypi.org/simple/"}', True),
        ("uv.lock", 'source={registry="https://private/simple"}', False),
        ("uv.lock", 'source={virtual="."}', False),
        ("uv.lock", 'source={directory="."}', False),
        ("poetry.lock", "", True),
        ("poetry.lock", 'source={type="git",url="x"}', False),
        ("pylock.toml", "", True),
        ("pylock.toml", 'index="https://pypi.org/simple/"', True),
        ("pylock.toml", 'index="https://private/simple"', False),
        ("pylock.toml", 'vcs={url="x"}', False),
        ("pylock.toml", 'directory={path="."}', False),
        ("pylock.toml", 'archive={url="x"}', False),
    ],
)
def test_lock_formats_normalize_keys_and_classify_sources(filename, entry, supported):
    array = "packages" if filename == "pylock.toml" else "package"
    content = f'[[{array}]]\nname="Foo._BAR"\nversion="1"\n{entry}'
    assert parse_python_lockfile(filename, content) == {"foo-bar": {LockEntry("1", supported)}}


@pytest.mark.parametrize(
    "content",
    [
        "[[",
        "package=1",
        'package=["bad"]',
        '[[package]]\nversion="1"',
        '[[package]]\nname="pkg"\nversion=1',
        '[[package]]\nname="pkg"\nsource=1',
        '[[package]]\nname=""',
        '[[package]]\nname="pkg"\nsource={registry=1}',
    ],
)
def test_malformed_consumed_fields_are_rejected(content):
    with pytest.raises(ValueError):
        parse_python_lockfile("uv.lock", content)


def test_missing_version_is_preserved_as_unusable_and_unused_fields_are_ignored():
    assert parse_python_lockfile("uv.lock", 'version=99\n[[package]]\nname="pkg"\nmarkers="uninterpreted"') == {
        "pkg": {LockEntry(None, False)}
    }
    with pytest.raises(ValueError):
        parse_python_lockfile("pylock.toml", '[[packages]]\nname="pkg"\nindex=1')


@pytest.mark.parametrize("layout", ["lib/python3.11/site-packages", "Lib/site-packages"])
def test_environment_prefers_top_level_and_normalizes_only_distribution_names(tmp_path, layout):
    metadata = tmp_path / layout / "PyYAML-6.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "top_level.txt").write_text("yaml\n_yaml\nyaml\nPIL\nnot.valid\n")
    (metadata / "RECORD").write_text("wrong/__init__.py,,\n")
    environment = PythonEnvironment(str(tmp_path))
    result = environment.installed_import_names("pyyaml")
    assert result.names == ("PIL", "_yaml", "yaml")
    assert result.version == "6"
    assert environment.installed_import_names("PyYAML") == result


def test_record_only_infers_packages_modules_and_extensions(tmp_path):
    metadata = tmp_path / "lib/python3.11/site-packages/pkg-1.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "RECORD").write_text(
        "alpha/__init__.py,,\nbeta.py,,\ncharlie.cpython-311-x86_64-linux-gnu.so,,\ndelta.pyd,,\n"
        "google/auth/__init__.py,,\n__pycache__/x.pyc,,\npkg-1.dist-info/METADATA,,\n"
        "pkg.data/data/file,,\n../../../bin/tool,,\n/absolute/pkg.py,,\n"
        "bad/../module.py,,\neditable.pth,,\n"
    )
    assert PythonEnvironment(str(tmp_path)).installed_import_names("pkg").names == (
        "alpha",
        "beta",
        "charlie",
        "delta",
        "google",
    )


@pytest.mark.parametrize("state", ["missing", "file", "empty", "multiple"])
def test_invalid_environment_layouts_raise_configuration_error(state, tmp_path):
    root = tmp_path / "env"
    if state == "file":
        root.touch()
    elif state != "missing":
        root.mkdir()
        if state == "multiple":
            for version in ("3.11", "3.12"):
                (root / f"lib/python{version}/site-packages").mkdir(parents=True)
    with pytest.raises(PythonEnvironmentError):
        PythonEnvironment(str(root))


def test_metadata_symlink_cannot_escape_environment_but_safe_record_can_resolve(tmp_path):
    root = tmp_path / "env"
    metadata = root / "lib/python3.11/site-packages/pkg-1.dist-info"
    metadata.mkdir(parents=True)
    target = tmp_path / "outside"
    target.write_text("stolen")
    (metadata / "top_level.txt").symlink_to(target)
    (metadata / "RECORD").write_text("safe/__init__.py,,\n")
    assert PythonEnvironment(str(root)).installed_import_names("pkg").names == ("safe",)


def test_site_packages_symlink_cannot_escape_environment(tmp_path):
    root = tmp_path / "env"
    lib = root / "lib/python3.11"
    lib.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (lib / "site-packages").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PythonEnvironmentError):
        PythonEnvironment(str(root))
