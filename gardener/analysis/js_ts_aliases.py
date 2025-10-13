"""
JS/TS alias configuration helpers for RepositoryAnalyzer

Parses tsconfig.json/jsconfig.json to extract baseUrl and paths and
constructs a UnifiedAliasResolver for consistent alias handling
"""

import json
import os
import re
from pathlib import Path

from gardener.common.alias_config import AliasConfiguration, UnifiedAliasResolver


def parse_ts_js_config(repo_path, js_config_files, ts_config_files, secure_file_ops, logger):
    """
    Parse root-level tsconfig/jsconfig for baseUrl and paths

    Args:
        repo_path (str): Absolute repository path
        js_config_files (list): Absolute paths to discovered jsconfig.json files
        ts_config_files (list): Absolute paths to discovered tsconfig.json files
        secure_file_ops (SecureFileOps|None): Secure file operations or None
        logger (Logger|None): Optional logger for notes and warnings

    Returns:
        Tuple of (base_url or None, paths dict)
    """

    def _root_relative(path):
        if secure_file_ops:
            rel = secure_file_ops.get_relative_path(path)
        else:
            rel = os.path.relpath(path, repo_path)
        return str(Path(rel))

    def _find_root_config(config_paths):
        roots = [path for path in config_paths if str(Path(_root_relative(path)).parent) == "."]
        if not roots:
            return None
        chosen = roots[0]
        if logger:
            logger.info(
                f"Found root {Path(chosen).name}: {_root_relative(chosen)}. This will be used for JS/TS path aliases."
            )
            if len(roots) > 1:
                logger.warning(
                    f"Multiple root {Path(chosen).name} files found. Using the first one: {_root_relative(chosen)}"
                )
        return chosen

    chosen_config = _find_root_config(ts_config_files)
    config_type = "tsconfig.json"
    if not chosen_config:
        chosen_config = _find_root_config(js_config_files)
        config_type = "jsconfig.json"

    if not chosen_config:
        if (ts_config_files or js_config_files) and logger:
            logger.warning(
                "JS/TS config files found but none at the repository root. Path aliases will not be processed from these non-root files."  # noqa
            )
        return None, {}

    try:
        if secure_file_ops:
            rel_path = secure_file_ops.get_relative_path(chosen_config)
            content = secure_file_ops.read_file(rel_path, encoding="utf-8-sig")
        else:
            with open(chosen_config, "r", encoding="utf-8-sig") as handle:
                content = handle.read()

        comment_regex = r"'(\\'|[^'])*?'|\"(\\\"|[^\"])*?\"|//[^\r\n]*|/\*(?:(?!\*/).)*\*/"
        content = re.sub(
            comment_regex,
            lambda match: match.group(0)
            if match.group(0).startswith('"') or match.group(0).startswith("'")
            else "",
            content,
            flags=re.S,
        )
        content = re.sub(r",\s*([\]}])", r"\1", content)

        data = json.loads(content)
        compiler_options = data.get("compilerOptions", {})

        base_url = compiler_options.get("baseUrl")
        if base_url is not None and not isinstance(base_url, str):
            base_url = None

        paths = compiler_options.get("paths")
        if paths is not None and not isinstance(paths, dict):
            paths = {}

        if base_url and logger:
            logger.info(f"Extracted baseUrl '{base_url}' from {config_type}")
        if paths and logger:
            logger.info(f"Extracted paths configuration from {config_type}: {paths}")

        return base_url, paths or {}

    except FileNotFoundError:
        if logger:
            logger.error(f"Selected JS/TS config file not found: {chosen_config}")
    except json.JSONDecodeError as exc:
        if logger:
            logger.error(
                f"Error decoding JSON from {config_type} ({_root_relative(chosen_config)}): {exc}. Path aliases may not be correctly parsed. Consider removing comments if present"  # noqa
            )
    except Exception as exc:
        if logger:
            logger.error(
                f"An unexpected error occurred while processing {config_type} ({_root_relative(chosen_config)}): {exc}"
            )

    return None, {}


def create_alias_resolver(repo_path, source_files, base_url, paths, logger):
    """
    Initialize UnifiedAliasResolver with parsed configuration

    Args:
        repo_path (str): Absolute repository path
        source_files (dict): Map of repo‑relative paths to file metadata
        base_url (str|None): baseUrl from ts/js config
        paths (dict): paths configuration from ts/js config
        logger (Logger|None): Optional logger for debug output

    Returns:
        UnifiedAliasResolver: Resolver instance configured for the repository
    """
    config = AliasConfiguration()
    if paths:
        config.ts_js_paths = paths
    if base_url:
        config.base_url = base_url
    resolver = UnifiedAliasResolver(
        config=config,
        repo_path=repo_path,
        source_files=source_files,
        logger=logger,
    )
    return resolver
