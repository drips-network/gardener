"""
Import extraction helpers and LocalImportResolver for RepositoryAnalyzer

Provides a timeout context manager, the LocalImportResolver used for per‑language
local path resolution, and a file walker that extracts external and local imports
using tree‑sitter parsers
"""

import logging
import os
import signal
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

from gardener.common.defaults import ResourceLimits
from gardener.common.tsl import get_parser

JS_TS_SOURCE_EXTS = [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"]
JSONLIKE_EXTS = [".json"]


class TimeoutError(Exception):
    """
    Raised when parsing exceeds configured timeout
    """

    pass


@contextmanager
def timeout(seconds):
    """
    Timeout context manager

    Args:
        seconds (int): Maximum time to allow before raising TimeoutError

    Raises:
        TimeoutError: When the timeout expires during the protected block

    Returns:
        None
    """
    if hasattr(signal, "SIGALRM"):

        def handler(signum, frame):
            raise TimeoutError(f"Operation timed out after {seconds} seconds")

        previous = signal.signal(signal.SIGALRM, handler)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)
    else:
        logging.debug("Timeout protection not available on this platform")
        yield


class LocalImportResolver:
    """
    Encapsulates language-specific local import resolution logic

    Args:
        repo_path (str): Absolute path to the repository root
        source_files (dict): Map of repo‑relative paths to file metadata
        alias_resolver (UnifiedAliasResolver|None): JS/TS alias resolver if configured
        js_ts_base_url (str|None): baseUrl from ts/js config used by legacy resolver
        js_ts_path_aliases (dict): legacy paths map from ts/js config
        go_module_path (str|None): Module path from go.mod for absolute imports
        remappings (dict): Solidity remappings from remappings.txt
        hardhat_remappings (dict): Solidity remappings derived from Hardhat config
        solidity_src_path (str|None): Foundry src path when available
        logger (Logger|None): Optional logger for debug and warnings
    """

    def __init__(self, repo_path, source_files, alias_resolver, js_ts_base_url,
                 js_ts_path_aliases, go_module_path, remappings, hardhat_remappings,
                 solidity_src_path, logger):
        self.repo_path = repo_path
        self.source_files = source_files
        self.alias_resolver = alias_resolver
        self.js_ts_base_url = js_ts_base_url
        self.js_ts_path_aliases = js_ts_path_aliases or {}
        self.go_module_path = go_module_path
        self.remappings = remappings or {}
        self.hardhat_remappings = hardhat_remappings or {}
        self.solidity_src_path = solidity_src_path
        self.logger = logger

    # --- Python helpers ---
    def _py_is_invalid_blank_absolute(self, module_str, level):
        return not module_str and level == 0

    def _py_base_dir_for_relative(self, importing_file_rel_path, level):
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
        current_dir = self._py_base_dir_for_relative(importing_file_rel_path, level)
        if level > 0 and not module_str:
            if current_dir is None:
                return []
            return [str(Path(current_dir) / "__init__.py")]

        if level > 0:
            if current_dir is None:
                return []
            module_parts = module_str.split(".") if module_str else []
            import_path_base = (
                str(Path(current_dir).joinpath(*module_parts)) if module_parts else current_dir
            )
        else:
            module_parts = module_str.split(".") if module_str else []
            import_path_base = str(Path(*module_parts)) if module_parts else "."

        standard = str(Path(f"{import_path_base}.py"))
        init_file = str(Path(import_path_base) / "__init__.py")
        return [standard, init_file]

    def _py_first_existing(self, candidates):
        for path in candidates:
            normalized = str(Path(path))
            if normalized in self.source_files:
                return normalized
        return None

    def resolve_python(self, importing_file_rel_path, module_str, relative_level):
        """
        Resolve a Python import to a local file if possible

        Args:
            importing_file_rel_path (str): Importing file path relative to the repo
            module_str (str): Module name portion of the import
            relative_level (int): Dots count for relative imports (0 for absolute)

        Returns:
            str|None: Repo‑relative target path if resolved, otherwise None
        """
        if self._py_is_invalid_blank_absolute(module_str, relative_level):
            return None
        candidates = self._py_target_paths(importing_file_rel_path, module_str, relative_level)
        return self._py_first_existing(candidates)

    # --- JS/TS helpers ---
    def _join_norm(self, *parts):
        return str(Path(*parts)) if parts else "."

    def _rel_to_repo(self, abs_path):
        try:
            rel = str(Path(abs_path).relative_to(self.repo_path))
        except ValueError:
            rel = os.path.relpath(abs_path, self.repo_path)
        return str(Path(rel))

    def _source_has(self, rel_path):
        return rel_path in self.source_files

    def _disk_file_exists(self, rel_path):
        candidate = Path(self.repo_path) / rel_path
        return candidate.exists() and candidate.is_file()

    def _js_resolve_framework_package_alias(self, importing_file_rel_path, module_str):
        if not self.alias_resolver:
            return None
        package_name = self.alias_resolver.config.framework_resolver.get_package_name(module_str)
        if package_name:
            return f"__PACKAGE:{package_name}"
        return None

    def _js_extensions(self, module_str):
        """
        Return preferred JS/TS extensions to try for a given import

        Prefers the alias configuration when available, with a fallback to
        the local default set

        Args:
            module_str (str): Import string as written in source

        Returns:
            list: Ordered list of file extensions to try
        """
        if self.alias_resolver and getattr(self.alias_resolver, "config", None):
            try:
                return list(self.alias_resolver.config.get_all_extensions_for_module(module_str))
            except Exception:
                return list(JS_TS_SOURCE_EXTS)
        return list(JS_TS_SOURCE_EXTS)

    def _js_resolve_path_alias(self, importing_file_rel_path, module_str):
        if not self.alias_resolver:
            return None
        resolved = self.alias_resolver.resolve(importing_file_rel_path, module_str)
        if resolved:
            return resolved
        return None

    def _js_legacy_path_alias(self, importing_file_rel_path, module_str):
        if not self.js_ts_path_aliases:
            return None

        for alias_pattern, targets in self.js_ts_path_aliases.items():
            module_wildcard_part = None

            if "*" in alias_pattern:
                if alias_pattern.endswith("/*"):
                    prefix = alias_pattern[:-2]
                    if module_str.startswith(prefix + "/"):
                        module_wildcard_part = module_str[len(prefix) + 1 :]
                    elif module_str == prefix:
                        module_wildcard_part = ""
                    else:
                        continue
                elif alias_pattern.endswith("*"):
                    prefix = alias_pattern[:-1]
                    if module_str.startswith(prefix):
                        module_wildcard_part = module_str[len(prefix) :]
                    else:
                        continue
                else:
                    continue
            elif alias_pattern == module_str:
                module_wildcard_part = ""
            else:
                continue

            for target_template in targets:
                if "*" in target_template:
                    if target_template.endswith("/*"):
                        base_target = target_template[:-2]
                        resolved_segment = (
                            str(Path(base_target) / module_wildcard_part)
                            if module_wildcard_part
                            else base_target
                        )
                    elif target_template.endswith("*"):
                        base_target = target_template[:-1]
                        resolved_segment = base_target + module_wildcard_part
                    else:
                        if self.logger:
                            self.logger.warning(
                                f"Complex wildcard in target path template '{target_template}' not fully supported. Skipping"  # noqa
                            )
                        continue
                else:
                    resolved_segment = target_template

                if self.js_ts_base_url and self.js_ts_base_url != ".":
                    path_from_root = str(Path(self.js_ts_base_url) / resolved_segment)
                else:
                    path_from_root = resolved_segment

                path_from_root = str(Path(path_from_root))

                if path_from_root in self.source_files:
                    return path_from_root

                candidate_path = str(Path(self.repo_path) / path_from_root)
                if (
                    os.path.splitext(path_from_root)[1]
                    and Path(candidate_path).exists()
                    and Path(candidate_path).is_file()
                ):
                    self.source_files[path_from_root] = {
                        "absolute_path": candidate_path,
                        "language": "javascript",
                    }
                    return path_from_root

                for ext in JS_TS_SOURCE_EXTS:
                    target_with_ext = str(Path(f"{path_from_root}{ext}"))
                    if target_with_ext in self.source_files:
                        return target_with_ext

                has_known_extension = any(
                    path_from_root.endswith(ext) for ext in JS_TS_SOURCE_EXTS + JSONLIKE_EXTS
                )
                if not has_known_extension:
                    for ext in JS_TS_SOURCE_EXTS:
                        index_path = str(Path(path_from_root) / f"index{ext}")
                        index_path = str(Path(index_path))
                        if index_path in self.source_files:
                            return index_path

        return None

    def _js_resolve_relative_base(self, importing_file_rel_path, module_str):
        if not module_str.startswith("."):
            return None
        abs_dir = str((Path(self.repo_path) / importing_file_rel_path).parent)
        abs_target = str(Path(abs_dir) / module_str)
        normalized = str(Path(abs_target).resolve())
        return self._rel_to_repo(normalized)

    def _js_try_as_is_or_data_like(self, rel_base):
        if self._source_has(rel_base):
            return rel_base
        full_path = str(Path(self.repo_path) / rel_base)
        full_path_path = Path(full_path)
        if full_path_path.exists() and full_path_path.is_file():
            if rel_base.endswith(tuple(JSONLIKE_EXTS + [".cjs", ".mjs"])):
                self.source_files[rel_base] = {
                    "absolute_path": full_path,
                    "language": "json" if rel_base.endswith(".json") else "javascript",
                }
                return rel_base
        return None

    def _js_try_with_source_exts(self, rel_base, module_str):
        for ext in self._js_extensions(module_str):
            target = str(Path(f"{rel_base}{ext}"))
            if self._source_has(target):
                return target
        return None

    def _js_try_index_files(self, rel_base, module_str):
        if os.path.splitext(rel_base)[1]:
            return None
        for ext in self._js_extensions(module_str):
            candidate = str(Path(rel_base) / f"index{ext}")
            candidate = str(Path(candidate))
            if self._source_has(candidate):
                return candidate
        return None

    def resolve_js(self, importing_file_rel_path, module_str):
        """
        Resolve a JavaScript/TypeScript import to a local file when it is relative
        or matches configured alias rules

        Args:
            importing_file_rel_path (str): Importing file path relative to the repo
            module_str (str): Import string as written in source

        Returns:
            str|None: Repo‑relative target path or None when treated as external
        """
        if self.alias_resolver:
            pkg_marker = self._js_resolve_framework_package_alias(importing_file_rel_path, module_str)
            if pkg_marker:
                return pkg_marker
            resolved = self._js_resolve_path_alias(importing_file_rel_path, module_str)
            if resolved:
                return resolved
        elif self.js_ts_path_aliases:
            legacy = self._js_legacy_path_alias(importing_file_rel_path, module_str)
            if legacy:
                return legacy

        if not module_str.startswith("."):
            return None

        rel_base = self._js_resolve_relative_base(importing_file_rel_path, module_str)
        if rel_base is None:
            return None

        as_is = self._js_try_as_is_or_data_like(rel_base)
        if as_is:
            return as_is

        with_ext = self._js_try_with_source_exts(rel_base, module_str)
        if with_ext:
            return with_ext

        index_file = self._js_try_index_files(rel_base, module_str)
        if index_file:
            return index_file

        return None

    # --- Rust helpers ---
    def _rust_prefix_and_remainder(self, importing_file_rel_path, use_path_parts):
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
            current_dir = "src"
        else:
            current_dir = importing_dir
        if self.logger:
            self.logger.debug(
                f"[_resolve_local_import_rust] Path does not start with crate/self/super. "
                f"Treating as relative to '{current_dir}'. Path segments: {use_path_parts}"
            )
        return current_dir, first_part, use_path_parts

    def _rust_handle_empty_or_wildcard(self, first_part, importing_file_rel_path, current_dir, remainder):
        if not remainder:
            if first_part == "crate":
                lib_path = str(Path(current_dir) / "lib.rs")
                if lib_path in self.source_files:
                    return lib_path, True
                main_path = str(Path(current_dir) / "main.rs")
                if main_path in self.source_files:
                    return main_path, True
            return None, True

        if len(remainder) == 1 and remainder[0] == "*":
            if first_part == "crate":
                lib_path = str(Path(current_dir) / "lib.rs")
                if lib_path in self.source_files:
                    return lib_path, True
                main_path = str(Path(current_dir) / "main.rs")
                if main_path in self.source_files:
                    return main_path, True
                return None, True
            if first_part == "self":
                return importing_file_rel_path, True
            if first_part == "super":
                parent_dir = str(Path(importing_file_rel_path).parent)
                segment = Path(parent_dir).name
                target_rs = str(Path(current_dir) / f"{segment}.rs")
                if target_rs in self.source_files:
                    return target_rs, True
                target_mod = str(Path(current_dir) / segment / "mod.rs")
                if target_mod in self.source_files:
                    return target_mod, True
                return None, True

        return None, False

    def _rust_try_module_candidates(self, current_dir, remainder):
        for length in range(len(remainder), 0, -1):
            module_segments = remainder[:length]
            if not module_segments or module_segments[-1] == "*":
                continue
            path_parts_rs = [current_dir]
            if len(module_segments) > 1:
                path_parts_rs.extend(module_segments[:-1])
            path_parts_rs.append(f"{module_segments[-1]}.rs")
            candidate_rs = str(Path(*path_parts_rs)) if path_parts_rs else "."
            if candidate_rs in self.source_files:
                return candidate_rs
            path_parts_mod = [current_dir]
            path_parts_mod.extend(module_segments)
            path_parts_mod.append("mod.rs")
            candidate_mod = str(Path(*path_parts_mod)) if path_parts_mod else "."
            if candidate_mod in self.source_files:
                return candidate_mod
        return None

    def resolve_rust(self, importing_file_rel_path, use_path_parts):
        """
        Resolve a Rust `use` path to a module file when possible

        Args:
            importing_file_rel_path (str): Importing file path relative to the repo
            use_path_parts (list): Components of the `use` path split on '::'

        Returns:
            str|None: Repo‑relative module path if resolved, otherwise None
        """
        if not use_path_parts:
            return None

        current_dir, first_part, remainder = self._rust_prefix_and_remainder(
            importing_file_rel_path, use_path_parts
        )

        resolved, handled = self._rust_handle_empty_or_wildcard(
            first_part, importing_file_rel_path, current_dir, remainder
        )
        if handled:
            return resolved

        resolved = self._rust_try_module_candidates(current_dir, remainder)
        if resolved:
            return resolved

        if self.logger:
            self.logger.debug(
                f"[_resolve_local_import_rust] Could not resolve: {'::'.join(use_path_parts)} to a local module file after all checks."  # noqa
            )
        return None

    # --- Go helpers ---
    def _go_is_module_absolute(self, module_str):
        return bool(self.go_module_path and module_str.startswith(self.go_module_path))

    def _go_import_path_for_relative(self, importing_file_rel_path, module_str):
        abs_dir = str((Path(self.repo_path) / importing_file_rel_path).parent)
        abs_target = str((Path(abs_dir) / module_str).resolve())
        try:
            rel = str(Path(abs_target).relative_to(self.repo_path))
        except ValueError:
            rel = os.path.relpath(abs_target, self.repo_path)
        return str(Path(rel))

    def _go_candidate_files(self, import_path):
        package_dir = Path(import_path).name
        yield str(Path(f"{import_path}.go"))
        yield str(Path(import_path) / f"{package_dir}.go")

    def _go_find_single_go_in_dir(self, import_path):
        prefix = "" if import_path == "." else import_path + os.sep
        found = []
        for rel_path in self.source_files:
            if prefix == "":
                if os.sep not in rel_path and rel_path.endswith(".go"):
                    found.append(rel_path)
            elif rel_path.startswith(prefix) and rel_path.endswith(".go"):
                found.append(rel_path)
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            return found
        return None

    def resolve_go(self, importing_file_rel_path, module_str):
        """
        Resolve a Go import path to a single local `.go` source file when unambiguous

        Args:
            importing_file_rel_path (str): Importing file path relative to the repo
            module_str (str): Import path as written in source

        Returns:
            str|None: Repo‑relative `.go` file if uniquely determined, otherwise None
        """
        if not module_str.startswith("."):
            if self._go_is_module_absolute(module_str):
                relative_part = module_str[len(self.go_module_path) :].lstrip("/")
                import_path = str(Path(relative_part).resolve())
            else:
                return None
        else:
            import_path = self._go_import_path_for_relative(importing_file_rel_path, module_str)

        for candidate in self._go_candidate_files(import_path):
            normalized = str(Path(candidate))
            if normalized in self.source_files:
                return normalized

        single_or_list = self._go_find_single_go_in_dir(import_path)
        if isinstance(single_or_list, str):
            return single_or_list
        if isinstance(single_or_list, list) and self.logger:
            self.logger.warning(
                f"Go resolver: Found multiple .go files in directory '{import_path}' "
                f"for import '{module_str}' from '{importing_file_rel_path}': {single_or_list}. Resolution is ambiguous."  # noqa
            )
        return None

    # --- Solidity helpers ---
    def _solidity_try_remappings(self, import_path_str, remappings_dict):
        if not remappings_dict:
            return None
        for prefix, remapped_base in remappings_dict.items():
            if import_path_str.startswith(prefix):
                path_after = import_path_str[len(prefix) :]
                remapped_segment = str(Path(remapped_base) / path_after)
                full_path = str((Path(self.repo_path) / remapped_segment).resolve())
                try:
                    rel = str(Path(full_path).relative_to(self.repo_path))
                except ValueError:
                    rel = os.path.relpath(full_path, self.repo_path)
                rel = str(Path(rel))
                if rel in self.source_files:
                    return rel
        return None

    def _solidity_relative_target(self, importing_file_rel_path, import_path_str):
        base_dir = str(Path(importing_file_rel_path).parent)
        abs_base_dir = os.path.join(self.repo_path, base_dir)
        target_abs = os.path.normpath(os.path.join(abs_base_dir, import_path_str))
        try:
            target_rel = str(Path(target_abs).relative_to(self.repo_path))
        except ValueError:
            target_rel = os.path.relpath(target_abs, self.repo_path)
        target_rel = str(Path(target_rel))
        if not target_rel.endswith(".sol"):
            return None
        if target_rel in self.source_files:
            return target_rel
        if (
            self.solidity_src_path
            and import_path_str.startswith("../")
            and importing_file_rel_path.startswith(self.solidity_src_path + os.sep)
        ):
            remainder = import_path_str[3:]
            fallback = str(Path(self.solidity_src_path) / remainder)
            fallback = str(Path(fallback))
            if fallback in self.source_files:
                return fallback
        return None

    def resolve_solidity(self, importing_file_rel_path, import_path_str):
        """
        Resolve a Solidity import path via remappings or relative paths

        Args:
            importing_file_rel_path (str): Importing file path relative to the repo
            import_path_str (str): Import string as written in source

        Returns:
            str|None: Repo‑relative path if resolved, otherwise None
        """
        if not import_path_str.startswith("."):
            resolved = self._solidity_try_remappings(import_path_str, self.hardhat_remappings)
            if resolved:
                return resolved
            resolved = self._solidity_try_remappings(import_path_str, self.remappings)
            if resolved:
                return resolved
            return None

        target = self._solidity_relative_target(importing_file_rel_path, import_path_str)
        if target:
            return target
        return None


