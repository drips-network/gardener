"""
Solidity-specific metadata helpers for RepositoryAnalyzer

Parses Solidity remappings, optionally extracts Hardhat remappings via a Node helper,
and associates Solidity packages with git submodules for better URL attribution
"""

import json
import os
import shutil
from pathlib import Path

from gardener.common.input_validation import InputValidator, ValidationError
from gardener.common.subprocess import SecureSubprocess, SubprocessSecurityError
from gardener.treewalk.solidity import SolidityLanguageHandler


def canonicalize_solidity_package_name(name):
    """
    Normalize common Solidity package aliases to canonical names

    Args:
        name (str): Original package-like identifier (e.g., '@openzeppelin')

    Returns:
        str: Canonicalized package name when recognized, otherwise original value
    """
    if not isinstance(name, str):
        return name
    if name in {"@openzeppelin", "@openzeppelin/"}:
        return "@openzeppelin/contracts"
    if name == "openzeppelin-contracts":
        return "@openzeppelin/contracts"
    return name


def parse_remappings_txt(secure_file_ops, logger):
    """
    Parse remappings.txt into {prefix: absolute_path}

    Args:
        secure_file_ops (SecureFileOps|None): Secure file operations or None
        logger (Logger|None): Optional logger for notes and warnings

    Returns:
        dict: Map of remapping prefixes to absolute paths
    """
    remappings = {}
    if not secure_file_ops:
        return remappings

    rel_path = "remappings.txt"
    if not secure_file_ops.exists(rel_path):
        return remappings

    if logger:
        logger.info("Found remappings.txt, parsing...")

    try:
        content = secure_file_ops.read_file(rel_path)
        for index, line in enumerate(content.splitlines()):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("=", 1)
            if len(parts) != 2:
                if logger:
                    logger.warning(f"Skipping malformed line {index + 1} in remappings.txt: '{line}'")
                continue
            prefix = parts[0].strip()
            path = parts[1].strip()
            normalized = str(Path(path).resolve())
            remappings[prefix] = normalized
            if logger:
                logger.debug(f"  Parsed remapping: '{prefix}' -> '{normalized}'")
    except Exception as exc:
        if logger:
            logger.error(f"Error reading or parsing remappings.txt: {exc}")
    return remappings


def get_hardhat_remappings(repo_path, logger):
    """
    Invoke Node helper to extract Hardhat remappings

    Args:
        repo_path (str): Absolute repository path
        logger (Logger|None): Optional logger for progress and errors

    Returns:
        dict: Map of remapping prefixes to absolute paths derived from Hardhat
    """
    script_dir_parts = ["external_helpers", "hardhat_config_parser"]
    script_name = "parse_remappings.cjs"
    script_path = Path(__file__).resolve().parent.parent.joinpath(*script_dir_parts, script_name)
    script_dir = script_path.parent
    local_node_modules = script_dir / "node_modules"

    if not script_path.exists():
        return {}

    node_executable = shutil.which("node")
    if not node_executable:
        if logger:
            logger.warning("Node.js executable not found in PATH. Cannot get Hardhat remappings.")
        return {}

    try:
        validated_repo_path = InputValidator.validate_file_path(repo_path, must_exist=True)
    except ValidationError as exc:
        if logger:
            logger.error(f"Invalid repository path: {exc}")
        return {}

    command = [node_executable, str(script_path), str(validated_repo_path)]
    env = {}
    if local_node_modules.is_dir():
        env["NODE_PATH"] = str(local_node_modules)
        if logger:
            logger.debug(
                f"Hardhat script: Using local node_modules. Setting NODE_PATH to: {local_node_modules}"
            )
    elif logger:
        logger.warning(
            f"Local node_modules for Hardhat helper not found at {local_node_modules}. "
            f"Ensure 'npm install' was run in '{script_dir}'. Script might rely on global or target project's ts-node."
        )

    try:
        runner = SecureSubprocess(allowed_root=validated_repo_path, timeout=60)
        result = runner.run(command, cwd=validated_repo_path, env=env, capture_output=True, check=False)

        if result.returncode != 0:
            parts = [f"Error getting Hardhat remappings. Script exited with code {result.returncode}."]
            if result.stdout:
                parts.append(f"Script stdout:\n{result.stdout.strip()}")
            if result.stderr:
                parts.append(f"Script stderr:\n{result.stderr.strip()}")
            if logger:
                logger.error("\n".join(parts))
            return {}

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            if logger:
                logger.error(
                    f"Failed to parse JSON output from Hardhat remapping script: {exc}\n"
                    f"Raw script output was:\n{result.stdout}"
                )
            return {}

    except (SubprocessSecurityError, ValidationError) as exc:
        if logger:
            logger.error(f"Security error executing Hardhat script: {exc}")
        return {}
    except FileNotFoundError:
        if logger:
            logger.error(
                f"Node.js executable '{node_executable}' not found. Ensure Node.js is installed and in PATH."
            )
        return {}
    except Exception as exc:
        if logger:
            logger.error(f"An unexpected error occurred while running Hardhat remapping script: {exc}")
        return {}


