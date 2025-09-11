"""
Alias configuration and resolution utilities

Provides a single, consistent mechanism to resolve JavaScript/TypeScript import aliases from:
- Custom rules (highest priority)
- TypeScript/JavaScript `paths` in tsconfig.json/jsconfig.json
- Framework-specific conventions (e.g., SvelteKit `$lib/`)

Only non-relative imports are considered here (e.g., `@utils/helpers`, `$lib/stores`).
Relative imports like `./x` or `../x` are intentionally ignored and handled elsewhere

Notes:
- All returned paths are repository-relative and normalized (no `..` segments)
- File existence checks are performed against the provided `source_files` map
- Framework aliases that resolve to external packages are treated as external and return None
"""

# Alias configuration tooling

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

from gardener.common.framework_config import FrameworkAliasConfig, FrameworkAliasResolver


@dataclass
class AliasRule:
    """
    Represents a single alias mapping rule

    Attributes:
        pattern: The alias pattern (e.g., '@/*', '$lib/*', 'utils')
        target: The target path(s) to resolve to (string or list)
        priority: Resolution priority (higher numbers are tried first)
        description: Human-readable description of the rule intent
    """

    pattern: str
    target: Union[str, List[str]]
    priority: int = 0
    description: str = ""

    def get_targets(self):
        """
        Get target paths as a list

        Returns:
            List of target paths
        """
        if isinstance(self.target, str):
            return [self.target]
        return self.target


