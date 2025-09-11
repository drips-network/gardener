"""
Resolver for Python package imports
"""

import io
import re
import tarfile
import zipfile

import requests

from gardener.common.secure_file_ops import FileOperationError
from gardener.package_metadata.name_resolvers.base import BaseResolver


class PythonResolver(BaseResolver):
    """
    Resolver for Python package imports

    Handles the complex mapping from PyPI package names to importable module names
    by analyzing package metadata and contents
    """

    def __init__(self, secure_file_ops=None):
        """
        Args:
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations
        """
        super().__init__(secure_file_ops)

    def resolve_from_manifest(self, manifest_path, logger=None, packages=None, **kwargs):
        """
        Resolve imports from requirements.txt or pyproject.toml

        Note: This is simplified, as Python package detection is often done from
        file imports rather than manifest files. For full resolution, use
        resolve_package_imports directly

        Args:
            manifest_path (str): Path to requirements.txt or pyproject.toml
            logger (Logger): Optional logger instance
            packages (list): Optional list of packages to resolve (overrides file parsing)
            **kwargs: Additional resolver-specific parameters

        Returns:
            dict: Mapping of {package_name: [import_names]}
        """
        logger and logger.debug(f"Resolving imports from Python manifest: {manifest_path}")

        # If explicit packages provided, use those
        if packages:
            return self._resolve_package_list(packages, logger)

        try:
            content = self.read_file_content(manifest_path)
        except FileOperationError as e:
            logger and logger.error(f"Failed to read {manifest_path}: {e}")
            return {}
        except Exception as e:
            logger and logger.error(f"Unexpected error reading {manifest_path}: {e}")
            return {}

        # Simple parsing for requirements.txt
        if manifest_path.endswith(".txt"):
            packages = []
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # NB: this is a simple parser that might not handle all requirements.txt formats
                package = line.split("==")[0].split(">")[0].split("<")[0].split("~=")[0].split("!=")[0].strip()
                if package:
                    packages.append(package)

            return self._resolve_package_list(packages)

        # Future enhancement: Add support for pyproject.toml

        return {}

    def _resolve_package_list(self, packages, logger=None):
        """
        Resolve a list of package names to their import names

        Args:
            packages (list): List of package names to resolve
            logger (Logger): Optional logger instance

        Returns:
            dict: Mapping of {package_name: [import_names]}
        """
        result = {}
        for package in packages:
            import_names = self.resolve_package_imports(package, logger=logger)
            if import_names:
                result[package] = import_names

        return result

    def _process_distribution_name(self, dist_name):
        """
        Process a distribution name into potential import names

        Args:
            dist_name (str): Distribution name to process

        Returns:
            list: List of potential import names
        """
        result = []

        # Replace dashes with underscores as a common convention
        underscore_name = dist_name.replace("-", "_")
        result.append(underscore_name)

        # If package name follows a common pattern, add additional possibilities
        if dist_name.startswith("python-"):
            # Packages starting with 'python-' often drop this prefix for import
            base_name = dist_name[len("python-") :]
            base_with_underscores = base_name.replace("-", "_")
            if base_with_underscores not in result:
                result.append(base_with_underscores)

            # Special case: python-X-bot often is imported as just X
            if base_name.endswith("-bot"):
                core_name = base_name[:-4]
                if core_name not in result:
                    result.append(core_name)

        if "-" in dist_name and not dist_name.startswith("python-"):
            parts = dist_name.split("-")
            if len(parts) >= 2:
                # For packages like django-rest-framework, add the first part as a potential import
                if parts[0] not in result:
                    result.append(parts[0])

                # For packages with multiple parts, also add the subsequent parts joined with underscores
                if len(parts) > 2:
                    # e.g., django-rest-framework -> rest_framework
                    remaining = "_".join(parts[1:])
                    if remaining not in result:
                        result.append(remaining)

        # Specific cases for scoped packages
        if dist_name.startswith("@"):
            parts = dist_name.split("/")
            if len(parts) >= 2:
                # Use the package part without the scope
                package_part = parts[1].replace("-", "_")
                if package_part not in result:
                    result.append(package_part)

        return result

    def resolve_package_imports(self, package_name, version=None, logger=None):
        """
        Resolve a single package name to its import names

        Args:
            package_name (str): Name of the package on PyPI
            version (str): Optional specific version to resolve
            logger (Logger): Optional logger instance

        Returns:
            list: List of possible import names for the package
        """
        # First use the direct mapping approach
        import_names = self._process_distribution_name(package_name)

        # Also use PyPI metadata
        try:
            pypi_names = resolve_python_import_names(package_name, version, logger)
            if pypi_names:
                import_names.extend(pypi_names)
        except Exception as e:
            # Log but continue with what we have
            if logger:
                logger.debug(f"PyPI fallback failed for {package_name}: {e}")

        # Deduplicate the list while preserving order
        seen = set()
        deduplicated = []
        for name in import_names:
            if name not in seen:
                seen.add(name)
                deduplicated.append(name)

        return deduplicated