def associate_submodules_with_solidity_packages(external_packages, remappings,
                                                hardhat_remappings, submodule_data, logger):
    """
    Associate Solidity packages discovered in remappings with .gitmodules metadata

    Args:
        external_packages (dict): Package metadata map, mutated in place when URLs found
        remappings (dict): remappings.txt map of prefix to absolute path
        hardhat_remappings (dict): Hardhat derived remappings of prefix to absolute path
        submodule_data (dict): Map of normalized submodule paths to URLs
        logger (Logger|None): Optional logger for info and warnings

    Returns:
        dict: Updated external package metadata with gitmodules linkage where available
    """
    if not remappings and not hardhat_remappings:
        return external_packages

    handler = SolidityLanguageHandler()

    combined = {}
    combined.update(remappings or {})
    combined.update(hardhat_remappings or {})

    for prefix, path in combined.items():
        path_str = str(path)
        is_library = False
        if prefix.startswith("@"):
            is_library = True
        if "node_modules/" in path_str or path_str.startswith("lib/"):
            is_library = True
        if prefix in ["forge-std/", "openzeppelin-contracts/", "solmate/", "hardhat/", "@openzeppelin/contracts/"]:
            is_library = True
        if not is_library:
            continue

        package_name = handler.normalize_package_name(prefix)
        package_name = canonicalize_solidity_package_name(package_name) if package_name else package_name
        if not package_name:
            if logger:
                logger.warning(f"Could not normalize potential package prefix '{prefix}' from remapping")
            continue
        package_meta = external_packages.get(package_name)
        if not package_meta or package_meta.get("ecosystem") != "solidity":
            continue

        assigned_url = None
        assigned_path = None
        normalized = str(Path(path_str)).replace(os.sep, "/").rstrip("/")

        parts = normalized.split("lib/")
        if len(parts) > 1:
            after_lib = parts[-1]
            fast_seg = after_lib.split("/", 1)[0]
        else:
            fast_seg = None

        if fast_seg:
            candidate = f"lib/{fast_seg}"
            package_cmp = package_name.replace("-", "").replace("_", "").lower()
            seg_cmp = fast_seg.replace("-", "").replace("_", "").lower()
            aligned = (
                package_cmp == seg_cmp
                or seg_cmp.startswith(package_cmp)
                or package_cmp.startswith(seg_cmp)
                or package_cmp in seg_cmp
                or seg_cmp in package_cmp
            )
            if aligned and candidate in submodule_data:
                assigned_url = submodule_data[candidate]
                assigned_path = candidate

        if not assigned_url:
            best_len = -1
            for sm_path, sm_url in submodule_data.items():
                normalized_sm = sm_path
                if normalized.startswith(normalized_sm + "/") or normalized == normalized_sm:
                    base = Path(normalized_sm).name
                    package_cmp = package_name.replace("-", "").replace("_", "").lower()
                    base_cmp = base.replace("-", "").replace("_", "").lower()
                    aligned = (
                        package_cmp == base_cmp
                        or base_cmp.startswith(package_cmp)
                        or package_cmp.startswith(base_cmp)
                        or package_cmp in base_cmp
                        or base_cmp in package_cmp
                    )
                    if aligned and len(normalized_sm) > best_len:
                        best_len = len(normalized_sm)
                        assigned_url = sm_url
                        assigned_path = normalized_sm

        if assigned_url:
            package_meta["gitmodules_url"] = assigned_url
            if assigned_path:
                package_meta["gitmodules_source_path"] = assigned_path
            if logger:
                logger.info(
                    f"Associated Solidity package '{package_name}' with submodule "
                    f"'{assigned_path if assigned_path else 'derived'}' -> '{assigned_url}'"
                )

    return external_packages
