"""
Repository scanning and import extraction orchestrator

Coordinates repository scanning, manifest processing, alias configuration, and
import extraction using helper modules while preserving the public API surface
of RepositoryAnalyzer
"""

import os
from collections import defaultdict
from pathlib import Path

from gardener.analysis import imports as imports_mod
from gardener.analysis import js_ts_aliases
from gardener.analysis import manifests
from gardener.analysis import scanner
from gardener.analysis import solidity_meta
from gardener.treewalk.solidity import SolidityLanguageHandler
from gardener.common.secure_file_ops import FileOperationError, SecureFileOps

TimeoutError = imports_mod.TimeoutError
timeout = imports_mod.timeout


class RepositoryAnalyzer:
    """
    Main controller that orchestrates the dependency analysis process

    Coordinates the analysis of repository source code to extract dependencies
    """

    def __init__(self, repo_path, focus_languages=None, logger=None):
        """
        Initialize a new analyzer instance

        Args:
            repo_path (str): Absolute path to the repository to analyze
            focus_languages (list|None): Optional list of languages to focus on
            logger (Logger|None): Optional logger instance

        Returns:
            None
        """
        self.repo_path = repo_path
        self.logger = logger
        self.focus_languages = focus_languages

        try:
            self.secure_file_ops = SecureFileOps(repo_path, logger)
        except FileOperationError as exc:
            if logger:
                logger.error(f"Failed to initialize secure file operations: {exc}")
            self.secure_file_ops = None

        self.gitignore_spec = self._load_gitignore()

        self.manifest_files = []
        self.root_manifest_files = []
        self.source_files = {}
        self.external_packages = {}
        self.file_imports = defaultdict(list)
        self.file_package_components = defaultdict(list)
        self.local_imports_map = defaultdict(list)
        self.root_package_names = set()
        self.go_module_path = None
        self.hardhat_remappings = {}
        self.remappings = {}
        self.solidity_src_path = None
        self.js_config_files = []
        self.ts_config_files = []
        self.js_ts_base_url = None
        self.js_ts_path_aliases = {}
        self.alias_resolver = None
        self.submodule_data = {}

        self.language_handlers = {}
        self._local_resolver = None

    def _load_gitignore(self):
        """
        Load .gitignore patterns if available

        Returns:
            pathspec.PathSpec|None: Compiled matcher or None
        """
        return scanner.load_gitignore(self.secure_file_ops, self.logger)

    def is_ignored(self, path):
        """
        Check if a path should be ignored according to .gitignore

        Args:
            path (str): Absolute path to test

        Returns:
            bool: True if ignored, otherwise False
        """
        if not self.gitignore_spec:
            return False
        try:
            if self.secure_file_ops:
                rel_path = self.secure_file_ops.get_relative_path(path)
            else:
                rel_path = os.path.relpath(path, self.repo_path)
        except ValueError:
            return False
        rel_path = str(Path(rel_path))
        return self.gitignore_spec.match_file(rel_path)

    def register_language_handler(self, language, handler):
        """
        Register a language handler

        Args:
            language (str): Language key
            handler (object): Language handler implementing required interface

        Returns:
            None
        """
        self.language_handlers[language] = handler
        self._local_resolver = None
        if self.logger:
            self.logger.debug(f"Registered language handler: {language}")

    def scan_repo(self):
        """
        Scan repo to identify source files and manifest files

        Returns:
            Tuple of (source_files map, manifest file list)
        """
        result = scanner.scan_repository(
            repo_path=self.repo_path,
            secure_file_ops=self.secure_file_ops,
            focus_languages=self.focus_languages,
            language_handlers=self.language_handlers,
            logger=self.logger,
        )

        self.source_files = result["source_files"]
        self.manifest_files = result["manifest_files"]
        self.root_manifest_files = result["root_manifest_files"]
        self.js_config_files = result["js_config_files"]
        self.ts_config_files = result["ts_config_files"]
        self.solidity_src_path = result["solidity_src_path"]
        self.submodule_data = result["submodule_data"]
        self.gitignore_spec = result["gitignore_spec"]
        self._local_resolver = None

        if self.logger:
            self.logger.info(
                f"... Found {len(self.source_files)} source files, "
                f"{len(self.manifest_files)} total manifest files "
                f"({len(self.root_manifest_files)} at root)"
            )

        self.hardhat_remappings = self._get_hardhat_remappings()
        if self.hardhat_remappings and self.logger:
            self.logger.debug(f"Retrieved Hardhat remappings: {self.hardhat_remappings}")

        return self.source_files, self.manifest_files

    def process_manifest_files(self):
        """
        Process manifest files to extract dependencies

        Returns:
            dict: External package metadata keyed by distribution name
        """
        self.remappings = solidity_meta.parse_remappings_txt(self.secure_file_ops, self.logger)
        self.hardhat_remappings = solidity_meta.get_hardhat_remappings(self.repo_path, self.logger)

        roots, go_module = manifests.collect_root_package_names_and_workspaces(
            self.root_manifest_files,
            self.secure_file_ops,
            self.logger,
            self.repo_path,
        )
        self.root_package_names = roots
        if go_module and not self.go_module_path:
            self.go_module_path = go_module

        self.external_packages = manifests.process_manifests(
            self.manifest_files, self.language_handlers, self.secure_file_ops, self.logger
        )

        if self.logger:
            self.logger.info(f"... Found {len(self.external_packages)} unique external packages")

        sol_handler = SolidityLanguageHandler()
        for remap_dict, source_name in [
            (self.remappings, "remappings.txt"),
            (self.hardhat_remappings, "hardhat config"),
        ]:
            self._solidity_candidates_from_remappings(remap_dict, source_name, sol_handler)

        self.external_packages = manifests.attach_import_names(
            self.external_packages, self.secure_file_ops, self.logger
        )

        base_url, paths = js_ts_aliases.parse_ts_js_config(
            self.repo_path,
            self.js_config_files,
            self.ts_config_files,
            self.secure_file_ops,
            self.logger,
        )
        self.js_ts_base_url = base_url
        self.js_ts_path_aliases = paths
        self.alias_resolver = js_ts_aliases.create_alias_resolver(
            self.repo_path, self.source_files, self.js_ts_base_url, self.js_ts_path_aliases, self.logger
        )

        self.external_packages = solidity_meta.associate_submodules_with_solidity_packages(
            self.external_packages,
            self.remappings,
            self.hardhat_remappings,
            self.submodule_data,
            self.logger,
        )

        manifests.resolve_version_conflicts(self.external_packages, self.logger)

        try:
            self.manifest_files.sort()
            self.root_manifest_files.sort()
        except Exception:
            pass

        return self.external_packages

    def _solidity_candidates_from_remappings(self, remappings_dict, source_name, sol_handler):
        if not remappings_dict:
            return

        # Use shared canonicalization to keep behavior consistent across helpers

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
            if not is_library:
                continue

            package_name = sol_handler.normalize_package_name(prefix)
            package_name = solidity_meta.canonicalize_solidity_package_name(package_name) if package_name else package_name
            if not package_name:
                if self.logger:
                    self.logger.warning(
                        f"Could not normalize potential package prefix '{prefix}' from {source_name} remapping"
                    )
                continue

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
                if source_name not in self.external_packages[package_name].get("source", "") and self.logger:
                    self.logger.debug(
                        f"  Remapped package '{package_name}' (from {source_name}: '{prefix}' -> '{path}') already identified from {self.external_packages[package_name]['source']}"  # noqa
                    )

    def extract_imports_from_all_files(self):
        """
        Extract imports and components from all source files

        Returns:
            None
        """
        if self.logger:
            self.logger.info(f"\nExtracting imports from {len(self.source_files)} source files")

        self._local_resolver = imports_mod.LocalImportResolver(
            repo_path=self.repo_path,
            source_files=self.source_files,
            alias_resolver=self.alias_resolver,
            js_ts_base_url=self.js_ts_base_url,
            js_ts_path_aliases=self.js_ts_path_aliases,
            go_module_path=self.go_module_path,
            remappings=self.remappings,
            hardhat_remappings=self.hardhat_remappings,
            solidity_src_path=self.solidity_src_path,
            logger=self.logger,
        )

        file_imports, local_imports_map, file_package_components = imports_mod.extract_imports(
            self.source_files,
            self.language_handlers,
            self.repo_path,
            self.secure_file_ops,
            self._local_resolver,
            self.logger,
        )

        self.file_imports = file_imports
        self.local_imports_map = local_imports_map
        self.file_package_components = file_package_components

    def _get_local_resolver(self):
        """
        Lazily construct and return the LocalImportResolver

        Returns:
            LocalImportResolver: Resolver instance bound to current analyzer state
        """
        if self._local_resolver is None:
            self._local_resolver = imports_mod.LocalImportResolver(
                repo_path=self.repo_path,
                source_files=self.source_files,
                alias_resolver=self.alias_resolver,
                js_ts_base_url=self.js_ts_base_url,
                js_ts_path_aliases=self.js_ts_path_aliases,
                go_module_path=self.go_module_path,
                remappings=self.remappings,
                hardhat_remappings=self.hardhat_remappings,
                solidity_src_path=self.solidity_src_path,
                logger=self.logger,
            )
        return self._local_resolver

    def _resolve_local_import(self, importing_file_rel_path, module_str, relative_level):
        """
        Wrapper for Python local import resolution

        Args:
            importing_file_rel_path (str): Importing file path
            module_str (str): Import module string
            relative_level (int): Dots count for relative import

        Returns:
            str|None: Resolved path or None
        """
        return self._get_local_resolver().resolve_python(importing_file_rel_path, module_str, relative_level)

    def _resolve_local_import_js(self, importing_file_rel_path, module_str):
        """
        Wrapper for JS/TS local import resolution

        Args:
            importing_file_rel_path (str): Importing file path
            module_str (str): Import string

        Returns:
            str|None: Resolved path or None
        """
        return self._get_local_resolver().resolve_js(importing_file_rel_path, module_str)

    def _resolve_local_import_rust(self, importing_file_rel_path, use_path_parts):
        """
        Wrapper for Rust local module resolution

        Args:
            importing_file_rel_path (str): Importing file path
            use_path_parts (list): `use` path components

        Returns:
            str|None: Resolved path or None
        """
        return self._get_local_resolver().resolve_rust(importing_file_rel_path, use_path_parts)

    def _resolve_local_import_go(self, importing_file_rel_path, module_str):
        """
        Wrapper for Go local import resolution

        Args:
            importing_file_rel_path (str): Importing file path
            module_str (str): Import path string

        Returns:
            str|None: Resolved path or None
        """
        return self._get_local_resolver().resolve_go(importing_file_rel_path, module_str)

    def _resolve_local_import_solidity(self, importing_file_rel_path, import_path_str):
        """
        Wrapper for Solidity local import resolution

        Args:
            importing_file_rel_path (str): Importing file path
            import_path_str (str): Import path string

        Returns:
            str|None: Resolved path or None
        """
        return self._get_local_resolver().resolve_solidity(importing_file_rel_path, import_path_str)

    def _get_hardhat_remappings(self):
        """
        Retrieve Hardhat remappings using helper module

        Returns:
            dict: Map of prefix to absolute path derived from Hardhat config
        """
        return solidity_meta.get_hardhat_remappings(self.repo_path, self.logger)

    def _resolve_version_conflict(self, version1, version2):
        """
        Delegate to manifests.resolve_version_conflict for tests

        Args:
            version1 (str): First version
            version2 (str): Second version

        Returns:
            str: Selected version according to project rules
        """
        return manifests.resolve_version_conflict(version1, version2)

    def _parse_semver(self, version_str):
        """
        Delegate to manifests.parse_semver for tests

        Args:
            version_str (str): Version string

        Returns:
            tuple|None: Parsed (major, minor, patch) or None
        """
        return manifests.parse_semver(version_str)

    def get_conflict_summary(self):
        """
        Return a summary of resolved package version conflicts

        Returns:
            dict: Conflict summary keyed by package
        """
        return manifests.get_conflict_summary(self.external_packages)