def transform_package_name(pkg_name):
    """
    Transform a PyPI package name to a potential import name using heuristics

    Applies common naming patterns to convert distribution names to import names:
    - Strips 'python-' prefix when present
    - Strips '-bot' suffix for certain packages
    - Replaces dashes with underscores

    Args:
        pkg_name (str): PyPI distribution package name

    Returns:
        Transformed import name based on common patterns
    """
    if pkg_name.startswith("python-"):
        name = pkg_name[len("python-") :]
        if name.endswith("-bot"):
            name = name[: -len("-bot")]
        return name
    return pkg_name.replace("-", "_")


def infer_top_level_names_from_paths(paths, package_name=None, logger=None):
    """
    Infer top-level import names from archive file paths

    Analyzes the structure of files in a Python package archive to determine
    the intended import names. Uses multiple strategies including common prefix
    detection, __init__.py discovery, and fallback transformations

    Args:
        paths (list): List of file paths from the package archive
        package_name (str): Optional package name for fallback transformations
        logger (Logger): Optional logger instance

    Returns:
        List of inferred top-level import names
    """
    # Filter out metadata directories (dist-info, egg-info, data)
    non_meta = [p for p in paths if not re.search(r"(\.dist-info|\.egg-info|\.data)", p)]
    if not non_meta:
        non_meta = paths

    def split_path(p):
        """
        Split a path string into a list of directory/file components,
        removing leading/trailing slashes

        Args:
            p (str): Path string to split

        Returns:
            List of path components
        """
        return p.strip("/").split("/")

    split_paths = [split_path(p) for p in non_meta if p.strip()]
    if not split_paths:
        return []

    # Compute longest common prefix among all paths
    common_prefix = []
    for components in zip(*split_paths):
        if all(x == components[0] for x in components):
            common_prefix.append(components[0])
        else:
            break

    # If the common prefix is non-empty and not just 'src', use its first element
    # (This is valid for wheels that package files under a single folder.)
    if common_prefix:
        if common_prefix[0].lower() != "src":
            logger and logger.debug(f"Common prefix found: {common_prefix[0]}")
            return [common_prefix[0]]
    # If common prefix is 'src', remove it and recompute
    trimmed_paths = []
    for comps in split_paths:
        if comps and comps[0].lower() == "src":
            if len(comps) > 1:
                trimmed_paths.append(comps[1:])
            else:
                trimmed_paths.append(comps)
        else:
            trimmed_paths.append(comps)
    new_common = []
    for components in zip(*trimmed_paths):
        if all(x == components[0] for x in components):
            new_common.append(components[0])
        else:
            break
    if new_common:
        logger and logger.debug(f"Common prefix after trimming 'src': {new_common[0]}")
        return [new_common[0]]

    # Otherwise, fall back to gathering candidates
    candidates = set()
    for comps in trimmed_paths:
        # Look for a directory with __init__.py or a single .py file that is not __init__
        if len(comps) >= 2 and comps[1] == "__init__.py":
            candidates.add(comps[0])
        elif len(comps) == 1 and comps[0].endswith(".py"):
            name = comps[0][:-3]
            if name != "__init__":
                candidates.add(name)
    candidates = sorted(candidates)
    # If we have many fragmented candidates, try a fallback transformation
    if len(candidates) > 3 and package_name is not None:
        fallback = transform_package_name(package_name)
        logger and logger.info(f"Falling back to transformation for {package_name} -> {fallback}")
        return [fallback]
    return candidates


def extract_from_zip(file_bytes, package_name=None, logger=None):
    """
    Extract import name candidates from a ZIP archive (wheel or zip sdist)

    Attempts to read top_level.txt from .dist-info directories first,
    then falls back to path-based inference

    Args:
        file_bytes (bytes): Binary content of the ZIP archive
        package_name (str): Optional package name for fallback heuristics
        logger (Logger): Optional logger instance

    Returns:
        List of candidate import names
    """
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            file_list = z.namelist()
            # First try to read top_level.txt from .dist-info folder
            top_level_content = None
            for name in file_list:
                if name.endswith("top_level.txt") and ".dist-info/" in name:
                    try:
                        top_level_content = z.read(name).decode("utf-8")
                        break
                    except Exception as e:
                        logger and logger.debug(f"Error reading {name}: {e}")
            if top_level_content:
                import_names = [line.strip() for line in top_level_content.splitlines() if line.strip()]
                if import_names:
                    return import_names
            # Fallback: infer from all file paths
            return infer_top_level_names_from_paths(file_list, package_name, logger)
    except zipfile.BadZipFile as e:
        logger and logger.error(f"Bad zip file: {e}")
        return []


