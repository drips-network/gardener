"""
Manifest processing helpers for RepositoryAnalyzer

Provides utilities to read and process manifest files across ecosystems,
deduplicate and normalize package entries, and resolve version conflicts
"""

import json
import os
import re
from pathlib import Path

from gardener.package_metadata.name_resolvers.go import GoResolver
from gardener.package_metadata.name_resolvers.json_manifest import JsonManifestResolver
from gardener.package_metadata.name_resolvers.python import PythonResolver
from gardener.package_metadata.name_resolvers.rust import RustResolver


def _read_file(path, secure_file_ops):
    """
    Read a text file using SecureFileOps when available

    Args:
        path (str): Absolute file path
        secure_file_ops (SecureFileOps|None): Secure file operations instance or None

    Returns:
        str: File content as text
    """
    if secure_file_ops:
        rel = secure_file_ops.get_relative_path(path)
        return secure_file_ops.read_file(rel)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _read_json(path, secure_file_ops):
    """
    Read a JSON file using SecureFileOps when available

    Args:
        path (str): Absolute file path
        secure_file_ops (SecureFileOps|None): Secure file operations instance or None

    Returns:
        dict: Parsed JSON object
    """
    if secure_file_ops:
        rel = secure_file_ops.get_relative_path(path)
        return secure_file_ops.read_json(rel)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def collect_root_package_names_and_workspaces(root_manifest_files, secure_file_ops, logger, repo_path):
    """
    Inspect root-level manifests to collect package names and workspace members

    Args:
        root_manifest_files (list): Absolute paths to manifests in repo root
        secure_file_ops (SecureFileOps|None): Secure file ops or None
        logger (Logger|None): Optional logger for notes and warnings
        repo_path (str): Absolute repository path

    Returns:
        Tuple of (root package name set, go module path or None)
    """
    root_names = set()
    go_module_path = None

    for manifest_file in root_manifest_files:
        basename = Path(manifest_file).name
        name, go_candidate = _get_package_name_from_manifest(
            manifest_file, basename, secure_file_ops, logger, repo_path
        )
        if name:
            root_names.add(name)
            if logger:
                logger.debug(f"Identified root package name '{name}' from {basename}")
        if go_candidate and go_module_path is None:
            go_module_path = go_candidate
            if logger:
                logger.info(f"Identified Go module path: {go_module_path}")

        if basename == "package.json":
            try:
                data = _read_json(manifest_file, secure_file_ops)
                dep_sections = [
                    data.get("dependencies", {}),
                    data.get("devDependencies", {}),
                    data.get("peerDependencies", {}),
                    data.get("optionalDependencies", {}),
                ]
                pnpm_cfg = data.get("pnpm")
                if isinstance(pnpm_cfg, dict):
                    overrides = pnpm_cfg.get("overrides")
                    if isinstance(overrides, dict):
                        dep_sections.append(overrides)
                    patched = pnpm_cfg.get("patchedDependencies")
                    if isinstance(patched, dict):
                        dep_sections.append({key: "patched" for key in patched})
                for section in dep_sections:
                    if isinstance(section, dict):
                        for dep_name, version in section.items():
                            if isinstance(version, str) and "workspace:" in version:
                                if dep_name not in root_names:
                                    root_names.add(dep_name)
            except Exception as exc:
                if logger:
                    logger.warning(
                        f"Error checking root package.json for workspace:* dependencies: {exc}"
                    )

    return root_names, go_module_path