@dataclass
class AliasConfiguration:
    """
    Complete alias configuration for a project

    Combines:
    - TypeScript/JavaScript path aliases from config files
    - Framework-specific aliases
    - Custom alias rules

    The configuration is read-only during resolution and can be composed via
    `merge_with` to aggregate multiple sources of alias definitions.
    """

    # TypeScript/JavaScript config-based aliases
    base_url: Optional[str] = None
    ts_js_paths: Dict[str, List[str]] = field(default_factory=dict)

    # Framework aliases
    framework_resolver: FrameworkAliasResolver = field(default_factory=FrameworkAliasResolver)

    # Custom alias rules
    custom_rules: List[AliasRule] = field(default_factory=list)

    # File extensions to try
    extensions_to_try: List[str] = field(
        default_factory=lambda: [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json"]
    )

    def add_custom_rule(self, pattern, target, priority=0, description=""):
        """
        Add a custom alias rule

        Args:
            pattern (str): The alias pattern (supports `*` wildcards)
            target (str or list): The target path(s) to resolve to (list is tried in order)
            priority (int): Resolution priority (higher numbers are tried first)
            description (str): Human-readable description
        """
        rule = AliasRule(pattern, target, priority, description)
        self.custom_rules.append(rule)
        # Keep rules sorted by priority (descending)
        self.custom_rules.sort(key=lambda r: r.priority, reverse=True)

    def add_framework_config(self, name, config):
        """
        Add a framework configuration

        Args:
            name (str): Framework name
            config (FrameworkAliasConfig): FrameworkAliasConfig instance
        """
        self.framework_resolver.add_framework_config(name, config)

    def get_all_extensions(self, module_str):
        """
        Get the complete set of file extensions to try for an import

        Combines default extensions from `extensions_to_try` with any framework-specific
        extensions inferred from the original `module_str` (for example, `.svelte` for
        SvelteKit `$lib/...` imports).

        Args:
            module_str (str): Module string to check for framework-specific extensions

        Returns:
            List of file extensions to try, ordered by priority
        """
        extensions = self.extensions_to_try.copy()

        extra_extensions = self.framework_resolver.get_extra_extensions(module_str)
        for ext in extra_extensions:
            if ext not in extensions:
                extensions.append(ext)

        return extensions

    def get_all_extensions_for_module(self, module_str):
        """
        Clearer alias of `get_all_extensions` for readability

        Args:
            module_str (str): The original import string

        Returns:
            List of file extensions to try
        """
        return self.get_all_extensions(module_str)

    @classmethod
    def from_ts_js_config(cls, config_path, logger=None, secure_file_ops=None):
        """
        Create configuration from tsconfig.json or jsconfig.json

        The loader is resilient to BOM-encoded JSON (uses `utf-8-sig`) and can optionally
        use `secure_file_ops` to read from untrusted paths.

        Args:
            config_path (str): Path to the config file
            logger (Logger): Optional logger for error reporting
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations

        Returns:
            AliasConfiguration instance
        """
        config = cls()

        try:
            if secure_file_ops:
                try:
                    data = secure_file_ops.read_json(config_path)
                except Exception as e:
                    # Try with encoding if JSON read fails
                    content = secure_file_ops.read_file(config_path, encoding="utf-8-sig")
                    data = json.loads(content)
            else:
                with open(config_path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)

            compiler_options = data.get("compilerOptions", {})

            base_url = compiler_options.get("baseUrl")
            if base_url and isinstance(base_url, str):
                config.base_url = base_url

            paths = compiler_options.get("paths")
            if paths and isinstance(paths, dict):
                config.ts_js_paths = paths

        except Exception as e:
            if logger:
                logger.error(f"Failed to load alias config from {config_path}: {e}")

        return config

    def merge_with(self, other):
        """
        Merge another configuration into this one

        Precedence and merge rules:
        - `base_url`: keep current if already set; otherwise adopt from `other`
        - `ts_js_paths`: add patterns from `other` when not already present
        - `custom_rules`: concatenate then sort by `priority` descending
        - `extensions_to_try`: union while preserving order

        Args:
            other (AliasConfiguration): Another AliasConfiguration to merge
        """
        # Merge TypeScript/JavaScript paths
        if other.base_url and not self.base_url:
            self.base_url = other.base_url

        for pattern, targets in other.ts_js_paths.items():
            if pattern not in self.ts_js_paths:
                self.ts_js_paths[pattern] = targets

        # Merge custom rules
        self.custom_rules.extend(other.custom_rules)
        self.custom_rules.sort(key=lambda r: r.priority, reverse=True)

        # Extensions
        for ext in other.extensions_to_try:
            if ext not in self.extensions_to_try:
                self.extensions_to_try.append(ext)


class UnifiedAliasResolver:
    """
    Unified resolver that handles all types of aliases

    Resolution order:
    1. Custom rules (by priority)
    2. TypeScript/JavaScript path aliases
    3. Framework-specific aliases

    Returns repository-relative, normalized paths or None when no match is found or the
    import is considered external (e.g., framework alias that maps to a package).
    """

    def __init__(self, config, repo_path, source_files, logger=None):
        """
        Initialize a resolver instance

        Args:
            config (AliasConfiguration): Alias configuration
            repo_path (str): Repository root path
            source_files (dict): Map of repo-relative paths to absolute paths
            logger (Logger): Optional logger (unused in core logic but available for debug)
        """
        self.config = config
        self.repo_path = repo_path
        self.source_files = source_files
        self.logger = logger

    def resolve(self, importing_file, module_str):
        """
        Resolve a non-relative import to a local file path

        This resolver ignores relative imports (those starting with `.`). For matching
        aliases, resolution attempts are performed in the documented order. The final
        result is a repo-relative, normalized path string.

        Args:
            importing_file (str): The file doing the import (relative path)
            module_str (str): The module string to resolve

        Returns:
            Repo-relative normalized path if found, None otherwise
        """
        if module_str.startswith("."):
            return None

        # Try custom rules first
        resolved = self._try_custom_rules(module_str)
        if resolved:
            return resolved

        # Try TypeScript/JavaScript path aliases
        resolved = self._try_ts_js_aliases(module_str)
        if resolved:
            return resolved

        # Try framework aliases
        resolved = self._try_framework_aliases(module_str)
        if resolved:
            return resolved

        return None

    def _try_custom_rules(self, module_str):
        """
        Try to resolve using custom alias rules

        Each rule can specify one or more targets; targets are tried in order until
        a matching file is found.

        Args:
            module_str (str): Module string to resolve

        Returns:
            Resolved path if found, None otherwise
        """
        for rule in self.config.custom_rules:
            if self._matches_pattern(module_str, rule.pattern):
                for target in rule.get_targets():
                    resolved = self._resolve_pattern_match(module_str, rule.pattern, target)
                    if resolved:
                        found = self._find_file_with_extensions(resolved)
                        if found:
                            return found
        return None

    def _try_ts_js_aliases(self, module_str):
        """
        Try to resolve using TypeScript/JavaScript aliases

        Applies `base_url` when present before file lookups.

        Args:
            module_str (str): Module string to resolve

        Returns:
            Resolved path if found, None otherwise
        """
        for pattern, targets in self.config.ts_js_paths.items():
            if self._matches_pattern(module_str, pattern):
                for target in targets:
                    resolved = self._resolve_pattern_match(module_str, pattern, target)
                    if resolved:
                        # Apply baseUrl if present
                        if self.config.base_url:
                            resolved = os.path.join(self.config.base_url, resolved)
                        found = self._find_file_with_extensions(resolved)
                        if found:
                            return found
        return None

    def _try_framework_aliases(self, module_str):
        """
        Try to resolve using framework-specific aliases

        If a framework alias indicates an external package (e.g., `$app`), this method
        returns None so that the import is treated as a package rather than a local file.

        Args:
            module_str (str): Module string to resolve

        Returns:
            Resolved path if found, None otherwise
        """
        # First check if this alias resolves to a package
        package_name = self.config.framework_resolver.get_package_name(module_str)
        if package_name:
            return None

        # Otherwise try to resolve to a local file
        resolved_path = self.config.framework_resolver.resolve_framework_alias(module_str)
        if resolved_path:
            # Need to pass module_str for framework-specific extensions
            found = self._find_file_with_extensions_for_module(resolved_path, module_str)
            if found:
                return found
        return None

    def _matches_pattern(self, module_str, pattern):
        """
        Check if a module string matches an alias pattern

        Supported pattern forms:
        - Exact string (no `*`): matches only the exact module string
        - `prefix*`: matches any string starting with `prefix`
        - `prefix/*`: matches `prefix` and any nested path under it

        Examples:
            _matches_pattern('@components/Button', '@components/*') -> True
            _matches_pattern('@components', '@components/*') -> True
            _matches_pattern('@utils', '@utils') -> True
            _matches_pattern('@utils/helpers', '@utils') -> False

        Args:
            module_str (str): Module string to check
            pattern (str): Pattern to match against

        Returns:
            True if matches, False otherwise
        """
        if "*" in pattern:
            if pattern.endswith("/*"):
                prefix = pattern[:-2]
                return module_str.startswith(prefix + "/") or module_str == prefix
            elif pattern.endswith("*"):
                prefix = pattern[:-1]
                return module_str.startswith(prefix)
        else:
            # Exact match
            return module_str == pattern
        return False

    def _resolve_pattern_match(self, module_str, pattern, target):
        """
        Resolve a pattern match to a target path

        Captures the wildcard portion of `module_str` relative to `pattern` and applies it
        to `target` (which may or may not include a wildcard).

        Rules:
        - If `pattern` has no `*`, return `target` as-is
        - If `pattern` ends with `/*`, capture the subpath after the prefix (or empty)
        - If `pattern` ends with `*`, capture the remaining suffix after the prefix
        - If `target` ends with `/*`, join base with captured part
        - If `target` ends with `*`, concatenate base with captured part
        - If `target` has no `*`, append captured part as a path element (when present)

        Examples:
            ('@components/Button', '@components/*', 'components/*') -> 'components/Button'
            ('@utils/helpers', '@utils/*', 'utils') -> 'utils/helpers'
            ('@api', '@api', 'api/index.ts') -> 'api/index.ts'

        Args:
            module_str (str): Module string to resolve
            pattern (str): Pattern that matched
            target (str): Target path pattern

        Returns:
            Resolved path if successful, None otherwise
        """
        if "*" not in pattern:
            # Direct replacement
            return target

        wildcard_part = ""
        if pattern.endswith("/*"):
            prefix = pattern[:-2]
            if module_str.startswith(prefix + "/"):
                wildcard_part = module_str[len(prefix) + 1 :]
            elif module_str == prefix:
                wildcard_part = ""
        elif pattern.endswith("*"):
            prefix = pattern[:-1]
            wildcard_part = module_str[len(prefix) :]

        # Apply to target
        if "*" in target:
            if target.endswith("/*"):
                base = target[:-2]
                return os.path.join(base, wildcard_part) if wildcard_part else base
            elif target.endswith("*"):
                base = target[:-1]
                return base + wildcard_part
        else:
            # No wildcard in target, append the wildcard part
            return os.path.join(target, wildcard_part) if wildcard_part else target

        return None

    def _find_file_with_extensions(self, path):
        """
        Try to find a file with various extensions

        Args:
            path: Path to check for extensions

        Returns:
            Found file path if exists, None otherwise
        """
        return self._find_file_with_extensions_for_module(path, path)

    def _find_file_with_extensions_for_module(self, path, module_str):
        """
        Try to find a file with various extensions, considering the original module string

        Search order:
        1. Exact path (already in `source_files` or exists on disk)
        2. Path with each extension from `config.get_all_extensions(module_str)`
        3. Directory index files: `path/index{ext}` for each extension when `path` has no ext

        Args:
            path (str): Path to check for extensions
            module_str (str): Original module string for framework-specific extensions

        Returns:
            Found file path if exists, None otherwise
        """
        normalized_path = str(Path(os.path.normpath(path)))

        if normalized_path in self.source_files:
            return normalized_path

        full_path = os.path.join(self.repo_path, normalized_path)
        if os.path.exists(full_path) and os.path.isfile(full_path):
            return normalized_path

        extensions = self.config.get_all_extensions(module_str)

        # Try with extensions
        for ext in extensions:
            path_with_ext = f"{normalized_path}{ext}"
            if path_with_ext in self.source_files:
                return path_with_ext

        # Try index files
        if not os.path.splitext(normalized_path)[1]:
            for ext in extensions:
                index_path = os.path.join(normalized_path, f"index{ext}")
                index_path_normalized = str(Path(index_path))
                if index_path_normalized in self.source_files:
                    return index_path_normalized

        return None

    def _try_tsconfig_path_aliases(self, module_str):
        """
        Clearer alias of `_try_ts_js_aliases` for readability

        Args:
            module_str (str): Module string to resolve

        Returns:
            Resolved path if found, None otherwise
        """
        return self._try_ts_js_aliases(module_str)

    def _try_framework_conventional_aliases(self, module_str):
        """
        Clearer alias of `_try_framework_aliases` for readability

        Args:
            module_str (str): Module string to resolve

        Returns:
            Resolved path if found, None otherwise
        """
        return self._try_framework_aliases(module_str)

    def _match_alias_pattern(self, module_str, pattern):
        """
        Clearer alias of `_matches_pattern` for readability

        Args:
            module_str (str): Module string to check
            pattern (str): Pattern to match against

        Returns:
            True if matches, False otherwise
        """
        return self._matches_pattern(module_str, pattern)

    def _apply_pattern_to_target(self, module_str, pattern, target):
        """
        Clearer alias of `_resolve_pattern_match` for readability

        Args:
            module_str (str): Module string to resolve
            pattern (str): Pattern that matched
            target (str): Target path pattern

        Returns:
            Resolved path if successful, None otherwise
        """
        return self._resolve_pattern_match(module_str, pattern, target)

    def _find_candidate_file(self, path):
        """
        Clearer alias of `_find_file_with_extensions` for readability

        Args:
            path (str): Path to check for extensions

        Returns:
            Found file path if exists, None otherwise
        """
        return self._find_file_with_extensions(path)

    def _find_candidate_file_for_module(self, path, module_str):
        """
        Clearer alias of `_find_file_with_extensions_for_module` for readability

        Args:
            path (str): Path to check for extensions
            module_str (str): Original module string

        Returns:
            Found file path if exists, None otherwise
        """
        return self._find_file_with_extensions_for_module(path, module_str)