def extract_from_tar(file_bytes, package_name=None, logger=None):
    """
    Extract import name candidates from a sdist tarball

    Attempts to read top_level.txt from metadata directories first,
    then falls back to path-based inference

    Args:
        file_bytes (bytes): Binary content of the TAR archive
        package_name (str): Optional package name for fallback heuristics
        logger (Logger): Optional logger instance

    Returns:
        List of candidate import names
    """
    try:
        with tarfile.open(fileobj=io.BytesIO(file_bytes), mode="r:*") as tar:
            file_list = tar.getnames()
            top_level_content = None
            for name in file_list:
                if name.endswith("top_level.txt") and re.search(r"(\.dist-info|\.egg-info)", name):
                    try:
                        member = tar.getmember(name)
                        f = tar.extractfile(member)
                        if f:
                            top_level_content = f.read().decode("utf-8")
                            break
                    except Exception as e:
                        logger and logger.debug(f"Error reading {name} from tar: {e}")
            if top_level_content:
                import_names = [line.strip() for line in top_level_content.splitlines() if line.strip()]
                if import_names:
                    return import_names
            return infer_top_level_names_from_paths(file_list, package_name, logger)
    except tarfile.TarError as e:
        logger and logger.error(f"Tar error: {e}")
        return []


def get_archive_import_names(file_bytes, archive_format, package_name=None, logger=None):
    """
    Extract import names from a package archive

    Args:
        file_bytes (bytes): Binary content of the archive
        archive_format (str): Either 'zip' or 'tar'
        package_name (str): Optional package name for fallback heuristics
        logger (Logger): Optional logger instance
    """
    if archive_format == "zip":
        return extract_from_zip(file_bytes, package_name, logger)
    elif archive_format == "tar":
        return extract_from_tar(file_bytes, package_name, logger)
    else:
        logger and logger.error(f"Unsupported archive format: {archive_format}")
        return []


def choose_wheel_file(release_files, logger=None):
    """
    Choose the best wheel file from PyPI release files

    Prefers universal wheels (py3-none-any) over platform-specific ones
    for maximum compatibility during import name analysis

    Args:
        release_files (list): List of release file metadata from PyPI
        logger (Logger): Optional logger instance

    Returns:
        URL of the selected wheel file, or None if no wheels found
    """
    wheels = [fi for fi in release_files if fi.get("filename", "").endswith(".whl")]
    if not wheels:
        return None
    for fi in wheels:
        if "py3-none-any" in fi.get("filename", "").lower():
            return fi.get("url")
    return wheels[0].get("url")


def choose_sdist_file(release_files, logger=None):
    """
    Choose a source distribution file from PyPI release files

    Selects tar.gz or zip files while excluding wheels, providing
    fallback archive access when wheels are unavailable

    Args:
        release_files (list): List of release file metadata from PyPI
        logger (Logger): Optional logger instance

    Returns:
        Tuple of (archive_url, archive_format) or (None, None) if not found
    """
    for fi in release_files:
        fname = fi.get("filename", "")
        if not fname.endswith(".whl") and (fname.endswith(".tar.gz") or fname.endswith(".zip")):
            archive_format = "tar" if fname.endswith(".tar.gz") else "zip"
            return fi.get("url"), archive_format
    return None, None


def resolve_python_import_names(package_name, version_override=None, logger=None):
    """
    Resolve top-level import names for a PyPI package by analyzing its distribution

    Downloads and analyzes package archives from PyPI to determine the actual
    import names. Prefers wheels over source distributions for faster processing

    Args:
        package_name (str): Name of the package on PyPI
        version_override (str): Optional specific version to resolve (uses latest if None)
        logger (Logger): Optional logger instance

    Returns:
        List of resolved import names, or empty list if resolution fails
    """
    pypi_url = f"https://pypi.org/pypi/{package_name}/json"
    logger and logger.debug(f"Fetching PyPI metadata for {package_name}")

    try:
        response = requests.get(pypi_url, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logger and logger.error(f"Failed to fetch metadata for {package_name}: {e}")
        return []

    data = response.json()
    version = version_override if version_override else data.get("info", {}).get("version")
    if not version:
        logger and logger.error(f"No version information available for {package_name}")
        return []

    release_files = data.get("releases", {}).get(version, [])
    if not release_files:
        logger and logger.error(f"No files found for {package_name} version {version}")
        return []

    archive_url = choose_wheel_file(release_files, logger)
    archive_format = "zip"
    if archive_url:
        logger and logger.debug(f"Using wheel from {archive_url}")
    else:
        archive_url, archive_format = choose_sdist_file(release_files, logger)
        if not archive_url:
            logger and logger.debug(f"No suitable archive (wheel or sdist) for {package_name} version {version}")
            return []
        logger and logger.debug(f"Using sdist from {archive_url}")

    try:
        archive_response = requests.get(archive_url, timeout=15)
        archive_response.raise_for_status()
    except Exception as e:
        logger and logger.error(f"Failed to download archive from {archive_url}: {e}")
        return []

    candidates = get_archive_import_names(archive_response.content, archive_format, package_name, logger)
    # If inference returns many fragmented candidates, try a fallback transform
    if len(candidates) > 3:
        fallback = transform_package_name(package_name)
        logger and logger.debug(
            f"Candidates appear fragmented; using fallback transformation for {package_name} -> {fallback}"
        )
        return [fallback]

    # Don't add the original package_name as-is if it's not already in candidates
    # Instead, transform it to replace dashes with underscores which is more likely to match import names
    transformed_name = transform_package_name(package_name)

    # Combine and deduplicate
    results = list(candidates)
    if transformed_name not in results:
        results.append(transformed_name)

    return results