def _get_package_name_from_manifest(path, basename, secure_file_ops, logger, repo_path):
    """
    Extract a canonical package or module name from a manifest

    Args:
        path (str): Absolute manifest path
        basename (str): Base filename of the manifest
        secure_file_ops (SecureFileOps|None): Secure file operations or None
        logger (Logger|None): Optional logger
        repo_path (str): Absolute repository path

    Returns:
        Tuple of (package name or None, go module path or None)
    """
    try:
        if basename == "package.json":
            data = _read_json(path, secure_file_ops)
            return data.get("name"), None

        content = _read_file(path, secure_file_ops)
        if basename == "pyproject.toml":
            match = re.search(
                r"\[project\]\s*.*?name\s*=\s*['\"]([^'\"]+)['\"]", content, re.DOTALL | re.IGNORECASE
            )
            if match:
                return match.group(1), None
        elif basename == "Cargo.toml":
            match = re.search(
                r"\[package\]\s*.*?name\s*=\s*['\"]([^'\"]+)['\"]", content, re.DOTALL | re.IGNORECASE
            )
            if match:
                return match.group(1), None
        elif basename == "go.mod":
            match = re.search(r"^module\s+([^\s]+)", content, re.MULTILINE)
            if match:
                module_path = match.group(1)
                return module_path, module_path
    except Exception as exc:
        if logger:
            logger.warning(f"Could not parse module name from {basename} {path}: {exc}")
    return None, None


def process_manifests(manifest_files, language_handlers, secure_file_ops, logger):
    """
    Process manifests using registered language handlers with deduplication semantics

    Args:
        manifest_files (list): Absolute paths to manifest files discovered in repo
        language_handlers (dict): Language handler instances keyed by language
        secure_file_ops (SecureFileOps|None): Secure file operations or None
        logger (Logger|None): Optional logger for status and errors

    Returns:
        dict: External package metadata map keyed by distribution name
    """
    external_packages = {}

    for manifest_path in list(manifest_files):
        basename = Path(manifest_path).name
        for handler_lang, handler in language_handlers.items():
            if basename not in handler.get_manifest_files():
                continue
            try:
                temp_packages = {}
                handler.process_manifest(manifest_path, temp_packages, secure_file_ops)
                for package_name, package_info in temp_packages.items():
                    if package_name in external_packages:
                        external_packages[package_name] = _deduplicate_package(
                            package_name,
                            external_packages[package_name],
                            package_info,
                            manifest_path,
                        )
                    else:
                        package_info["found_in_manifests"] = [manifest_path]
                        external_packages[package_name] = package_info
            except Exception as exc:
                if logger:
                    logger.exception(
                        f"Error processing manifest {manifest_path} with {handler_lang} handler"
                    )
    return external_packages


def _deduplicate_package(package_name, existing_package, new_package_info, manifest_path):
    """
    Merge duplicate package entries while tracking version conflicts

    Args:
        package_name (str): Distribution name
        existing_package (dict): Current canonical package metadata
        new_package_info (dict): Newly parsed package metadata
        manifest_path (str): Manifest where the new entry was found

    Returns:
        dict: Updated canonical package metadata
    """
    if "found_in_manifests" not in existing_package:
        existing_package["found_in_manifests"] = []
    existing_package["found_in_manifests"].append(manifest_path)

    existing_version = existing_package.get("version", "")
    new_version = new_package_info.get("version", "")

    if existing_version and new_version and existing_version != new_version:
        if "version_conflicts" not in existing_package:
            existing_package["version_conflicts"] = []
            original_conflict = {
                "manifest": (
                    existing_package["found_in_manifests"][0]
                    if existing_package.get("found_in_manifests")
                    else "unknown"
                ),
                "version": existing_version,
            }
            existing_package["version_conflicts"].append(original_conflict)

        conflict_info = {"manifest": manifest_path, "version": new_version}
        if conflict_info not in existing_package["version_conflicts"]:
            existing_package["version_conflicts"].append(conflict_info)
    elif new_version and not existing_version:
        existing_package["version"] = new_version

    for key, value in new_package_info.items():
        if key in ["version", "ecosystem"]:
            continue
        if key not in existing_package:
            existing_package[key] = value

    return existing_package