def extract_imports(source_files, language_handlers, repo_path, secure_file_ops, local_resolver, logger):
    """
    Extract imports from source files using provided handlers

    Args:
        source_files (dict): Map of repo‑relative paths to file metadata
        language_handlers (dict): Registered language handlers keyed by language name
        repo_path (str): Absolute repository root path
        secure_file_ops (SecureFileOps|None): Secure file operations or None
        local_resolver (LocalImportResolver): Resolver for local file imports
        logger (Logger|None): Optional logger for progress and warnings

    Returns:
        Tuple of (file_imports, local_imports_map, file_package_components)
    """
    file_imports = defaultdict(list)
    local_imports_map = defaultdict(list)
    file_package_components = defaultdict(list)

    processed_files = 0

    for rel_path, file_info in list(source_files.items()):
        abs_path = file_info["absolute_path"]
        language = file_info["language"]
        if not language or language not in language_handlers:
            continue
        handler = language_handlers[language]

        try:
            try:
                parser = get_parser(language)
            except Exception as exc:
                if logger:
                    logger.warning(f"Failed to get parser for {language}: {str(exc)}, skipping file {rel_path}")
                continue

            try:
                file_size = Path(abs_path).stat().st_size
                if file_size > ResourceLimits.MAX_FILE_SIZE:
                    if logger:
                        logger.warning(
                            f"Skipping {rel_path}: file size ({file_size / 1024 / 1024:.1f}MB) "
                            f"exceeds limit ({ResourceLimits.MAX_FILE_SIZE / 1024 / 1024}MB)"
                        )
                    continue
            except Exception as exc:
                if logger:
                    logger.warning(f"Could not check file size for {abs_path}: {exc}")

            try:
                if secure_file_ops:
                    code = secure_file_ops.read_file(rel_path, encoding="utf-8")
                else:
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as handle:
                        code = handle.read()
            except Exception as exc:
                if logger:
                    logger.error(f"Could not read file {abs_path}: {exc}, skipping")
                continue

            if logger:
                logger.debug(f"Parsing {rel_path} ({len(code)} bytes)")

            try:
                with timeout(ResourceLimits.PARSE_TIMEOUT):
                    tree = parser.parse(bytes(code, "utf-8"))
            except TimeoutError as exc:
                if logger:
                    logger.warning(f"Parsing timed out for {rel_path}: {str(exc)}, skipping")
                continue
            except Exception as exc:
                if logger:
                    logger.warning(f"Failed to parse {rel_path}: {str(exc)}, skipping")
                continue

            resolver_func = None
            if language == "python":
                resolver_func = local_resolver.resolve_python
            elif language in ["javascript", "typescript"]:
                resolver_func = local_resolver.resolve_js
            elif language == "rust":
                resolver_func = local_resolver.resolve_rust
            elif language == "go":
                resolver_func = local_resolver.resolve_go
            elif language == "solidity":
                resolver_func = local_resolver.resolve_solidity

            try:
                external_imports, local_imports = handler.extract_imports(
                    tree.root_node,
                    rel_path,
                    file_package_components,
                    resolver_func,
                    logger=logger,
                )

                if external_imports:
                    file_imports[rel_path] = external_imports
                if local_imports:
                    local_imports_map[rel_path] = local_imports

                processed_files += 1
            except Exception as exc:
                if logger:
                    logger.warning(f"Error extracting imports from {rel_path}: {str(exc)}")

        except Exception as exc:
            if logger:
                logger.exception(f"Unexpected error processing file {rel_path}")

    if logger:
        logger.info(f"... Processed {processed_files}/{len(source_files)} files for imports")

    return file_imports, local_imports_map, file_package_components
