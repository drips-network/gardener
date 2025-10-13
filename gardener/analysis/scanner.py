"""
Repository scanning helpers
"""

import os
import re
from pathlib import Path

import pathspec

from gardener.common.defaults import ResourceLimits
from gardener.common.language_detection import filename_to_lang

# Local constants for JS/TS detection parity
JS_TS_SOURCE_EXTS = [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"]


def load_gitignore(secure_file_ops, logger):
    """
    Load .gitignore using secure file operations when available

    Args:
        secure_file_ops (SecureFileOps|None): SecureFileOps instance if available
        logger (Logger|None): Optional logger

    Returns:
        pathspec.PathSpec|None: Compiled gitignore rules
    """
    if not secure_file_ops:
        return None

    gitignore_path = ".gitignore"
    if not secure_file_ops.exists(gitignore_path):
        return None

    try:
        gitignore_content = secure_file_ops.read_file(gitignore_path)
        return pathspec.PathSpec.from_lines(
            pathspec.patterns.GitWildMatchPattern, gitignore_content.splitlines()
        )
    except Exception as exc:
        if logger:
            logger.warning(f"Could not load or parse .gitignore: {exc}")
        return None


def _is_ignored(path, repo_path, gitignore_spec, secure_file_ops):
    """
    Determine whether a path should be ignored according to .gitignore

    Args:
        path (str): Absolute path to test
        repo_path (str): Absolute repository root path
        gitignore_spec (pathspec.PathSpec|None): Compiled matcher or None
        secure_file_ops (SecureFileOps|None): Secure file operations or None

    Returns:
        bool: True when path is ignored by the matcher
    """
    if not gitignore_spec:
        return False

    try:
        if secure_file_ops:
            rel_path = secure_file_ops.get_relative_path(path)
        else:
            rel_path = os.path.relpath(path, repo_path)
    except ValueError:
        return False

    rel_path = str(Path(rel_path))
    return gitignore_spec.match_file(rel_path)


def _parse_foundry_src_path(secure_file_ops, logger):
    """
    Parse foundry.toml at repo root to extract the Solidity src path

    Args:
        secure_file_ops (SecureFileOps|None): Secure file operations or None
        logger (Logger|None): Optional logger for notes and errors

    Returns:
        str|None: Foundry src path if configured, otherwise None
    """
    if not secure_file_ops:
        return None

    rel_path = "foundry.toml"
    if not secure_file_ops.exists(rel_path):
        return None

    try:
        content = secure_file_ops.read_file(rel_path)
        match = re.search(
            r"\[profile\.default\][^\[]*\s*src\s*=\s*['\"]([^'\"]+)['\"]",
            content,
            re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r"\[default\][^\[]*\s*src\s*=\s*['\"]([^'\"]+)['\"]",
                content,
                re.IGNORECASE,
            )
        if match:
            src_path = match.group(1).strip()
            if logger:
                logger.debug(f"Found Solidity src path in foundry.toml: '{src_path}'")
            return src_path
        if logger:
            logger.debug(
                "No 'src' path found under [profile.default] or [default] in foundry.toml"
            )
    except Exception as exc:
        if logger:
            logger.error(f"Error reading or parsing foundry.toml for src path: {exc}")
    return None


def _scan_secure(repo_path, secure_file_ops, gitignore_spec, all_manifest_files,
                 all_extensions, active_languages, logger):
    """
    Secure directory traversal

    Args:
        repo_path (str): Absolute repository path
        secure_file_ops (SecureFileOps): Secure file operations instance
        gitignore_spec (pathspec.PathSpec|None): Compiled matcher or None
        all_manifest_files (set): Set of manifest basenames to collect
        all_extensions (set): File extensions to include in scan
        active_languages (list): Languages that are active for this scan
        logger (Logger|None): Optional logger for progress and warnings

    Returns:
        Tuple of (source_files, manifest_files, root_manifest_files, js_config_files, ts_config_files)
    """
    source_files = {}
    manifest_files = []
    root_manifest_files = []
    js_config_files = []
    ts_config_files = []

    visited_dirs = set()

    def _scan_dir_recursive(dir_path):
        try:
            resolved_path = str(Path(str(dir_path)).resolve())
        except (OSError, RuntimeError) as exc:
            if logger:
                logger.debug(f"Skipping directory due to resolution error: {exc}")
            return

        if resolved_path in visited_dirs:
            if logger:
                logger.debug(f"Already visited directory: {resolved_path}")
            return

        visited_dirs.add(resolved_path)

        try:
            entries = secure_file_ops.list_dir(dir_path)
        except Exception as exc:
            if logger:
                logger.warning(f"Error scanning directory {dir_path}: {exc}")
            return

        try:
            entries = sorted(entries, key=lambda p: p.name)
        except Exception:
            entries = list(entries)

        for entry in entries:
            if entry.name.startswith("."):
                continue

            full_path = str(entry)

            try:
                if not ResourceLimits.FOLLOW_SYMLINKS and Path(full_path).is_symlink():
                    continue
            except Exception:
                pass

            if _is_ignored(full_path, repo_path, gitignore_spec, secure_file_ops):
                continue

            if secure_file_ops.is_dir(entry):
                _scan_dir_recursive(entry)
                continue

            if not secure_file_ops.is_file(entry):
                continue

            rel_path = secure_file_ops.get_relative_path(full_path)
            basename = entry.name
            _, ext = os.path.splitext(basename)

            if basename in all_manifest_files:
                manifest_files.append(full_path)
                if str(Path(rel_path).parent) == ".":
                    root_manifest_files.append(full_path)

            if basename == "jsconfig.json":
                js_config_files.append(full_path)
            elif basename == "tsconfig.json":
                ts_config_files.append(full_path)

            if ext in all_extensions:
                language = filename_to_lang(full_path)
                if language is None:
                    language = {".cjs": "javascript", ".mjs": "javascript", ".svelte": "javascript"}.get(ext)
                if language and language in active_languages:
                    source_files[str(Path(rel_path))] = {
                        "absolute_path": full_path,
                        "language": language,
                    }

    _scan_dir_recursive(repo_path)
    return (
        source_files,
        manifest_files,
        root_manifest_files,
        js_config_files,
        ts_config_files,
    )


def _scan_standard(repo_path, gitignore_spec, all_manifest_files, all_extensions, active_languages, logger):
    """
    Fallback os.walk scan

    Args:
        repo_path (str): Absolute repository path
        gitignore_spec (pathspec.PathSpec|None): Compiled matcher or None
        all_manifest_files (set): Set of manifest basenames to collect
        all_extensions (set): File extensions to include in scan
        active_languages (list): Languages that are active for this scan
        logger (Logger|None): Optional logger for progress and warnings

    Returns:
        Tuple of (source_files, manifest_files, root_manifest_files, js_config_files, ts_config_files)
    """
    source_files = {}
    manifest_files = []
    root_manifest_files = []
    js_config_files = []
    ts_config_files = []

    for root, dirs, files in os.walk(repo_path, topdown=True):
        filtered_dirs = [
            d
            for d in dirs
            if not d.startswith(".")
            and not _is_ignored(str(Path(root) / d), repo_path, gitignore_spec, None)
        ]
        if not ResourceLimits.FOLLOW_SYMLINKS:
            filtered_dirs = [
                d for d in filtered_dirs if not Path(Path(root) / d).is_symlink()
            ]
        dirs[:] = sorted(filtered_dirs)

        for file_name in sorted(files):
            file_path = str(Path(root) / file_name)
            if not ResourceLimits.FOLLOW_SYMLINKS and Path(file_path).is_symlink():
                continue
            if _is_ignored(file_path, repo_path, gitignore_spec, None):
                continue
            try:
                rel_path = str(Path(file_path).relative_to(repo_path))
            except ValueError:
                rel_path = os.path.relpath(file_path, repo_path)
            rel_path = str(Path(rel_path))
            basename = Path(file_path).name
            _, ext = os.path.splitext(basename)

            if basename in all_manifest_files:
                manifest_files.append(file_path)
                if str(Path(rel_path).parent) == ".":
                    root_manifest_files.append(file_path)

            if basename == "jsconfig.json":
                js_config_files.append(file_path)
            elif basename == "tsconfig.json":
                ts_config_files.append(file_path)

            if ext in all_extensions:
                language = filename_to_lang(file_path)
                if language is None:
                    language = {".cjs": "javascript", ".mjs": "javascript", ".svelte": "javascript"}.get(ext)
                if language and language in active_languages:
                    source_files[rel_path] = {"absolute_path": file_path, "language": language}

    return (
        source_files,
        manifest_files,
        root_manifest_files,
        js_config_files,
        ts_config_files,
    )


def parse_gitmodules(repo_path, secure_file_ops, logger):
    """
    Parse .gitmodules and return {normalized_path: url}

    Args:
        repo_path (str): Absolute repository path
        secure_file_ops (SecureFileOps|None): Secure file operations or None
        logger (Logger|None): Optional logger for warnings and errors

    Returns:
        dict: Map of normalized submodule paths to repository URLs
    """
    import configparser

    gitmodules_rel_path = ".gitmodules"

    if secure_file_ops:
        if not secure_file_ops.exists(gitmodules_rel_path):
            return {}
    else:
        gitmodules_abs = Path(repo_path) / gitmodules_rel_path
        if not gitmodules_abs.exists():
            return {}

    config = configparser.ConfigParser()
    try:
        if secure_file_ops:
            content = secure_file_ops.read_file(gitmodules_rel_path, encoding="utf-8")
            config.read_string(content)
        else:
            with open(Path(repo_path) / gitmodules_rel_path, "r", encoding="utf-8") as handle:
                config.read_file(handle)

        parsed = {}
        for section in config.sections():
            if config.has_option(section, "path") and config.has_option(section, "url"):
                sub_path_raw = config.get(section, "path")
                url = config.get(section, "url")
                normalized_path = str(Path(sub_path_raw).resolve()).rstrip(os.sep)
                parsed[normalized_path] = url
        return parsed
    except configparser.Error as exc:
        if logger:
            logger.warning(f"Could not parse .gitmodules file at '{gitmodules_rel_path}': {exc}")
        return {}
    except Exception as exc:
        if logger:
            logger.error(
                f"An unexpected error occurred while parsing .gitmodules at '{gitmodules_rel_path}': {exc}"
            )
        return {}


def scan_repository(repo_path, secure_file_ops, focus_languages, language_handlers, logger):
    """
    High-level entry point

    Args:
        repo_path (str): Absolute repository path
        secure_file_ops (SecureFileOps|None): Secure file operations or None
        focus_languages (list|None): Subset of languages to analyze or None for all
        language_handlers (dict): Language handler instances keyed by language
        logger (Logger|None): Optional logger for progress and warnings

    Returns:
        dict: Keys: source_files, manifest_files, root_manifest_files, js_config_files,
            ts_config_files, solidity_src_path, submodule_data, gitignore_spec
    """
    gitignore_spec = load_gitignore(secure_file_ops, logger)

    active_languages = focus_languages or list(language_handlers.keys())
    all_manifest_files = set()
    all_extensions = set()

    for lang in active_languages:
        handler = language_handlers.get(lang)
        if not handler:
            continue
        all_manifest_files.update(handler.get_manifest_files())
        all_extensions.update(handler.get_file_extensions())

    if secure_file_ops:
        (
            source_files,
            manifest_files,
            root_manifest_files,
            js_config_files,
            ts_config_files,
        ) = _scan_secure(
            repo_path,
            secure_file_ops,
            gitignore_spec,
            all_manifest_files,
            all_extensions,
            active_languages,
            logger,
        )
    else:
        (
            source_files,
            manifest_files,
            root_manifest_files,
            js_config_files,
            ts_config_files,
        ) = _scan_standard(
            repo_path,
            gitignore_spec,
            all_manifest_files,
            all_extensions,
            active_languages,
            logger,
        )

    solidity_src_path = _parse_foundry_src_path(secure_file_ops, logger)
    submodule_data = parse_gitmodules(repo_path, secure_file_ops, logger)

    return {
        "source_files": source_files,
        "manifest_files": manifest_files,
        "root_manifest_files": root_manifest_files,
        "js_config_files": js_config_files,
        "ts_config_files": ts_config_files,
        "solidity_src_path": solidity_src_path,
        "submodule_data": submodule_data,
        "gitignore_spec": gitignore_spec,
    }