def attach_import_names(external_packages, secure_file_ops, logger):
    """
    Attach import names for known ecosystems

    Args:
        external_packages (dict): Package metadata map keyed by distribution name
        secure_file_ops (SecureFileOps|None): Secure file operations or None
        logger (Logger|None): Optional logger

    Returns:
        dict: Package metadata map with `import_names` populated
    """
    resolvers = {
        "pypi": PythonResolver,
        "go": GoResolver,
        "cargo": RustResolver,
        "npm": JsonManifestResolver,
    }

    for dist_name, metadata in external_packages.items():
        if "import_names" in metadata:
            continue
        ecosystem = metadata.get("ecosystem")
        resolver_cls = resolvers.get(ecosystem)
        if resolver_cls:
            resolver = resolver_cls(secure_file_ops=secure_file_ops)
            names = resolver.resolve_package_imports(dist_name, logger=logger)
            metadata["import_names"] = names if names else [dist_name]
        else:
            metadata["import_names"] = [dist_name]
    return external_packages


def resolve_version_conflicts(external_packages, logger):
    """
    Args:
        external_packages (dict): Package metadata map keyed by distribution name
        logger (Logger|None): Optional logger for conflict summaries

    Returns:
        None
    """
    for package_name, package_info in external_packages.items():
        if "version_conflicts" not in package_info:
            continue

        versions = []
        for conflict in package_info["version_conflicts"]:
            version = conflict.get("version")
            if version and version not in versions:
                versions.append(version)

        if len(versions) <= 1:
            continue

        resolved = versions[0]
        for version in versions[1:]:
            resolved = resolve_version_conflict(resolved, version)

        package_info["version"] = resolved
        package_info["version_conflicts"] = [
            conflict for conflict in package_info["version_conflicts"] if conflict.get("version") != resolved
        ]

        if logger:
            conflict_summary = ", ".join(
                [f"{conflict['version']} (from {conflict['manifest']})" for conflict in package_info["version_conflicts"]]  # noqa
            )
            logger.warning(
                f"Version conflict for package '{package_name}': {conflict_summary}. Resolved to: {resolved}"
            )


def resolve_version_conflict(version1, version2):
    """
    Args:
        version1 (str): First version string
        version2 (str): Second version string

    Returns:
        str: Selected version according to project rules
    """
    if "workspace:" in version1:
        return version2
    if "workspace:" in version2:
        return version1

    if version1 in ["latest", "*"]:
        return version2
    if version2 in ["latest", "*"]:
        return version1

    try:
        parsed_v1 = parse_semver(version1)
        parsed_v2 = parse_semver(version2)
        if parsed_v1 and parsed_v2:
            for index in range(3):
                if parsed_v1[index] > parsed_v2[index]:
                    return version1
                if parsed_v1[index] < parsed_v2[index]:
                    return version2
    except Exception:
        pass

    if any(char in version1 for char in "^~><"):
        if not any(char in version2 for char in "^~><"):
            return version2
    elif any(char in version2 for char in "^~><"):
        return version1

    return version1


def parse_semver(version_str):
    """
    Parse a semantic version string into (major, minor, patch)

    Args:
        version_str (str): Version string that may include range symbols

    Returns:
        tuple|None: (major, minor, patch) if parseable, otherwise None
    """
    cleaned = version_str.lstrip("^~>=<")
    parts = cleaned.split(".")
    if len(parts) >= 3:
        try:
            major = int(parts[0])
            minor = int(parts[1])
            patch_part = parts[2].split("-")[0]
            patch = int(patch_part) if patch_part else 0
            return (major, minor, patch)
        except ValueError:
            return None
    return None


def get_conflict_summary(external_packages):
    """
    Summarize version conflicts

    Args:
        external_packages (dict): Package metadata map with conflict info

    Returns:
        dict: Summary keyed by package with resolved version and conflicts
    """
    summary = {}
    for name, info in external_packages.items():
        if "version_conflicts" in info:
            summary[name] = {
                "resolved_version": info.get("version"),
                "conflicts": info["version_conflicts"],
                "found_in_manifests": info.get("found_in_manifests", []),
            }
    return summary
