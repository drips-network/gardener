"""Static Python lockfile and installed-distribution metadata"""

import csv
import io
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from gardener.common.secure_file_ops import FileOperationError, SecureFileOps, SecurityError
from gardener.common.utils import Logger

PYTHON_LOCKFILE_NAMES = ("uv.lock", "poetry.lock", "pylock.toml")
_PYPI_SIMPLE_INDEX = "https://pypi.org/simple"


class ImportNames(NamedTuple):
    """Names supplied by metadata for one release"""

    names: tuple[str, ...]
    version: str


class LockEntry(NamedTuple):
    """A locked version and whether public PyPI can supply its metadata"""

    version: str | None
    source_is_pypi: bool


def normalize_distribution_name(name: str) -> str:
    """Normalize distribution lookup keys, not case-sensitive import names"""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_python_lockfile(filename: str, content: str) -> dict[str, set[LockEntry]]:
    """Parse consumed lock fields; raise ValueError for malformed input"""
    array = {"uv.lock": "package", "poetry.lock": "package", "pylock.toml": "packages"}[filename]
    packages = tomllib.loads(content).get(array, [])
    if not isinstance(packages, list):
        raise ValueError(f"{array} must be an array of tables")
    result: dict[str, set[LockEntry]] = {}
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("Lock package must be a table")
        name = package.get("name")
        version = package.get("version")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Lock package requires a nonempty name")
        if version is not None and (not isinstance(version, str) or not version.strip()):
            raise ValueError(f"Invalid locked version for {name}")
        source_is_pypi = _lock_source_is_pypi(filename, package, name)
        key = normalize_distribution_name(name)
        result.setdefault(key, set()).add(LockEntry(version, source_is_pypi))
    return result


def _lock_source_is_pypi(filename: str, package: dict[str, object], name: str) -> bool:
    if filename == "pylock.toml":
        index = package.get("index")
        if index is not None and not isinstance(index, str):
            raise ValueError(f"Invalid index for {name}")
        source_is_pypi = not any(key in package for key in ("vcs", "directory", "archive")) and (
            index is None or index.rstrip("/") == _PYPI_SIMPLE_INDEX
        )
    else:
        source = package.get("source")
        if source is not None and not isinstance(source, dict):
            raise ValueError(f"Invalid source for {name}")
        if filename == "poetry.lock":
            source_is_pypi = source is None
        else:
            registry = source.get("registry") if source is not None else None
            if registry is not None and not isinstance(registry, str):
                raise ValueError(f"Invalid registry for {name}")
            source_is_pypi = registry is not None and registry.rstrip("/") == _PYPI_SIMPLE_INDEX
    return source_is_pypi


class PythonEnvironmentError(ValueError):
    """The explicitly selected environment cannot be inspected"""


class PythonEnvironment:
    """Read one environment's contained dist-info metadata without running its code"""

    def __init__(self, env_path: str, logger: Logger | None = None):
        self.logger = logger
        try:
            self.file_ops = SecureFileOps(env_path, logger)
            self.site_packages = self._find_site_packages(env_path)
            self.distributions: dict[str, list[tuple[Path, str]]] = {}
            for directory in sorted(self.file_ops.list_dir(self.site_packages)):
                if not directory.name.endswith(".dist-info") or not self.file_ops.is_dir(directory):
                    continue
                name, separator, version = directory.name.removesuffix(".dist-info").partition("-")
                if not name or not separator or not version or "-" in version:
                    if logger:
                        logger.warning(f"Invalid distribution metadata directory: {directory.name}")
                    continue
                self.distributions.setdefault(normalize_distribution_name(name), []).append((directory, version))
        except (FileOperationError, SecurityError, OSError) as exc:
            raise PythonEnvironmentError(f"Cannot read Python environment {env_path}: {exc}") from exc
        if logger:
            logger.info(f"Python environment: {self.site_packages} ({len(self.distributions)} distributions)")

    def _find_site_packages(self, env_path: str) -> Path:
        candidates: set[Path] = set()
        if self.file_ops.is_dir("lib"):
            for directory in self.file_ops.list_dir("lib"):
                site_packages = directory / "site-packages"
                if directory.name.startswith("python3.") and self.file_ops.is_dir(site_packages):
                    candidates.add(self.file_ops.secure_access.validate_path(site_packages))
        if self.file_ops.is_dir("Lib/site-packages"):
            candidates.add(self.file_ops.secure_access.validate_path("Lib/site-packages"))
        if len(candidates) != 1:
            raise PythonEnvironmentError(
                f"Expected one lib/python3.*/site-packages or Lib/site-packages in {env_path}; "
                f"found {len(candidates)}"
            )
        return candidates.pop()

    def installed_import_names(self, package_name: str) -> ImportNames | None:
        """Return static import names, or absence with a diagnostic for unusable metadata"""
        entries = self.distributions.get(normalize_distribution_name(package_name), [])
        if len(entries) != 1:
            if self.logger:
                log = self.logger.warning if entries else self.logger.debug
                log(f"Python environment has {len(entries)} metadata entries for {package_name}")
            return None
        directory, version = entries[0]
        for filename in ("top_level.txt", "RECORD"):
            path = directory / filename
            try:
                if not self.file_ops.is_file(path):
                    continue
                content = self.file_ops.read_file(path)
                if filename == "top_level.txt":
                    names = {line.strip() for line in content.splitlines() if line.strip().isidentifier()}
                    names.discard("__pycache__")
                else:
                    names = _record_import_names(content)
                if names:
                    return ImportNames(tuple(sorted(names)), version)
            except (FileOperationError, SecurityError, OSError, csv.Error) as exc:
                if self.logger:
                    self.logger.warning(f"Cannot read Python metadata {path}: {exc}")
        if self.logger:
            self.logger.debug(f"No usable installed import names for {package_name}; resolving from lockfile/PyPI")
        return None


def _record_import_names(content: str) -> set[str]:
    names = set()
    for row in csv.reader(io.StringIO(content), strict=True):
        if not row:
            continue
        path = PurePosixPath(row[0])
        if not path.parts or path.is_absolute() or ".." in path.parts:
            continue
        if len(path.parts) > 1:
            name = path.parts[0]
        elif path.suffix in (".py", ".so", ".pyd"):
            name = path.name.split(".", 1)[0]
        else:
            continue
        if name.isidentifier() and name != "__pycache__":
            names.add(name)
    return names
