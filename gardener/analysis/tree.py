"""
Repository scanning and import extraction
"""

import configparser  # Added for .gitmodules parsing
import json
import logging
import os
import re
import shutil  # Added for checking Node.js existence
import signal
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

# Local constants for JS/TS resolution (no behavior change)
JS_TS_SOURCE_EXTS = [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"]
JSONLIKE_EXTS = [".json"]

import pathspec
from grep_ast import filename_to_lang
from grep_ast.tsl import get_parser

from gardener.common.alias_config import AliasConfiguration, UnifiedAliasResolver
from gardener.common.defaults import ResourceLimits
from gardener.common.input_validation import InputValidator, ValidationError
from gardener.common.secure_file_ops import FileOperationError, SecureFileOps
from gardener.common.subprocess import SecureSubprocess, SubprocessSecurityError
from gardener.package_metadata.name_resolvers.go import GoResolver
from gardener.package_metadata.name_resolvers.json_manifest import JsonManifestResolver
from gardener.package_metadata.name_resolvers.python import PythonResolver
from gardener.package_metadata.name_resolvers.rust import RustResolver
from gardener.treewalk.solidity import SolidityLanguageHandler


class TimeoutError(Exception):
    """
    Raised when a parsing operation times out
    """

    pass


@contextmanager
def timeout(seconds):
    """
    Context manager for timeout protection

    Args:
        seconds (int): Number of seconds before timeout

    Raises:
        TimeoutError: If operation times out
    """
    # Check if SIGALRM is available (Unix-like systems)
    if hasattr(signal, "SIGALRM"):

        def timeout_handler(signum, frame):
            raise TimeoutError(f"Operation timed out after {seconds} seconds")

        # Set up the timeout handler
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(seconds)

        try:
            yield
        finally:
            # Cancel the alarm and restore the old handler
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    else:
        # On Windows or other systems without SIGALRM, no timeout protection
        # Log a warning if logger is available
        logging.debug("Timeout protection not available on this platform")
        yield


class RepositoryAnalyzer:
    """
    Handles repository scanning and import extraction functions
    """

    def __init__(self, repo_path, focus_languages=None, logger=None):
        """
        Args:
            repo_path (str): Path to the repository to analyze
            focus_languages (list): Optional list of languages to focus analysis on
            logger (Logger): Optional logger instance
        """
        self.repo_path = repo_path
        self.logger = logger
        self.focus_languages = focus_languages

        try:
            self.secure_file_ops = SecureFileOps(repo_path, logger)
        except FileOperationError as e:
            if logger:
                logger.error(f"Failed to initialize secure file operations: {e}")
            self.secure_file_ops = None

        # Load gitignore after secure file ops is initialized
        self.gitignore_spec = self._load_gitignore()

        # Repository data
        self.manifest_files = []  # All found manifests
        self.root_manifest_files = []  # Manifests found at the repo root
        self.source_files = {}
        self.external_packages = {}
        self.file_imports = defaultdict(list)  # Maps file -> list of external package names
        self.file_package_components = defaultdict(list)  # Maps file -> list of (pkg, component) tuples
        self.local_imports_map = defaultdict(list)  # Maps file -> list of resolved local file paths
        self.root_package_names = set()  # Store names found in root manifests
        self.go_module_path = None  # Store the main module path from go.mod
        self.hardhat_remappings = {}  # Store Hardhat remappings if found
        self.remappings = {}  # Store remappings from remappings.txt
        self.solidity_src_path = None  # Store the src path from foundry.toml

        # JS/TS config related
        self.js_config_files = []  # Paths to all found jsconfig.json files
        self.ts_config_files = []  # Paths to all found tsconfig.json files
        self.js_ts_base_url = None
        self.js_ts_path_aliases = {}
        self.alias_resolver = None  # UnifiedAliasResolver instance
        self.submodule_data = {}  # For .gitmodules data

        # Manifest hierarchy tracking
        # Metadata includes:
        # - 'type': manifest type (package.json, requirements.txt, etc.)
        # - 'language': associated language (javascript, python, etc.)
        # - 'depth': directory depth from repo root (0 = root, 1 = first level, etc.)
        # - 'parent': path to parent manifest (if any)
        # - 'children': list of child manifest paths
        # - 'directory': directory containing the manifest

        # Language handlers
        self.language_handlers = {}

    def _load_gitignore(self):
        """Load .gitignore patterns if available"""
        gitignore_path = ".gitignore"

        # Use secure file operations if available
        if self.secure_file_ops:
            if self.secure_file_ops.exists(gitignore_path):
                try:
                    gitignore_content = self.secure_file_ops.read_file(gitignore_path)
                    return pathspec.PathSpec.from_lines(
                        pathspec.patterns.GitWildMatchPattern, gitignore_content.splitlines()
                    )
                except (FileOperationError, Exception) as e:
                    if self.logger:
                        self.logger.warning(f"Could not load or parse .gitignore: {e}")
        return None

    def is_ignored(self, path):
        """
        Check if a path should be ignored according to .gitignore

        Args:
            path (str): File path to check

        Returns:
            Boolean indicating if path should be ignored
        """
        if not self.gitignore_spec:
            return False

        try:
            rel_path = (
                self.secure_file_ops.get_relative_path(path)
                if self.secure_file_ops
                else os.path.relpath(path, self.repo_path)
            )
            # Normalize path separators for pathspec
            rel_path = str(Path(rel_path))
            return self.gitignore_spec.match_file(rel_path)
        except ValueError:
            # Handle cases where path is outside the repo_path (e.g., different drive on Windows)
            return False  # Assume not ignored if we can't get a relative path

    def _is_ignored_safe(self, path):
        """Wrapper around is_ignored for internal use; mirrors error handling semantics"""
        return self.is_ignored(path)

    def register_language_handler(self, language, handler):
        """
        Register a language handler

        Args:
            language (str): Language identifier (e.g., 'python', 'javascript')
            handler (object): Language handler instance
        """
        self.language_handlers[language] = handler
        if self.logger:
            self.logger.debug(f"Registered language handler: {language}")

    def scan_repo(self):
        """
        Scan repo to identify source files and manifest files

        Returns:
            Tuple of (source_files, manifest_files)
        """
        self._parse_gitmodules()  # Parse .gitmodules early

        all_manifest_files = set()
        all_extensions = set()
        active_languages = self.focus_languages or list(self.language_handlers.keys())

        # Collect manifest files and extensions from active handlers
        for lang in active_languages:
            if lang in self.language_handlers:
                handler = self.language_handlers[lang]
                all_manifest_files.update(handler.get_manifest_files())
                all_extensions.update(handler.get_file_extensions())

        # Use secure file operations if available
        if self.secure_file_ops:
            self._scan_directory_secure(all_extensions, all_manifest_files, active_languages)
            return self.source_files, self.manifest_files

        # Fallback to standard os.walk
        self._scan_directory_standard(all_extensions, all_manifest_files, active_languages)

        if self.logger:
            self.logger.info(
                f"... Found {len(self.source_files)} source files, {len(self.manifest_files)} total manifest files ({len(self.root_manifest_files)} at root)"
            )

        self.hardhat_remappings = self._get_hardhat_remappings()
        if self.hardhat_remappings and self.logger:
            self.logger.debug(f"Retrieved Hardhat remappings: {self.hardhat_remappings}")

        return self.source_files, self.manifest_files

    # --- Scanning helpers (fallback only) ---
    def _scan_directory_standard(self, all_extensions, all_manifest_files, active_languages):
        """Fallback scan using os.walk, preserving existing ignore and detection logic"""
        for root, dirs, files in os.walk(self.repo_path, topdown=True):
            # Filter and sort directories deterministically
            filtered_dirs = [
                d for d in dirs if not d.startswith(".") and not self._is_ignored_safe(str(Path(root) / d))
            ]
            # Optionally skip symlinks
            if not ResourceLimits.FOLLOW_SYMLINKS:
                filtered_dirs = [d for d in filtered_dirs if not Path(Path(root) / d).is_symlink()]
            dirs[:] = sorted(filtered_dirs)

            # Sort files deterministically
            files = sorted(files)
            for file in files:
                file_path = str(Path(root) / file)
                if not ResourceLimits.FOLLOW_SYMLINKS and Path(file_path).is_symlink():
                    continue
                if self._is_ignored_safe(file_path):
                    continue
                try:
                    rel_path = str(Path(file_path).relative_to(self.repo_path))
                except ValueError:
                    rel_path = os.path.relpath(file_path, self.repo_path)
                rel_path = str(Path(rel_path))
                basename = Path(file_path).name
                _, ext = os.path.splitext(basename)
                if basename in all_manifest_files:
                    self.manifest_files.append(file_path)
                    is_root_file = str(Path(rel_path).parent) == "."
                    if is_root_file:
                        self.root_manifest_files.append(file_path)
                if basename == "jsconfig.json":
                    self.js_config_files.append(file_path)
                elif basename == "tsconfig.json":
                    self.ts_config_files.append(file_path)
                if ext in all_extensions:
                    language = filename_to_lang(file_path)
                    if language is None:
                        ext_to_lang = {".cjs": "javascript", ".mjs": "javascript", ".svelte": "javascript"}
                        language = ext_to_lang.get(ext)
                    if language and language in active_languages:
                        self.source_files[rel_path] = {"absolute_path": file_path, "language": language}
        # Parse foundry.toml for src path if it exists (fallback branch semantics)
        self._parse_foundry_toml_for_src_path()

    def _parse_foundry_toml_for_src_path(self):
        """Parse foundry.toml in fallback path, matching existing behavior (secure_file_ops only)"""
        foundry_toml_path = "foundry.toml"
        if self.secure_file_ops:
            if self.secure_file_ops.exists(foundry_toml_path):
                try:
                    content = self.secure_file_ops.read_file(foundry_toml_path)
                    match = re.search(
                        r"\[profile\.default\][^\[]*\s*src\s*=\s*[\'\"]([^\'\"]+)[\'\"]", content, re.IGNORECASE
                    )
                    if not match:
                        match = re.search(
                            r"\[default\][^\[]*\s*src\s*=\s*[\'\"]([^\'\"]+)[\'\"]", content, re.IGNORECASE
                        )
                    if match:
                        self.solidity_src_path = match.group(1).strip()
                        if self.logger:
                            self.logger.debug(f"Found Solidity src path in foundry.toml: '{self.solidity_src_path}'")
                    else:
                        if self.logger:
                            self.logger.debug(
                                "No 'src' path found under [profile.default] or [default] in foundry.toml"
                            )
                except (FileOperationError, Exception) as e:
                    if self.logger:
                        self.logger.error(f"Error reading or parsing foundry.toml for src path: {e}")

    def _scan_directory_secure(self, all_extensions, all_manifest_files, active_languages):
        """
        Scan directory using secure file operations

        Args:
            all_extensions (set): Set of file extensions to scan for
            all_manifest_files (set): Set of manifest filenames to look for
            active_languages (list): List of languages to include in the scan
        """

        # Track visited directories to prevent infinite loops with symlinks
        visited_dirs = set()

        def _scan_dir_recursive(dir_path):
            """Recursively scan directory"""
            try:
                # Resolve the directory path to handle symlinks
                try:
                    resolved_path = str(Path(str(dir_path)).resolve())
                except (OSError, RuntimeError) as e:
                    # Skip if we can't resolve the path (broken symlink, etc.)
                    if self.logger:
                        self.logger.debug(f"Skipping directory due to resolution error: {e}")
                    return

                if resolved_path in visited_dirs:
                    if self.logger:
                        self.logger.debug(f"Already visited directory: {resolved_path}")
                    return

                visited_dirs.add(resolved_path)

                entries = self.secure_file_ops.list_dir(dir_path)
                # Sort entries by name for deterministic traversal
                try:
                    entries = sorted(entries, key=lambda p: p.name)
                except Exception:
                    entries = list(entries)
                for entry in entries:
                    # Skip hidden files/dirs and check gitignore
                    if entry.name.startswith("."):
                        continue

                    full_path = str(entry)

                    # Optionally skip symlinks
                    try:
                        if not ResourceLimits.FOLLOW_SYMLINKS and Path(full_path).is_symlink():
                            continue
                    except Exception:
                        pass

                    if self._is_ignored_safe(full_path):
                        continue

                    if self.secure_file_ops.is_dir(entry):
                        _scan_dir_recursive(entry)
                    elif self.secure_file_ops.is_file(entry):
                        rel_path = self.secure_file_ops.get_relative_path(full_path)
                        basename = entry.name
                        _, ext = os.path.splitext(basename)

                        if basename in all_manifest_files:
                            self.manifest_files.append(full_path)
                            is_root_file = str(Path(rel_path).parent) == "."
                            if is_root_file:
                                self.root_manifest_files.append(full_path)

                        if basename == "jsconfig.json":
                            self.js_config_files.append(full_path)
                        elif basename == "tsconfig.json":
                            self.ts_config_files.append(full_path)

                        if ext in all_extensions:
                            language = filename_to_lang(full_path)  # Use grep-ast's detection

                            if language is None:
                                # Map extensions to languages for cases grep-ast doesn't handle
                                ext_to_lang = {
                                    ".cjs": "javascript",
                                    ".mjs": "javascript",
                                    ".svelte": "javascript",  # Treat Svelte files as JavaScript
                                }
                                language = ext_to_lang.get(ext)

                            if language and language in active_languages:
                                self.source_files[rel_path] = {"absolute_path": full_path, "language": language}
            except (FileOperationError, Exception) as e:
                if self.logger:
                    self.logger.warning(f"Error scanning directory {dir_path}: {e}")

        _scan_dir_recursive(self.repo_path)

        foundry_toml_path = "foundry.toml"
        if self.secure_file_ops.exists(foundry_toml_path):
            if self.logger:
                self.logger.info("Found foundry.toml, checking for Solidity src path...")
            try:
                content = self.secure_file_ops.read_file(foundry_toml_path)
                # Simple regex to find src = 'path' under [profile.default] or [default]
                match = re.search(
                    r"\[profile\.default\][^\[]*\s*src\s*=\s*[\'\"]([^\'\"]+)[\'\"]", content, re.IGNORECASE
                )
                if not match:
                    match = re.search(r"\[default\][^\[]*\s*src\s*=\s*[\'\"]([^\'\"]+)[\'\"]", content, re.IGNORECASE)

                if match:
                    self.solidity_src_path = match.group(1).strip()
                    if self.logger:
                        self.logger.debug(f"Found Solidity src path in foundry.toml: '{self.solidity_src_path}'")
                else:
                    if self.logger:
                        self.logger.debug("No 'src' path found under [profile.default] or [default] in foundry.toml")
            except (FileOperationError, Exception) as e:
                if self.logger:
                    self.logger.error(f"Error reading or parsing foundry.toml for src path: {e}")

        if self.logger:
            self.logger.info(
                f"... Found {len(self.source_files)} source files, "
                f"{len(self.manifest_files)} total manifest files "
                f"({len(self.root_manifest_files)} at root)"
            )

        self.hardhat_remappings = self._get_hardhat_remappings()
        if self.hardhat_remappings and self.logger:
            self.logger.debug(f"Retrieved Hardhat remappings: {self.hardhat_remappings}")

    def process_manifest_files(self):
        """
        Process manifest files to extract dependencies

        Returns:
            Dictionary of external packages
        """
        # Parse remappings.txt if it exists at the root
        self._parse_remappings_txt_into_self()

        sol_handler = SolidityLanguageHandler()  # Instantiate for normalization
        for remappings_dict, source_name in [
            (self.remappings, "remappings.txt"),
            (self.hardhat_remappings, "hardhat config"),
        ]:
            self._solidity_candidates_from_remappings(remappings_dict, source_name)

        # Process all manifest files
        manifests_to_process = list(self.manifest_files)
        if self.logger:
            self.logger.info(f"\nProcessing {len(manifests_to_process)} manifest files")

        # Root manifest name + workspaces detection
        for manifest_file in self.root_manifest_files:
            basename = Path(manifest_file).name
            self._collect_root_package_names_and_workspaces(manifest_file, basename)

        # Per-manifest processing via handlers with deduplication
        self._process_all_manifests_via_handlers()

        if self.logger:
            self.logger.info(f"... Found {len(self.external_packages)} unique external packages")

        # Attach import names to external packages
        self._attach_import_names()

        # Process JS/TS configs (baseUrl/paths) and init resolver
        self._process_js_ts_configs()

        # Associate submodule URLs for Solidity packages
        self._associate_submodules_with_solidity_packages(sol_handler)

        # Resolve version conflicts across packages
        self._resolve_all_version_conflicts_in_self()

        # Ensure stable order of manifest tracking lists for deterministic behavior
        try:
            self.manifest_files.sort()
            self.root_manifest_files.sort()
        except Exception:
            pass

        return self.external_packages

    # --- Manifest processing helpers ---
    def _parse_remappings_txt_into_self(self):
        """Parse remappings.txt at repo root and populate self.remappings with normalized paths"""
        remappings_path = "remappings.txt"
        if self.secure_file_ops and self.secure_file_ops.exists(remappings_path):
            if self.logger:
                self.logger.info("Found remappings.txt, parsing...")
            try:
                content = self.secure_file_ops.read_file(remappings_path)
                for line_num, line in enumerate(content.splitlines()):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        prefix = parts[0].strip()
                        path = parts[1].strip()
                        normalized_path = str(Path(path).resolve())
                        self.remappings[prefix] = normalized_path
                        if self.logger:
                            self.logger.debug(f"  Parsed remapping: '{prefix}' -> '{normalized_path}'")
                    else:
                        if self.logger:
                            self.logger.warning(f"Skipping malformed line {line_num + 1} in remappings.txt: '{line}'")
            except (FileOperationError, Exception) as e:
                if self.logger:
                    self.logger.error(f"Error reading or parsing remappings.txt: {e}")

    def _solidity_candidates_from_remappings(self, remappings_dict, source_name):
        """Identify potential external Solidity packages from remappings"""
        if not remappings_dict:
            return
        sol_handler_local = SolidityLanguageHandler()

        def _canonicalize_package_name(name):
            """
            Map alias-like Solidity package names to canonical distributions

            - '@openzeppelin' and '@openzeppelin/' -> '@openzeppelin/contracts'
            - 'openzeppelin-contracts' -> '@openzeppelin/contracts'

            Args:
                name (str): Candidate package name

            Returns:
                str: Canonical package name
            """
            if not isinstance(name, str):
                return name
            if name in {"@openzeppelin", "@openzeppelin/"}:
                return "@openzeppelin/contracts"
            if name == "openzeppelin-contracts":
                return "@openzeppelin/contracts"
            return name

        for prefix, path in remappings_dict.items():
            path_str = str(path)
            is_library = False
            if prefix.startswith("@"):
                is_library = True
            if "node_modules/" in path_str:
                is_library = True
            if path_str.startswith("lib/"):
                is_library = True
            if prefix in ["forge-std/", "openzeppelin-contracts/", "solmate/", "hardhat/", "@openzeppelin/contracts/"]:
                is_library = True
            if is_library:
                package_name = sol_handler_local.normalize_package_name(prefix)
                package_name = _canonicalize_package_name(package_name) if package_name else package_name
                if package_name:
                    if package_name not in self.external_packages:
                        self.external_packages[package_name] = {
                            "ecosystem": "solidity",
                            "source": f"{source_name}: {prefix}={path}",
                        }
                        if self.logger:
                            self.logger.info(
                                f"  Identified potential external Solidity package '{package_name}' from {source_name} remapping: '{prefix}' -> '{path}'"  # noqa
                            )
                    else:
                        if source_name not in self.external_packages[package_name]["source"]:
                            if self.logger:
                                self.logger.debug(
                                    f"  Remapped package '{package_name}' (from {source_name}: '{prefix}' -> '{path}') already identified from {self.external_packages[package_name]['source']}"  # noqa
                                )
                else:
                    if self.logger:
                        self.logger.warning(
                            f"Could not normalize potential package prefix '{prefix}' from {source_name} remapping"
                        )

    def _collect_root_package_names_and_workspaces(self, manifest_file, basename):
        """Collect root package names and detect workspace:* dependencies from root package.json"""
        root_name = self._get_package_name_from_manifest(manifest_file, basename)
        if root_name:
            self.root_package_names.add(root_name)
            if self.logger:
                self.logger.debug(f"Identified root package name '{root_name}' from {basename}")
        if basename == "package.json":
            try:
                if self.secure_file_ops:
                    rel_path = self.secure_file_ops.get_relative_path(manifest_file)
                    data = self.secure_file_ops.read_json(rel_path)
                else:
                    with open(manifest_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                dep_sections_to_check = [
                    data.get("dependencies", {}),
                    data.get("devDependencies", {}),
                    data.get("peerDependencies", {}),
                    data.get("optionalDependencies", {}),
                ]
                if "pnpm" in data and isinstance(data["pnpm"], dict):
                    if "overrides" in data["pnpm"] and isinstance(data["pnpm"]["overrides"], dict):
                        dep_sections_to_check.append(data["pnpm"]["overrides"])
                    if "patchedDependencies" in data["pnpm"] and isinstance(data["pnpm"]["patchedDependencies"], dict):
                        dep_sections_to_check.append({k: "patched" for k in data["pnpm"]["patchedDependencies"]})
                for dep_section in dep_sections_to_check:
                    if isinstance(dep_section, dict):
                        for name, version in dep_section.items():
                            if isinstance(version, str) and "workspace:" in version:
                                if name not in self.root_package_names:
                                    self.root_package_names.add(name)
            except Exception as e:
                if self.logger:
                    self.logger.warning(f"Error checking root package.json for workspace:* dependencies: {e}")

    def _process_all_manifests_via_handlers(self):
        """Process all manifests using language handlers with deduplication"""
        for manifest_file in list(self.manifest_files):
            basename = Path(manifest_file).name
            for handler_lang, handler in self.language_handlers.items():
                if basename in handler.get_manifest_files():
                    try:
                        temp_packages = {}
                        handler.process_manifest(manifest_file, temp_packages, self.secure_file_ops)
                        for package_name, package_info in temp_packages.items():
                            if package_name in self.external_packages:
                                self.external_packages[package_name] = self._deduplicate_package(
                                    package_name, self.external_packages[package_name], package_info, manifest_file
                                )
                            else:
                                package_info["found_in_manifests"] = [manifest_file]
                                self.external_packages[package_name] = package_info
                    except Exception as e:
                        if self.logger:
                            self.logger.error(
                                f"Error processing manifest {manifest_file} with {handler_lang} handler", e
                            )

    def _associate_submodules_with_solidity_packages(self, sol_handler):
        """Associate submodule URLs with identified Solidity packages based on remappings and .gitmodules"""
        all_defined_remappings = {}
        all_defined_remappings.update(self.remappings)
        all_defined_remappings.update(self.hardhat_remappings)
        for remap_prefix, remap_path_str in all_defined_remappings.items():
            potential_package_name = sol_handler.normalize_package_name(remap_prefix)
            if (
                potential_package_name
                and potential_package_name in self.external_packages
                and self.external_packages[potential_package_name].get("ecosystem") == "solidity"
            ):
                assigned_submodule_url = None
                assigned_submodule_path = None
                fast_path_seg = None
                normalized_remap_path_for_split = str(Path(remap_path_str)).replace(os.sep, "/")
                parts = normalized_remap_path_for_split.rstrip("/").split("lib/")
                if len(parts) > 1:
                    sub_path_after_lib = parts[-1]
                    fast_path_seg = sub_path_after_lib.split("/", 1)[0]
                if fast_path_seg:
                    candidate_submodule_path_norm = f"lib/{fast_path_seg}"
                    comp_pkg_name = potential_package_name.replace("-", "").replace("_", "").lower()
                    comp_seg_name = fast_path_seg.replace("-", "").replace("_", "").lower()
                    names_considered_aligned = (
                        comp_pkg_name == comp_seg_name
                        or comp_seg_name.startswith(comp_pkg_name)
                        or comp_pkg_name.startswith(comp_seg_name)
                        or comp_pkg_name in comp_seg_name
                        or comp_seg_name in comp_pkg_name
                    )
                    if names_considered_aligned and candidate_submodule_path_norm in self.submodule_data:
                        assigned_submodule_url = self.submodule_data[candidate_submodule_path_norm]
                        assigned_submodule_path = candidate_submodule_path_norm
                if not assigned_submodule_url:
                    normalized_original_remapped_path = str(Path(remap_path_str).resolve()).replace(os.sep, "/")
                    best_match_len = -1
                    for sm_path_from_data, sm_url_from_data in self.submodule_data.items():
                        if (
                            normalized_original_remapped_path.startswith(sm_path_from_data + "/")
                            or normalized_original_remapped_path == sm_path_from_data
                        ):
                            submodule_base_name = Path(sm_path_from_data).name
                            comp_pkg_name = potential_package_name.replace("-", "").replace("_", "").lower()
                            comp_sm_basename = submodule_base_name.replace("-", "").replace("_", "").lower()
                            fallback_names_aligned = (
                                comp_pkg_name == comp_sm_basename
                                or comp_sm_basename.startswith(comp_pkg_name)
                                or comp_pkg_name.startswith(comp_sm_basename)
                                or comp_pkg_name in comp_sm_basename
                                or comp_sm_basename in comp_pkg_name
                            )
                            if fallback_names_aligned:
                                if len(sm_path_from_data) > best_match_len:
                                    best_match_len = len(sm_path_from_data)
                                    assigned_submodule_url = sm_url_from_data
                                    assigned_submodule_path = sm_path_from_data
                if assigned_submodule_url:
                    self.external_packages[potential_package_name]["gitmodules_url"] = assigned_submodule_url
                    if assigned_submodule_path:
                        self.external_packages[potential_package_name][
                            "gitmodules_source_path"
                        ] = assigned_submodule_path  # noqa
                    if self.logger:
                        self.logger.info(
                            f"Associated Solidity package '{potential_package_name}' with submodule "
                            f"'{assigned_submodule_path if assigned_submodule_path else 'derived'}' -> '{assigned_submodule_url}'"  # noqa
                        )

    def _resolve_all_version_conflicts_in_self(self):
        """Resolve version conflicts across self.external_packages and log one warning per package"""
        for package_name, package_info in self.external_packages.items():
            if "version_conflicts" in package_info:
                all_versions = []
                for conflict in package_info["version_conflicts"]:
                    version = conflict.get("version")
                    if version and version not in all_versions:
                        all_versions.append(version)

                # Only attempt resolution when we truly have multiple unique versions
                if len(all_versions) > 1:
                    resolved_version = all_versions[0]
                    for version in all_versions[1:]:
                        resolved_version = self._resolve_version_conflict(resolved_version, version)

                    # Update the resolved version
                    package_info["version"] = resolved_version

                    # Filter out the resolved version from the conflicts list so it only contains actual conflicts
                    package_info["version_conflicts"] = [
                        c for c in package_info["version_conflicts"] if c.get("version") != resolved_version
                    ]

                    if self.logger:
                        conflict_summary = ", ".join(
                            [f"{c['version']} (from {c['manifest']})" for c in package_info["version_conflicts"]]
                        )
                        self.logger.warning(
                            f"Version conflict for package '{package_name}': {conflict_summary}. Resolved to: {resolved_version}"  # noqa
                        )

    def _get_package_name_from_manifest(self, m_file, b_name):
        """
        Extract a package/module name from a manifest. Behavior matches original nested function
        """
        try:
            if self.secure_file_ops:
                rel_path = self.secure_file_ops.get_relative_path(m_file)
                if b_name == "package.json":
                    data = self.secure_file_ops.read_json(rel_path)
                    return data.get("name")
                elif b_name in ["pyproject.toml", "Cargo.toml", "go.mod"]:
                    content = self.secure_file_ops.read_file(rel_path)
                    if b_name == "pyproject.toml":
                        match = re.search(
                            r"\[project\]\s*.*?name\s*=\s*[\'\"]([^\'\"]+)[\'\"]", content, re.DOTALL | re.IGNORECASE
                        )
                        if match:
                            return match.group(1)
                    elif b_name == "Cargo.toml":
                        match = re.search(
                            r"\[package\]\s*.*?name\s*=\s*[\'\"]([^\'\"]+)[\'\"]", content, re.DOTALL | re.IGNORECASE
                        )
                        if match:
                            return match.group(1)
                    elif b_name == "go.mod":
                        match = re.search(r"^module\s+([^\s]+)", content, re.MULTILINE)
                        if match:
                            module_path = match.group(1)
                            if self.go_module_path is None:
                                self.go_module_path = module_path
                                if self.logger:
                                    self.logger.info(f"Identified Go module path: {self.go_module_path}")
                            return module_path
            else:
                if b_name == "package.json":
                    if self.secure_file_ops and self.secure_file_ops.exists(m_file):
                        try:
                            data = self.secure_file_ops.read_json(m_file)
                            return data.get("name")
                        except (FileOperationError, Exception):
                            pass
                    with open(m_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return data.get("name")
                elif b_name == "pyproject.toml":
                    if self.secure_file_ops and self.secure_file_ops.exists(m_file):
                        try:
                            content = self.secure_file_ops.read_file(m_file)
                        except (FileOperationError, Exception):
                            with open(m_file, "r", encoding="utf-8") as f:
                                content = f.read()
                    else:
                        with open(m_file, "r", encoding="utf-8") as f:
                            content = f.read()
                    match = re.search(
                        r"\[project\]\s*.*?name\s*=\s*[\'\"]([^\'\"]+)[\'\"]", content, re.DOTALL | re.IGNORECASE
                    )
                    if match:
                        return match.group(1)
                elif b_name == "Cargo.toml":
                    if self.secure_file_ops and self.secure_file_ops.exists(m_file):
                        try:
                            content = self.secure_file_ops.read_file(m_file)
                        except (FileOperationError, Exception):
                            with open(m_file, "r", encoding="utf-8") as f:
                                content = f.read()
                    else:
                        with open(m_file, "r", encoding="utf-8") as f:
                            content = f.read()
                    match = re.search(
                        r"\[package\]\s*.*?name\s*=\s*[\'\"]([^\'\"]+)[\'\"]", content, re.DOTALL | re.IGNORECASE
                    )
                    if match:
                        return match.group(1)
                elif b_name == "go.mod":
                    if self.secure_file_ops and self.secure_file_ops.exists(m_file):
                        try:
                            content = self.secure_file_ops.read_file(m_file)
                        except (FileOperationError, Exception):
                            with open(m_file, "r", encoding="utf-8") as f:
                                content = f.read()
                    else:
                        with open(m_file, "r", encoding="utf-8") as f:
                            content = f.read()
                    match = re.search(r"^module\s+([^\s]+)", content, re.MULTILINE)
                    if match:
                        module_path = match.group(1)
                        if self.go_module_path is None:
                            self.go_module_path = module_path
                            if self.logger:
                                self.logger.info(f"Identified Go module path: {self.go_module_path}")
                        return module_path
        except Exception as e:
            if self.logger:
                self.logger.warning(f"Could not parse module name from {b_name} {m_file}: {e}")
        return None

    def _deduplicate_package(self, package_name, existing_package, new_package_info, manifest_path):
        """
        Merge information from a duplicate package occurrence

        Args:
            package_name (str): Name of the package being deduplicated
            existing_package (dict): Current package info dict
            new_package_info (dict): New package info dict from another manifest
            manifest_path (str): Path to the manifest where new info was found

        Returns:
            Merged package info dict
        """
        # Track all manifests where this package was found
        if "found_in_manifests" not in existing_package:
            existing_package["found_in_manifests"] = []
        existing_package["found_in_manifests"].append(manifest_path)

        existing_version = existing_package.get("version", "")
        new_version = new_package_info.get("version", "")

        if existing_version and new_version and existing_version != new_version:
            # Version conflict detected - just collect it, don't resolve yet
            if "version_conflicts" not in existing_package:
                existing_package["version_conflicts"] = []
                # Add the original version too if not already tracked
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

            # Only add if not already tracked
            if conflict_info not in existing_package["version_conflicts"]:
                existing_package["version_conflicts"].append(conflict_info)
        elif new_version and not existing_version:
            existing_package["version"] = new_version

        # Merge any additional metadata
        for key, value in new_package_info.items():
            if key not in ["version", "ecosystem"] and key not in existing_package:
                existing_package[key] = value

        return existing_package

    def _resolve_version_conflict(self, version1, version2):
        """
        Resolve version conflicts between package versions

        Args:
            version1 (str): First version string
            version2 (str): Second version string

        Returns:
            Resolved version string
        """
        # Strategy 1: If one is a workspace dependency, prefer the other
        if "workspace:" in version1:
            return version2
        if "workspace:" in version2:
            return version1

        # Strategy 2: If one is 'latest' or '*', prefer the more specific one
        if version1 in ["latest", "*"]:
            return version2
        if version2 in ["latest", "*"]:
            return version1

        # Strategy 3: Try to parse semantic versions and choose the higher one
        try:
            # Simple semantic version comparison (doesn't handle all edge cases)
            v1_parts = self._parse_semver(version1)
            v2_parts = self._parse_semver(version2)

            if v1_parts and v2_parts:
                # Compare major.minor.patch
                for i in range(3):
                    if v1_parts[i] > v2_parts[i]:
                        return version1
                    elif v1_parts[i] < v2_parts[i]:
                        return version2

        except Exception:
            # If parsing fails, fall through to next strategy
            pass

        # Strategy 4: Prefer non-range versions over ranges
        if "^" in version1 or "~" in version1 or ">" in version1 or "<" in version1:
            if "^" not in version2 and "~" not in version2 and ">" not in version2 and "<" not in version2:
                return version2
        elif "^" in version2 or "~" in version2 or ">" in version2 or "<" in version2:
            return version1

        # Default: Keep the first version encountered
        return version1

    def _parse_semver(self, version_str):
        """
        Parse a semantic version string into major, minor, patch components

        Args:
            version_str (str): Version string like '1.2.3' or '^1.2.3'

        Returns:
            Tuple of (major, minor, patch) as integers, or None if parsing fails
        """
        cleaned = version_str.lstrip("^~>=<")

        # Split by dots
        parts = cleaned.split(".")
        if len(parts) >= 3:
            try:
                major = int(parts[0])
                minor = int(parts[1])
                patch_str = parts[2].split("-")[0]
                patch = int(patch_str) if patch_str else 0
                return (major, minor, patch)
            except ValueError:
                return None
        return None

    def get_conflict_summary(self):
        """
        Get a summary of all version conflicts found during manifest processing

        Returns:
            Dict with conflict information
        """
        conflicts = {}

        for package_name, package_info in self.external_packages.items():
            if "version_conflicts" in package_info:
                conflicts[package_name] = {
                    "resolved_version": package_info.get("version"),
                    "conflicts": package_info["version_conflicts"],
                    "found_in_manifests": package_info.get("found_in_manifests", []),
                }

        return conflicts

    def _attach_import_names(self):
        """
        Attach import names to external packages by resolving distribution names
        to their corresponding import names
        """
        for dist, meta in self.external_packages.items():
            if "import_names" in meta:
                continue
            eco = meta.get("ecosystem")
            resolver = {
                "pypi": PythonResolver,
                "go": GoResolver,
                "cargo": RustResolver,
                "npm": JsonManifestResolver,
            }.get(eco)

            if resolver:
                # Pass secure_file_ops to resolver (note: JsonManifestResolver needs mode parameter)
                if resolver == JsonManifestResolver:
                    resolver_instance = resolver(secure_file_ops=self.secure_file_ops)
                else:
                    resolver_instance = resolver(secure_file_ops=self.secure_file_ops)
                resolved_import_names = resolver_instance.resolve_package_imports(dist, logger=self.logger)
                if resolved_import_names:
                    meta["import_names"] = resolved_import_names
                else:
                    meta["import_names"] = [dist]
            else:
                meta["import_names"] = [dist]  # Fallback for unknown ecosystems

    # --- Python resolution helpers ---
    def _py_is_invalid_blank_absolute(self, module_str, level):
        """Return True for invalid blank absolute imports (module_str empty and level==0)"""
        return not module_str and level == 0

    def _py_base_dir_for_relative(self, importing_file_rel_path, level):
        """Compute base directory for relative imports, moving up (level-1) levels; return current_dir or None"""
        importing_file_rel_path_norm = str(Path(importing_file_rel_path))
        base_dir = str(Path(importing_file_rel_path_norm).parent)
        if level <= 0:
            return base_dir
        current_dir = base_dir
        for _ in range(level - 1):
            if current_dir == "":
                return None
            current_dir = str(Path(current_dir).parent)
        return current_dir

    def _py_target_paths(self, importing_file_rel_path, module_str, level):
        """Yield candidate repo-relative file paths in order for a Python import"""
        current_dir = self._py_base_dir_for_relative(importing_file_rel_path, level)
        if level > 0 and not module_str:
            # from . import foo -> package __init__.py
            if current_dir is None:
                return
            target_path_init = str(Path(current_dir) / "__init__.py")
            yield str(Path(target_path_init))
            return

        if level > 0:
            if current_dir is None:
                return
            module_parts = module_str.split(".") if module_str else []
            import_path_base = str(Path(current_dir).joinpath(*module_parts)) if module_parts else current_dir
        else:
            module_parts = module_str.split(".") if module_str else []
            import_path_base = str(Path(*module_parts)) if module_parts else "."

        target_path_py = str(Path(f"{import_path_base}.py"))
        yield target_path_py
        target_path_init = str(Path(import_path_base) / "__init__.py")
        yield str(Path(target_path_init))

    def _py_first_existing(self, candidates):
        """Return first candidate path that exists in self.source_files, else None"""
        for cand in candidates:
            cand_norm = str(Path(cand))
            if cand_norm in self.source_files:
                return cand_norm
        return None

    def _resolve_local_import(self, importing_file_rel_path, module_str, relative_level):
        """
        Attempt to resolve a Python import to a local file within the scanned source files

        Args:
            importing_file_rel_path (str): The relative path of the file doing the import
            module_str (str): The module string being imported
                              (e.g., '.utils', '..config', 'scrapers.utils')
            relative_level (int): The number of leading dots (0 for absolute-local)

        Returns:
            The resolved relative path of the imported file if found locally, otherwise None
        """
        if self._py_is_invalid_blank_absolute(module_str, relative_level):
            return None

        candidates = self._py_target_paths(importing_file_rel_path, module_str, relative_level)
        resolved = self._py_first_existing(candidates)
        if resolved:
            return resolved

        return None

    # --- JavaScript/TypeScript resolution helpers ---
    def _join_norm(self, *parts):
        """Join and normalize path parts using pathlib"""
        return str(Path(*parts)) if parts else "."

    def _rel_to_repo(self, abs_path):
        """Return repo-relative normalized path for an absolute path"""
        try:
            rel = str(Path(abs_path).relative_to(self.repo_path))
        except ValueError:
            rel = os.path.relpath(abs_path, self.repo_path)
        return str(Path(rel))

    def _source_has(self, rel_path):
        """Check if a repo-relative path is registered in source_files"""
        return rel_path in self.source_files

    def _disk_file_exists(self, rel_path):
        """Check if a repo-relative path exists on disk as a file"""
        p = Path(self.repo_path) / rel_path
        return p.exists() and p.is_file()

    def _js_resolve_framework_package_alias(self, importing_file_rel_path, module_str):
        """Return '__PACKAGE:<name>' if framework alias maps to a package, else None"""
        if not self.alias_resolver:
            return None
        package_name = self.alias_resolver.config.framework_resolver.get_package_name(module_str)
        if package_name:
            return f"__PACKAGE:{package_name}"
        return None

    def _js_resolve_path_alias(self, importing_file_rel_path, module_str):
        """Use UnifiedAliasResolver to resolve a path alias to a repo-relative path"""
        if not self.alias_resolver:
            return None
        resolved = self.alias_resolver.resolve(importing_file_rel_path, module_str)
        if resolved:
            return resolved
        return None

    def _js_legacy_path_alias(self, importing_file_rel_path, module_str):
        """Legacy alias resolution using js_ts_path_aliases, preserving logging and behavior"""
        if not self.js_ts_path_aliases:
            return None

        for alias_pattern_orig, target_paths_list in self.js_ts_path_aliases.items():
            module_wildcard_part = None

            if "*" in alias_pattern_orig:
                if alias_pattern_orig.endswith("/*"):
                    prefix_to_match = alias_pattern_orig[:-2]
                    if module_str.startswith(prefix_to_match + "/"):
                        module_wildcard_part = module_str[len(prefix_to_match) + 1 :]
                    elif module_str == prefix_to_match:
                        module_wildcard_part = ""
                    else:
                        continue
                elif alias_pattern_orig.endswith("*"):
                    prefix_to_match = alias_pattern_orig[:-1]
                    if module_str.startswith(prefix_to_match):
                        module_wildcard_part = module_str[len(prefix_to_match) :]
                    else:
                        continue
                else:
                    continue
            elif alias_pattern_orig == module_str:
                module_wildcard_part = ""
            else:
                continue

            for target_path_template in target_paths_list:
                if "*" in target_path_template:
                    if target_path_template.endswith("/*"):
                        base_target = target_path_template[:-2]
                        resolved_path_segment = (
                            str(Path(base_target) / module_wildcard_part) if module_wildcard_part else base_target
                        )
                    elif target_path_template.endswith("*"):
                        base_target = target_path_template[:-1]
                        resolved_path_segment = base_target + module_wildcard_part
                    else:
                        if self.logger:
                            self.logger.warning(
                                f"Complex wildcard in target path template '{target_path_template}' not fully supported. Skipping"  # noqa
                            )
                        continue
                else:
                    resolved_path_segment = target_path_template

                if self.js_ts_base_url and self.js_ts_base_url != ".":
                    path_from_repo_root = str(Path(self.js_ts_base_url) / resolved_path_segment)
                else:
                    path_from_repo_root = resolved_path_segment

                path_from_repo_root_normalized = str(Path(path_from_repo_root))

                if path_from_repo_root_normalized in self.source_files:
                    return path_from_repo_root_normalized

                potential_file_on_disk = str(Path(self.repo_path) / path_from_repo_root_normalized)
                if (
                    os.path.splitext(path_from_repo_root_normalized)[1]
                    and Path(potential_file_on_disk).exists()
                    and Path(potential_file_on_disk).is_file()
                ):
                    self.source_files[path_from_repo_root_normalized] = {
                        "absolute_path": potential_file_on_disk,
                        "language": "javascript",
                    }
                    return path_from_repo_root_normalized

                for ext in JS_TS_SOURCE_EXTS:
                    target_path_with_ext = f"{path_from_repo_root_normalized}{ext}"
                    target_path_with_ext_normalized = str(Path(target_path_with_ext))
                    if target_path_with_ext_normalized in self.source_files:
                        return target_path_with_ext_normalized

                has_known_extension = any(
                    path_from_repo_root_normalized.endswith(ext) for ext in JS_TS_SOURCE_EXTS + JSONLIKE_EXTS
                )
                if not has_known_extension:
                    for ext_for_index in JS_TS_SOURCE_EXTS:
                        index_file_path = str(Path(path_from_repo_root_normalized) / f"index{ext_for_index}")
                        index_file_path_normalized = str(Path(index_file_path))
                        if index_file_path_normalized in self.source_files:
                            return index_file_path_normalized

        return None

    def _js_resolve_relative_base(self, importing_file_rel_path, module_str):
        """Resolve a relative module string to a repo-relative base path; return None if not relative"""
        if not module_str.startswith("."):
            return None
        abs_importing_file_dir = str((Path(self.repo_path) / importing_file_rel_path).parent)
        abs_potential_path = str(Path(abs_importing_file_dir) / module_str)
        abs_potential_path_normalized = str(Path(abs_potential_path).resolve())
        return self._rel_to_repo(abs_potential_path_normalized)

    def _js_try_as_is_or_data_like(self, rel_base):
        """Try the path as-is and handle data-like .json/.cjs/.mjs registration; return path or None"""
        if rel_base in self.source_files:
            return rel_base

        full_path = str(Path(self.repo_path) / rel_base)
        if Path(full_path).exists() and Path(full_path).is_file():
            if rel_base.endswith(tuple(JSONLIKE_EXTS + [".cjs", ".mjs"])):
                self.source_files[rel_base] = {
                    "absolute_path": full_path,
                    "language": "json" if rel_base.endswith(".json") else "javascript",
                }
                return rel_base
        return None

    def _js_try_with_source_exts(self, rel_base):
        """Try appending JS/TS source extensions to base; return found path or None"""
        for ext in JS_TS_SOURCE_EXTS:
            target = str(Path(f"{rel_base}{ext}"))
            if target in self.source_files:
                return target
        return None

    def _js_try_index_files(self, rel_base):
        """Try index.{ext} under the base directory when base has no extension; return found path or None"""
        if os.path.splitext(rel_base)[1]:
            return None
        for ext in JS_TS_SOURCE_EXTS:
            cand = str(Path(rel_base) / f"index{ext}")
            cand_norm = str(Path(cand))
            if cand_norm in self.source_files:
                return cand_norm
        return None

    def _resolve_local_import_js(self, importing_file_rel_path, module_str):
        """
        Attempt to resolve a JS/TS import to a local file

        Handles path aliases, relative paths, and checks for various extensions and index files

        For framework aliases that resolve to packages (e.g., $app/ -> @sveltejs/kit),
        this returns a special marker string that the JS handler can recognize

        Args:
            importing_file_rel_path (str): The relative path of the file doing the import
            module_str (str): The module string (e.g., './utils', '@core/Button', 'some-npm-package')

        Returns:
            The resolved relative path of the imported file if found locally,
            a special marker for package aliases (e.g., '__PACKAGE:@sveltejs/kit'),
            or None for unresolvable imports
        """
        # --- BEGIN ALIAS RESOLUTION ---
        if self.alias_resolver:
            pkg_marker = self._js_resolve_framework_package_alias(importing_file_rel_path, module_str)
            if pkg_marker:
                return pkg_marker
            resolved = self._js_resolve_path_alias(importing_file_rel_path, module_str)
            if resolved:
                return resolved
        elif self.js_ts_path_aliases:
            legacy_resolved = self._js_legacy_path_alias(importing_file_rel_path, module_str)
            if legacy_resolved:
                return legacy_resolved

        # --- END ALIAS RESOLUTION ---

        # If module_str starts with '.', it's a relative import
        # If not, and not resolved by alias, it's considered external or unresolvable
        if not module_str.startswith("."):
            return None

        # --- BEGIN RELATIVE PATH RESOLUTION ---
        rel_base = self._js_resolve_relative_base(importing_file_rel_path, module_str)
        if rel_base is None:
            return None

        as_is = self._js_try_as_is_or_data_like(rel_base)
        if as_is:
            return as_is

        with_ext = self._js_try_with_source_exts(rel_base)
        if with_ext:
            return with_ext

        index_file = self._js_try_index_files(rel_base)
        if index_file:
            return index_file

        # If not found after checks
        return None

    # --- Rust resolution helpers ---
    def _rust_prefix_and_remainder(self, importing_file_rel_path, use_path_parts):
        """Compute base dir from crate/self/super or relative; return (current_dir_from_prefix, first_part, path_after_prefix)"""
        if not use_path_parts:
            return "", "", []
        first_part = use_path_parts[0]
        if first_part == "crate":
            return "src", "crate", use_path_parts[1:]
        if first_part == "self":
            return str(Path(importing_file_rel_path).parent), "self", use_path_parts[1:]
        if first_part == "super":
            return str(Path(importing_file_rel_path).parent.parent), "super", use_path_parts[1:]
        importing_dir = str(Path(importing_file_rel_path).parent)
        if importing_dir == "src" and Path(importing_file_rel_path).name in ["main.rs", "lib.rs"]:
            current_dir_from_prefix = "src"
        else:
            current_dir_from_prefix = importing_dir
        if self.logger:
            self.logger.debug(
                f"[_resolve_local_import_rust] Path does not start with crate/self/super. "
                f"Treating as relative to '{current_dir_from_prefix}'. Path segments: {use_path_parts}"
            )
        return current_dir_from_prefix, first_part, use_path_parts

    def _rust_handle_empty_or_wildcard(
        self, first_part, importing_file_rel_path, current_dir_from_prefix, path_after_prefix
    ):
        """Handle empty remainder and wildcard cases; return (resolved_path_or_None, handled_bool)"""
        if not path_after_prefix:
            if first_part == "crate":
                lib_rs_path = str(Path(current_dir_from_prefix) / "lib.rs")
                if lib_rs_path in self.source_files:
                    return lib_rs_path, True
                main_rs_path = str(Path(current_dir_from_prefix) / "main.rs")
                if main_rs_path in self.source_files:
                    return main_rs_path, True
            return None, True

        if len(path_after_prefix) == 1 and path_after_prefix[0] == "*":
            if first_part == "crate":
                lib_rs_path = str(Path(current_dir_from_prefix) / "lib.rs")
                if lib_rs_path in self.source_files:
                    return lib_rs_path, True
                main_rs_path = str(Path(current_dir_from_prefix) / "main.rs")
                if main_rs_path in self.source_files:
                    return main_rs_path, True
                return None, True

            if first_part == "self":
                return importing_file_rel_path, True

            if first_part == "super":
                parent_dir_of_importing_file = str(Path(importing_file_rel_path).parent)
                super_module_name_segment = Path(parent_dir_of_importing_file).name
                super_target_rs = str(Path(current_dir_from_prefix) / f"{super_module_name_segment}.rs")
                if super_target_rs in self.source_files:
                    return super_target_rs, True
                super_target_mod_rs = str(Path(current_dir_from_prefix) / super_module_name_segment / "mod.rs")
                if super_target_mod_rs in self.source_files:
                    return super_target_mod_rs, True
                return None, True

        return None, False

    def _rust_try_module_candidates(self, current_dir_from_prefix, path_after_prefix):
        """Iteratively try '<dir>/<module>.rs' and '<dir>/<module>/mod.rs' from longest to shortest prefix"""
        for i in range(len(path_after_prefix), 0, -1):
            current_module_segments = path_after_prefix[:i]
            if not current_module_segments:
                continue
            if current_module_segments[-1] == "*":
                continue
            path_parts_for_rs = [current_dir_from_prefix]
            if len(current_module_segments) > 1:
                path_parts_for_rs.extend(current_module_segments[:-1])
            path_parts_for_rs.append(f"{current_module_segments[-1]}.rs")
            target_file_rs = str(Path(*path_parts_for_rs)) if path_parts_for_rs else "."
            if target_file_rs in self.source_files:
                return target_file_rs
            path_parts_for_mod_rs = [current_dir_from_prefix]
            path_parts_for_mod_rs.extend(current_module_segments)
            path_parts_for_mod_rs.append("mod.rs")
            target_file_mod_rs = str(Path(*path_parts_for_mod_rs)) if path_parts_for_mod_rs else "."
            if target_file_mod_rs in self.source_files:
                return target_file_mod_rs
        return None

    def _resolve_local_import_rust(self, importing_file_rel_path, use_path_parts):
        """
        Attempt to resolve a Rust 'use' path to a local module file

        Handles crate::, self::, super:: prefixes and performs iterative resolution

        For `use a::b::Item;`, it tries to find module `a::b`, then `a`
        """
        if not use_path_parts:
            return None

        current_dir_from_prefix, first_part, path_after_prefix = self._rust_prefix_and_remainder(
            importing_file_rel_path, use_path_parts
        )

        resolved, handled = self._rust_handle_empty_or_wildcard(
            first_part, importing_file_rel_path, current_dir_from_prefix, path_after_prefix
        )
        if handled:
            return resolved

        resolved = self._rust_try_module_candidates(current_dir_from_prefix, path_after_prefix)
        if resolved:
            return resolved

        if self.logger:
            self.logger.debug(
                f"[_resolve_local_import_rust] Could not resolve: {'::'.join(use_path_parts)} to a local module file after all checks."  # noqa
            )
        return None

    # --- Go resolution helpers ---
    def _go_is_module_absolute(self, module_str):
        """Check if module_str is a module-absolute path under self.go_module_path"""
        return bool(self.go_module_path and module_str.startswith(self.go_module_path))

    def _go_import_path_for_relative(self, importing_file_rel_path, module_str):
        """Compute repo-relative import path for a relative Go import"""
        abs_importing_file_dir = str((Path(self.repo_path) / importing_file_rel_path).parent)
        abs_target_path = str((Path(abs_importing_file_dir) / module_str).resolve())
        try:
            import_path = str(Path(abs_target_path).relative_to(self.repo_path))
        except ValueError:
            import_path = os.path.relpath(abs_target_path, self.repo_path)
        return str(Path(import_path))

    def _go_candidate_files(self, import_path):
        """Yield candidate Go files for an import path: '<import_path>.go' and '<import_path>/<dir_basename>.go'"""
        package_dir_name = Path(import_path).name
        yield str(Path(f"{import_path}.go"))
        yield str(Path(import_path) / f"{package_dir_name}.go")

    def _go_find_single_go_in_dir(self, import_path):
        """If exactly one .go exists under directory import_path, return it; if multiple, return list for caller to warn; else None"""  # noqa
        current_search_dir_prefix = "" if import_path == "." else import_path + os.sep
        found_files_in_dir = []
        for sf_rel_path in self.source_files:
            if current_search_dir_prefix == "":
                if os.sep not in sf_rel_path and sf_rel_path.endswith(".go"):
                    found_files_in_dir.append(sf_rel_path)
            elif sf_rel_path.startswith(current_search_dir_prefix) and sf_rel_path.endswith(".go"):
                found_files_in_dir.append(sf_rel_path)
        if len(found_files_in_dir) == 1:
            return found_files_in_dir[0]
        if len(found_files_in_dir) > 1:
            return found_files_in_dir  # Caller logs ambiguous warning
        return None

    def _resolve_local_import_go(self, importing_file_rel_path, module_str):
        """
        Attempt to resolve a Go import to a local file/package

        Handles relative paths like './utils' or '../models'

        Module-absolute paths require knowing the module root, which is complex to determine reliably here

        Args:
            importing_file_rel_path (str): The relative path of the file doing the import
            module_str (str): The module string (e.g., './utils', 'github.com/gin-gonic/gin')

        Returns:
            The resolved relative path of the imported directory's primary file
            (e.g., utils/utils.go or utils.go) if found locally, otherwise None
        """
        if not module_str.startswith("."):
            # Not a relative path, check if it's a module-absolute local import
            if self._go_is_module_absolute(module_str):
                relative_part = module_str[len(self.go_module_path) :].lstrip("/")
                import_path = str(Path(relative_part).resolve())
            else:
                # Truly external or standard library
                return None
        else:
            import_path = self._go_import_path_for_relative(importing_file_rel_path, module_str)

        # 1. Check direct candidate files
        for cand in self._go_candidate_files(import_path):
            cand_norm = str(Path(cand))
            if cand_norm in self.source_files:
                return cand_norm

        # 2. Scan directory for a representative .go file
        single_or_list = self._go_find_single_go_in_dir(import_path)
        if isinstance(single_or_list, str):
            return single_or_list
        elif isinstance(single_or_list, list):
            if self.logger:
                self.logger.warning(
                    f"Go resolver: Found multiple .go files in directory '{import_path}' "
                    f"for import '{module_str}' from '{importing_file_rel_path}': {single_or_list}. Resolution is ambiguous."  # noqa
                )

        return None

    # --- Solidity resolution helpers ---
    def _solidity_try_remappings(self, import_path_str, remappings_dict):
        """Apply remappings to resolve non-relative imports; return repo-relative path or None"""
        if not remappings_dict:
            return None
        for prefix, remapped_base in remappings_dict.items():
            if import_path_str.startswith(prefix):
                path_after_prefix = import_path_str[len(prefix) :]
                remapped_path_segment = str(Path(remapped_base) / path_after_prefix)
                full_path = str((Path(self.repo_path) / remapped_path_segment).resolve())
                try:
                    relative_path = str(Path(full_path).relative_to(self.repo_path))
                except ValueError:
                    relative_path = os.path.relpath(full_path, self.repo_path)
                normalized_rel_path = str(Path(relative_path))
                if normalized_rel_path in self.source_files:
                    return normalized_rel_path
        return None

    def _solidity_relative_target(self, importing_file_rel_path, import_path_str):
        """Resolve relative Solidity import to repo-relative .sol file; include foundry src fallback"""
        base_dir = str(Path(importing_file_rel_path).parent)
        if self.secure_file_ops:
            abs_base_dir = self.secure_file_ops.join_paths(self.repo_path, base_dir)
        else:
            abs_base_dir = os.path.join(self.repo_path, base_dir)
        target_path_abs = os.path.normpath(os.path.join(abs_base_dir, import_path_str))
        try:
            target_path = str(Path(target_path_abs).relative_to(self.repo_path))
        except ValueError:
            target_path = os.path.relpath(target_path_abs, self.repo_path)
        target_path = str(Path(target_path))
        if not target_path.endswith(".sol"):
            return None
        if target_path in self.source_files:
            return target_path
        if (
            self.solidity_src_path
            and import_path_str.startswith("../")
            and importing_file_rel_path.startswith(self.solidity_src_path + os.sep)
        ):
            path_segment_after_dots = import_path_str[3:]
            fallback_target_path = str(Path(self.solidity_src_path) / path_segment_after_dots)
            fallback_target_path = str(Path(fallback_target_path))
            if fallback_target_path in self.source_files:
                return fallback_target_path
        return None

    def _resolve_local_import_solidity(self, importing_file_rel_path, import_path_str):
        """
        Attempt to resolve a Solidity import to a local file

        Handles relative paths like './MyContract.sol' or '../interfaces/IERC20.sol'

        Args:
            importing_file_rel_path (str): The relative path of the file doing the import
            import_path_str (str): The path string from the import directive

        Returns:
            The resolved relative path of the imported .sol file if found locally, otherwise None
        """

        # 1. Check Remappings (Hardhat first, then remappings.txt)
        if not import_path_str.startswith("."):
            resolved = self._solidity_try_remappings(import_path_str, self.hardhat_remappings)
            if resolved:
                return resolved
            resolved = self._solidity_try_remappings(import_path_str, self.remappings)
            if resolved:
                return resolved
            return None

        # 2. Handle Relative Paths (if not handled by remappings)
        if import_path_str.startswith("."):
            target = self._solidity_relative_target(importing_file_rel_path, import_path_str)
            if target:
                return target

        # 3. If not found by any method
        return None

    def _get_hardhat_remappings(self):
        """
        Execute the Node.js script to get Hardhat remappings if available,
        prioritizing locally installed Node.js dependencies for the script

        Returns:
            Dictionary of remappings or empty dict if script/Node not found or error occurs
        """

        script_filename = "parse_remappings.cjs"
        helper_module_path_parts = ["external_helpers", "hardhat_config_parser"]

        current_file_abs_path = Path(__file__).resolve()
        current_file_dir = current_file_abs_path.parent
        gardener_package_root = current_file_dir.parent
        script_path_abs = gardener_package_root.joinpath(*helper_module_path_parts, script_filename)

        # Directory containing the .cjs script and its package.json / node_modules
        script_containing_dir_abs = script_path_abs.parent
        local_node_modules_abs = script_containing_dir_abs / "node_modules"

        if not script_path_abs.exists():
            return {}

        node_executable = shutil.which("node")
        if not node_executable:
            if self.logger:
                self.logger.warning("Node.js executable not found in PATH. Cannot get Hardhat remappings.")
            return {}

        # Validate repo_path before using it
        try:
            validated_repo_path = InputValidator.validate_file_path(self.repo_path, must_exist=True)
        except ValidationError as e:
            if self.logger:
                self.logger.error(f"Invalid repository path: {e}")
            return {}

        # self.repo_path is the path to the Hardhat project being analyzed (passed to the script)
        command = [node_executable, str(script_path_abs), str(validated_repo_path)]

        # Prepare environment for subprocess with security constraints
        env_vars = {}
        if local_node_modules_abs.is_dir():
            env_vars["NODE_PATH"] = str(local_node_modules_abs)
            if self.logger:
                self.logger.debug(
                    f"Hardhat script: Using local node_modules. Setting NODE_PATH to: {local_node_modules_abs}"
                )
        elif self.logger:  # Optional: Warn if local node_modules is missing
            warning_msg = (
                f"Local node_modules for Hardhat helper not found at {local_node_modules_abs}. "
                f"Ensure 'npm install' was run in '{script_containing_dir_abs}'. "
                "Script might rely on global or target project's ts-node."
            )
            self.logger.warning(warning_msg)

        try:
            # Use SecureSubprocess for sandboxed execution
            secure_runner = SecureSubprocess(
                allowed_root=validated_repo_path, timeout=60  # 60 seconds should be enough for parsing config
            )

            result = secure_runner.run(command, cwd=validated_repo_path, env=env_vars, capture_output=True, check=False)

            if result.returncode != 0:
                error_parts = [f"Error getting Hardhat remappings. Script exited with code {result.returncode}."]
                # It's often helpful to include stdout and stderr for debugging script errors
                if result.stdout:
                    error_parts.append(f"Script stdout:\n{result.stdout.strip()}")
                if result.stderr:
                    error_parts.append(f"Script stderr:\n{result.stderr.strip()}")
                error_message = "\n".join(error_parts)
                if self.logger:
                    self.logger.error(error_message)
                return {}

            try:
                remappings = json.loads(result.stdout)
                return remappings
            except json.JSONDecodeError as e:
                error_message = (
                    f"Failed to parse JSON output from Hardhat remapping script: {e}\n"
                    f"Raw script output was:\n{result.stdout}"
                )
                if self.logger:
                    self.logger.error(error_message)
                return {}

        except (SubprocessSecurityError, ValidationError) as e:
            # Security constraint violation
            if self.logger:
                self.logger.error(f"Security error executing Hardhat script: {e}")
            return {}
        except FileNotFoundError:
            # This specific error means the node_executable itself wasn't found at runtime
            if self.logger:
                error_msg = (
                    f"Node.js executable '{node_executable}' not found. " "Ensure Node.js is installed and in PATH."
                )
                self.logger.error(error_msg)
            return {}
        except Exception as e:
            # Catch any other unexpected errors during subprocess execution
            if self.logger:
                self.logger.error(f"An unexpected error occurred while running Hardhat remapping script: {e}")
            return {}

    def _process_js_ts_configs(self):
        """
        Parses jsconfig.json or tsconfig.json to extract path aliasing configuration
        """

        config_file_to_parse = None
        config_type_parsed = None  # 'tsconfig' or 'jsconfig'

        # Prioritize root tsconfig.json
        root_ts_configs = [
            p
            for p in self.ts_config_files
            if str(
                Path(
                    self.secure_file_ops.get_relative_path(p)
                    if self.secure_file_ops
                    else os.path.relpath(p, self.repo_path)
                ).parent
            )
            == "."
        ]
        if root_ts_configs:
            config_file_to_parse = root_ts_configs[0]  # Take the first root tsconfig
            config_type_parsed = "tsconfig.json"
            if self.logger:
                self.logger.info(
                    f"Found root tsconfig.json: {self.secure_file_ops.get_relative_path(config_file_to_parse) if self.secure_file_ops else os.path.relpath(config_file_to_parse, self.repo_path)}. This will be used for JS/TS path aliases."
                )  # noqa
            if len(root_ts_configs) > 1:
                if self.logger:
                    self.logger.warning(
                        f"Multiple root tsconfig.json files found. Using the first one: {self.secure_file_ops.get_relative_path(config_file_to_parse) if self.secure_file_ops else os.path.relpath(config_file_to_parse, self.repo_path)}"
                    )  # noqa

        # If no root tsconfig, try root jsconfig.json
        if not config_file_to_parse:
            root_js_configs = [
                p
                for p in self.js_config_files
                if str(
                    Path(
                        self.secure_file_ops.get_relative_path(p)
                        if self.secure_file_ops
                        else os.path.relpath(p, self.repo_path)
                    ).parent
                )
                == "."
            ]
            if root_js_configs:
                config_file_to_parse = root_js_configs[0]  # Take the first root jsconfig
                config_type_parsed = "jsconfig.json"
                if self.logger:
                    self.logger.info(
                        f"Found root jsconfig.json: {self.secure_file_ops.get_relative_path(config_file_to_parse) if self.secure_file_ops else os.path.relpath(config_file_to_parse, self.repo_path)}. This will be used for JS/TS path aliases."
                    )  # noqa
                if len(root_js_configs) > 1:
                    if self.logger:
                        self.logger.warning(
                            f"Multiple root jsconfig.json files found. Using the first one: {self.secure_file_ops.get_relative_path(config_file_to_parse) if self.secure_file_ops else os.path.relpath(config_file_to_parse, self.repo_path)}"
                        )  # noqa

        if not config_file_to_parse:
            if self.ts_config_files or self.js_config_files:  # Configs exist, but not at root
                if self.logger:
                    self.logger.warning(
                        "JS/TS config files found but none at the repository root. Path aliases will not be processed from these non-root files."
                    )  # noqa
                # Still initialize alias resolver with framework defaults
                self._initialize_alias_resolver()
                return
            else:  # No config files found at all
                # Still initialize alias resolver with framework defaults
                self._initialize_alias_resolver()
                return

        try:
            # Read config file with secure operations or fallback
            if self.secure_file_ops:
                rel_path = self.secure_file_ops.get_relative_path(config_file_to_parse)
                # Use 'utf-8-sig' to handle potential BOM
                content = self.secure_file_ops.read_file(rel_path, encoding="utf-8-sig")
            else:
                # Use 'utf-8-sig' to handle potential BOM
                with open(config_file_to_parse, "r", encoding="utf-8-sig") as f:
                    content = f.read()

            # Robust comment stripping
            # This regex first tries to match complete strings (double or single-quoted)
            # If a string is matched, the lambda function returns it unchanged
            # Otherwise, it tries to match single-line (//) or multi-line (/*...*/) comments
            # If a comment is matched, the lambda function returns an empty string, effectively removing it
            # re.S (re.DOTALL) allows '.' in multi-line comments to match newline characters
            comment_regex = r"'(\\'|[^'])*?'|\"(\\\"|[^\"])*?\"|//[^\r\n]*|/\*(?:(?!\*/).)*\*/"
            content = re.sub(
                comment_regex,
                lambda m: m.group(0) if m.group(0).startswith('"') or m.group(0).startswith("'") else "",
                content,
                flags=re.S,
            )

            # This regex finds a comma, optionally followed by whitespace,
            # immediately followed by a closing square bracket or curly brace
            # It replaces this with just the closing bracket/brace
            content = re.sub(r",\s*([\]}])", r"\1", content)

            data = json.loads(content)

            compiler_options = data.get("compilerOptions", {})
            base_url = compiler_options.get("baseUrl")
            paths = compiler_options.get("paths")

            if base_url is not None and isinstance(base_url, str):
                self.js_ts_base_url = base_url
                if self.logger:
                    self.logger.info(f"Extracted baseUrl '{self.js_ts_base_url}' from {config_type_parsed}")

            if paths is not None and isinstance(paths, dict):
                self.js_ts_path_aliases = paths
                if self.logger:
                    self.logger.info(
                        f"Extracted paths configuration from {config_type_parsed}: {self.js_ts_path_aliases}"
                    )  # noqa

        except FileNotFoundError:
            if self.logger:
                self.logger.error(f"Selected JS/TS config file not found: {config_file_to_parse}")
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.error(
                    f"Error decoding JSON from {config_type_parsed} ({self.secure_file_ops.get_relative_path(config_file_to_parse) if self.secure_file_ops else os.path.relpath(config_file_to_parse, self.repo_path)}): {e}. Path aliases may not be correctly parsed. Consider removing comments if present."
                )  # noqa
        except Exception as e:
            if self.logger:
                self.logger.error(
                    f"An unexpected error occurred while processing {config_type_parsed} ({self.secure_file_ops.get_relative_path(config_file_to_parse) if self.secure_file_ops else os.path.relpath(config_file_to_parse, self.repo_path)}): {e}"
                )  # noqa

        self._initialize_alias_resolver()

    def _initialize_alias_resolver(self):
        """Initialize the UnifiedAliasResolver with loaded configuration"""
        config = AliasConfiguration()

        if self.js_ts_path_aliases:
            config.ts_js_paths = self.js_ts_path_aliases
            config.base_url = self.js_ts_base_url

        # The framework resolver is already initialized with default configs
        # in AliasConfiguration, which includes SvelteKit aliases

        self.alias_resolver = UnifiedAliasResolver(
            config=config, repo_path=self.repo_path, source_files=self.source_files, logger=self.logger
        )

    def extract_imports_from_all_files(self):
        """
        Extract imports and components from all source files

        This method now only focuses on extracting import information
        and populating self.file_imports and self.file_package_components

        Returns:
            None (modifies instance attributes directly)
        """
        if self.logger:
            self.logger.info(f"\nExtracting imports from {len(self.source_files)} source files")
        processed_files = 0

        for rel_path, file_info in list(self.source_files.items()):  # Iterate over a copy
            abs_path = file_info["absolute_path"]
            language = file_info["language"]
            if not language or language not in self.language_handlers:
                continue

            handler = self.language_handlers[language]

            try:

                try:
                    parser = get_parser(language)
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Failed to get parser for {language}: {str(e)}, skipping file {rel_path}")
                    continue

                try:
                    file_size = Path(abs_path).stat().st_size
                    if file_size > ResourceLimits.MAX_FILE_SIZE:
                        if self.logger:
                            self.logger.warning(
                                f"Skipping {rel_path}: file size ({file_size / 1024 / 1024:.1f}MB) "
                                f"exceeds limit ({ResourceLimits.MAX_FILE_SIZE / 1024 / 1024}MB)"
                            )
                        continue
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Could not check file size for {abs_path}: {e}")

                # Read file content
                try:
                    if self.secure_file_ops:
                        code = self.secure_file_ops.read_file(rel_path, encoding="utf-8")
                    else:
                        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                            code = f.read()
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Could not read file {abs_path}: {e}, skipping")
                    continue

                # Parse code with timeout protection
                if self.logger:
                    self.logger.debug(f"Parsing {rel_path} ({len(code)} bytes)")
                try:
                    with timeout(ResourceLimits.PARSE_TIMEOUT):
                        tree = parser.parse(bytes(code, "utf-8"))
                except TimeoutError as e:
                    if self.logger:
                        self.logger.warning(f"Parsing timed out for {rel_path}: {str(e)}, skipping")
                    continue
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Failed to parse {rel_path}: {str(e)}, skipping")
                    continue

                # Extract imports using the handler
                try:
                    # Determine the resolver function based on language
                    resolver_func = None
                    if language == "python":
                        resolver_func = self._resolve_local_import
                    elif language in ["javascript", "typescript"]:
                        resolver_func = self._resolve_local_import_js
                    elif language == "rust":
                        resolver_func = self._resolve_local_import_rust
                    elif language == "go":
                        resolver_func = self._resolve_local_import_go
                    elif language == "solidity":
                        resolver_func = self._resolve_local_import_solidity

                    # All handlers now have the same signature with logger as optional parameter
                    external_imports, local_imports = handler.extract_imports(
                        tree.root_node, rel_path, self.file_package_components, resolver_func, logger=self.logger
                    )

                    if external_imports:
                        self.file_imports[rel_path] = external_imports
                    if local_imports:
                        self.local_imports_map[rel_path] = local_imports  # Store resolved local paths

                    processed_files += 1
                except Exception as e:
                    if self.logger:
                        self.logger.warning(f"Error extracting imports from {rel_path}: {str(e)}")

            except Exception as e:
                if self.logger:
                    self.logger.error(f"Unexpected error processing file {rel_path}", e)

        if self.logger:
            self.logger.info(f"... Processed {processed_files}/{len(self.source_files)} files for imports")
        return

    def _parse_gitmodules(self):
        """Parse .gitmodules file to extract submodule paths and URLs"""
        gitmodules_rel_path = ".gitmodules"

        if self.secure_file_ops:
            if not self.secure_file_ops.exists(gitmodules_rel_path):
                return
        else:
            gitmodules_path = str(Path(self.repo_path) / gitmodules_rel_path)
            if not Path(gitmodules_path).exists():
                return

        # configparser is imported at the top of the file
        config = configparser.ConfigParser()
        try:
            # Read with utf-8 encoding
            if self.secure_file_ops:
                content = self.secure_file_ops.read_file(gitmodules_rel_path, encoding="utf-8")
                config.read_string(content)
            else:
                gitmodules_path = str(Path(self.repo_path) / gitmodules_rel_path)
                with open(gitmodules_path, "r", encoding="utf-8") as f:
                    config.read_file(f)  # Use read_file for explicit encoding handling

            parsed_data = {}
            for section in config.sections():
                if config.has_option(section, "path") and config.has_option(section, "url"):
                    submodule_path_raw = config.get(section, "path")
                    submodule_url = config.get(section, "url")

                    # Normalize path using Path().resolve() for consistency
                    normalized_path = str(Path(submodule_path_raw).resolve()).rstrip(os.sep)

                    parsed_data[normalized_path] = submodule_url
            self.submodule_data = parsed_data
        except configparser.Error as e:  # More specific error for parsing
            if self.logger:
                self.logger.warning(f"Could not parse .gitmodules file at '{gitmodules_path}': {e}")
        except Exception as e:  # Generic catch-all for other issues like file IO
            if self.logger:
                self.logger.error(f"An unexpected error occurred while parsing .gitmodules at '{gitmodules_path}': {e}")
