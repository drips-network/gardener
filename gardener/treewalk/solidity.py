"""
Solidity-specific visitors and handlers
"""

import os
import re

from gardener.common.secure_file_ops import FileOperationError
from gardener.common.utils import Logger
from gardener.treewalk.base import LanguageHandler, TreeVisitor
from gardener.treewalk.javascript import JavaScriptLanguageHandler

# Module-level logger instance
logger = Logger(verbose=False)  # Will be configured by the caller


class SolidityImportVisitor(TreeVisitor):
    """
    Visitor for extracting imports from Solidity tree using the correct node types
    """

    def __init__(self, rel_path, file_components_dict, local_resolver_func, logger=None):
        super().__init__()
        self.rel_path = rel_path
        self.file_components_dict = file_components_dict
        self.imports = []  # External imports
        self.local_imports = []  # Resolved local import paths
        self._resolve_local = local_resolver_func  # Store resolver
        self.logger = logger

    def visit_import_directive(self, node):
        """
        Process Solidity import directives to extract dependencies

        Handles various Solidity import forms including simple imports, aliased imports,
        and selective imports with symbols. Processes both local imports (relative paths)
        and external imports (from node_modules or remappings). Applies remapping rules
        from remappings.txt or Hardhat configuration

        Args:
            node (object): AST node representing a Solidity import directive
        """
        import_path = self._parse_import_source(node)
        if not import_path:
            return

        has_symbols, import_clause_node = self._detect_symbols_and_clause(node)
        alias_name = self._parse_top_level_alias(node)
        package_name_for_display = self._package_name_for_display(import_path)

        symbols = self._collect_symbols(import_clause_node, node, has_symbols)
        imported_symbols_str = self._symbols_to_str(symbols)

        # Generate component string according to specification
        final_component_display_string = self._generate_component_string(
            import_path=import_path,
            package_name=package_name_for_display,
            alias_name=alias_name,
            symbols_str=imported_symbols_str,
        )

        self._resolve_and_record(import_path, final_component_display_string, package_name_for_display)

    def _parse_import_source(self, node):
        """
        Return decoded import path string or None if not a string literal
        """
        source_node = node.child_by_field_name("source")
        if source_node and source_node.type == "string":
            return source_node.text.decode("utf-8").strip("\"'")
        return None

    def _detect_symbols_and_clause(self, node):
        """
        Return (has_symbols: bool, import_clause_node or None)
        """
        has_symbols = any(child.type == "{" for child in node.children)
        import_clause_node = None
        if not has_symbols:
            for child_node in node.children:
                if child_node.type == "import_clause":
                    import_clause_node = child_node
                    break
        return has_symbols, import_clause_node

    def _parse_top_level_alias(self, node):
        """
        Return alias name from 'import "path" as Alias;' or None
        """
        alias_node = node.child_by_field_name("alias")
        if alias_node:
            return alias_node.text.decode("utf-8")
        return None

    def _package_name_for_display(self, import_path):
        """
        Return normalized external package name (or None for local) using
        SolidityLanguageHandler().normalize_package_name
        """
        if not import_path.startswith("."):
            return SolidityLanguageHandler().normalize_package_name(import_path)
        return None

    def _collect_symbols(self, import_clause_node, node, has_symbols):
        """
        Return a list of symbol strings; supports both 'import_clause' node path and '{ ... }' scanning
        """
        imported_symbols_list = []
        if import_clause_node:
            for named_child_in_clause in import_clause_node.named_children:
                child_type = named_child_in_clause.type
                child_text = named_child_in_clause.text.decode("utf-8")
                if child_type == "import_alias":
                    name_node = named_child_in_clause.child_by_field_name("name")
                    alias_node_in_symbol_clause = named_child_in_clause.child_by_field_name("alias")
                    if name_node and name_node.type == "identifier":
                        symbol_text = name_node.text.decode("utf-8")
                        if alias_node_in_symbol_clause and alias_node_in_symbol_clause.type == "identifier":
                            symbol_text += f" as {alias_node_in_symbol_clause.text.decode('utf-8')}"
                        imported_symbols_list.append(symbol_text)
                elif child_type == "identifier":
                    imported_symbols_list.append(child_text)
        elif has_symbols:
            inside_braces = False
            for child in node.children:
                if child.type == "{":
                    inside_braces = True
                elif child.type == "}":
                    inside_braces = False
                elif inside_braces and child.type == "identifier":
                    imported_symbols_list.append(child.text.decode("utf-8"))
        return imported_symbols_list

    def _symbols_to_str(self, symbols):
        """
        Return the exact formatted symbol suffix: '' or ' { A, B }'
        """
        if not symbols:
            return ""
        return f" {{ {', '.join(sorted(list(set(symbols))))} }}"

    def _resolve_and_record(self, import_path, component_display, package_name_for_display):
        """
        Apply identical logic currently in visit_import_directive to:
        - resolve with self._resolve_local
        - decide component key (remap vs local)
        - mutate imports/local_imports and file_components_dict identically to current behavior
        """
        resolved_local_path = self._resolve_local(self.rel_path, import_path)
        component_key = None
        if resolved_local_path:
            if resolved_local_path not in self.local_imports:
                self.local_imports.append(resolved_local_path)
            was_remapped = not import_path.startswith(".")
            if was_remapped:
                package_name_for_remapped = package_name_for_display
                if package_name_for_remapped:
                    component_key = package_name_for_remapped
                    if package_name_for_remapped not in self.imports:
                        self.imports.append(package_name_for_remapped)
                else:
                    component_key = resolved_local_path
            else:
                component_key = resolved_local_path

            if component_key:
                self.file_components_dict.setdefault(self.rel_path, []).append((component_key, component_display))
        elif not import_path.startswith("."):
            package_name = package_name_for_display
            if package_name:
                if package_name not in self.imports:
                    self.imports.append(package_name)
                self.file_components_dict.setdefault(self.rel_path, []).append((package_name, component_display))

    def _generate_component_string(self, import_path, package_name, alias_name, symbols_str):
        """
        Generate component string based on formal specification. This implementation
        is additive to correctly handle all combinations of symbols and aliases

        Component strings uniquely identify imported components with format:
        - External: <package>.<normalized_path>[symbols][alias]
        - Local: <original_import_path>[symbols][alias]

        Args:
            import_path (str): The import path from the source code
            package_name (str): Resolved package name for external imports, None for local
            alias_name (str): Alias if present (e.g., "MyToken" from "as MyToken")
            symbols_str (str): Formatted symbol list (e.g., " { ERC20, IERC20 }")

        Returns:
            Component string following specification format
        """
        if self._is_local_import(import_path):
            # Local imports preserve original path exactly
            base_component = import_path
        else:
            # External imports get normalized
            base_component = self._format_external_component(import_path, package_name, symbols_str, alias_name)

        final_string = base_component
        if symbols_str:
            final_string += symbols_str

        if alias_name:
            # Note: The spec implies whole-file aliasing, which typically does not
            # occur with symbol imports. This handles it robustly regardless
            final_string += f" as {alias_name}"

        return final_string

    def _is_local_import(self, import_path):
        """Check if import is local (starts with . or ..)"""
        return import_path.startswith(".")

    def _format_external_component(self, import_path, package_name, symbols_str, alias_name):
        """
        Format external package component according to specification

        Returns:
            Formatted string like "package.normalized_path"
        """
        if not package_name:
            # Direct file import without package context
            if import_path.endswith(".sol"):
                if not alias_name or symbols_str:
                    return import_path[:-4]
            return import_path

        # Normalize the path
        normalized_path = self._normalize_import_path(import_path, package_name)

        if normalized_path.endswith(".sol"):
            if not alias_name or symbols_str:
                normalized_path = normalized_path[:-4]

        return f"{package_name}.{normalized_path}"

    def _normalize_import_path(self, path, package_name):
        """
        Normalize import path according to specification rules

        1. Remove package prefix if present
        2. Remove common directory prefixes in order
        3. Return normalized path
        """
        normalized = path

        # Step 1: Remove package prefix
        if normalized.startswith(package_name + "/"):
            normalized = normalized[len(package_name) + 1 :]

        # Step 2: Remove common prefixes in order
        prefixes_to_strip = [f"lib/{package_name}/", f"src/{package_name}/", "src/", "lib/"]

        for prefix in prefixes_to_strip:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break  # Only remove first matching prefix

        return normalized


class SolidityLanguageHandler(LanguageHandler):
    """
    Handler for Solidity language
    """

    def __init__(self, logger=None):
        """
        Args:
            logger (Logger): Optional logger instance
        """
        self.logger = logger

    def get_manifest_files(self):
        """
        Get the manifest files for Solidity

        Returns:
            List of manifest filenames
        """
        # Solidity projects often use npm for dependencies
        return ["package.json", "hardhat.config.js", "hardhat.config.ts", "foundry.toml"]

    def get_file_extensions(self):
        """
        Get the file extensions for Solidity

        Returns:
            List of file extensions with dot prefix
        """
        return [".sol"]

    def process_manifest(self, file_path, packages_dict, secure_file_ops=None):
        """
        Process manifest files for Solidity projects

        Args:
            file_path (str): Path to the manifest file
            packages_dict (dict): Dictionary to update with package information
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations

        Returns:
            Updated packages_dict
        """
        # For Solidity, we often use npm packages
        # Reuse JavaScript manifest processing for package.json
        basename = os.path.basename(file_path)

        if basename == "package.json":
            # Delegate to JavaScript handler for package.json
            js_handler = JavaScriptLanguageHandler()
            return js_handler.process_manifest(file_path, packages_dict, secure_file_ops)
        elif basename == "foundry.toml":
            # Basic parsing for foundry.toml dependencies
            try:
                content = self.read_file_content(file_path, secure_file_ops)
                # Look for dependencies under [dependencies] or similar sections
                deps_pattern = r"\[dependencies\](.*?)(\n\[|\Z)"
                match = re.search(deps_pattern, content, re.DOTALL | re.IGNORECASE)
                if match:
                    deps_section = match.group(1)
                    # Extract lines like 'name = 'github_user/repo@tag''
                    lib_pattern = r'([a-zA-Z0-9_-]+)\s*=\s*[\'"]([^\'"]+)[\'"]'
                    libs = re.findall(lib_pattern, deps_section)
                    for name, source in libs:
                        # Try to guess package name from source (e.g., github url)
                        # This is heuristic
                        if "github.com" in source:
                            parts = source.split("/")
                            if len(parts) >= 2:
                                pkg_name = f"{parts[-2]}/{parts[-1].split('@')[0]}"
                                packages_dict[pkg_name] = {"ecosystem": "solidity", "source": source}
                        else:  # Assume name is package name
                            packages_dict[name] = {"ecosystem": "solidity", "source": source}
            except FileOperationError as e:
                logger.error(f"Failed to read foundry.toml at {file_path}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error processing foundry.toml at {file_path}", exception=e)

        # hardhat.config files don't typically list dependencies directly

        # Attempt to get repo_path and logger from the analyzer instance if available
        # This assumes the handler instance is used within a RepositoryAnalyzer context
        repo_path_base = getattr(self, "repo_path", os.path.dirname(file_path))  # Fallback to manifest dir
        logger = getattr(self, "logger", None)

        if secure_file_ops:
            remappings_path = secure_file_ops.join_paths(repo_path_base, "remappings.txt")
            if secure_file_ops.exists(remappings_path):
                if logger:
                    logger.debug(f"Processing remappings file: {remappings_path}")
                try:
                    content = secure_file_ops.read_file(remappings_path)
                    for line in content.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        # Simple parsing: assume format like 'name=path' or 'prefix/=path/'
                        parts = line.split("=")
                        if len(parts) == 2:
                            name = parts[0].strip().rstrip("/")
                            # Heuristic: If it doesn't look like a relative path, consider it a package
                            # Also check if it contains common lib indicators like
                            # 'node_modules' or 'lib' in its path part
                            path_part = parts[1].strip()
                            is_likely_package = (
                                name
                                and not name.startswith("./")
                                and not name.startswith("../")
                                and (
                                    "node_modules" in path_part or "lib/" in path_part or not path_part.startswith("./")
                                )
                            )
                            if is_likely_package:
                                # Normalize and canonicalize common remapping aliases
                                normalized_name = name
                                if "openzeppelin-contracts" in name:
                                    normalized_name = "openzeppelin-contracts"
                                elif "forge-std" in name:
                                    normalized_name = "forge-std"
                                # Canonicalize alias-like names to the canonical dist
                                if normalized_name in ("@openzeppelin", "@openzeppelin/"):
                                    normalized_name = "@openzeppelin/contracts"
                                if normalized_name == "openzeppelin-contracts":
                                    normalized_name = "@openzeppelin/contracts"

                                # Avoid adding duplicates if already found via package.json or other means
                                if normalized_name not in packages_dict:
                                    if logger:
                                        logger.debug(
                                            f"Found potential package '{normalized_name}' "
                                            f"from remappings.txt line: '{line}'"
                                        )
                                    # Mark ecosystem as solidity, source indicates it came from remappings
                                    packages_dict[normalized_name] = {
                                        "ecosystem": "solidity",
                                        "source": f"remappings: {line}",
                                    }
                except FileOperationError as e:
                    if logger:
                        logger.warning(f"Failed to read remappings.txt at {remappings_path}: {e}")
                except Exception as e:
                    if logger:
                        logger.warning(f"Unexpected error processing remappings.txt at {remappings_path}: {e}")
        else:
            remappings_path = os.path.join(repo_path_base, "remappings.txt")
            if os.path.exists(remappings_path):
                if logger:
                    logger.debug(f"Processing remappings file: {remappings_path}")
                try:
                    with open(remappings_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            # Simple parsing: assume format like 'name=path' or 'prefix/=path/'
                            parts = line.split("=")
                            if len(parts) == 2:
                                name = parts[0].strip().rstrip("/")
                                # Heuristic: If it doesn't look like a relative path, consider it a package
                                # Also check if it contains common lib indicators like
                                # 'node_modules' or 'lib' in its path part
                                path_part = parts[1].strip()
                                is_likely_package = (
                                    name
                                    and not name.startswith(".")
                                    and ("node_modules/" in path_part or "lib/" in path_part)
                                )

                                if is_likely_package:
                                    # Normalize and canonicalize common remapping aliases
                                    normalized_name = name
                                    if "openzeppelin-contracts" in name:
                                        normalized_name = "openzeppelin-contracts"
                                    elif "forge-std" in name:
                                        normalized_name = "forge-std"
                                    # Canonicalize alias-like names to the canonical dist
                                    if normalized_name in ("@openzeppelin", "@openzeppelin/"):
                                        normalized_name = "@openzeppelin/contracts"
                                    if normalized_name == "openzeppelin-contracts":
                                        normalized_name = "@openzeppelin/contracts"

                                    # Avoid adding duplicates if already found via package.json or other means
                                    if normalized_name not in packages_dict:
                                        if logger:
                                            logger.debug(
                                                f"Found potential package '{normalized_name}' "
                                                f"from remappings.txt line: '{line}'"
                                            )
                                        # Mark ecosystem as solidity, source indicates it came from remappings
                                        packages_dict[normalized_name] = {
                                            "ecosystem": "solidity",
                                            "source": f"remappings: {line}",
                                        }
                except FileOperationError as e:
                    if logger:
                        logger.warning(f"Failed to read remappings.txt at {remappings_path}: {e}")
                except Exception as e:
                    if logger:
                        logger.warning(f"Unexpected error processing remappings.txt at {remappings_path}: {e}")

        return packages_dict

    def normalize_package_name(self, package_path):
        """
        Handle Solidity imports like '@openzeppelin/contracts/...' or 'hardhat/console.sol'

        Args:
            package_path (str): The raw import path

        Returns:
            Normalized package name or None if it's a relative import
        """
        if package_path.startswith("."):
            return None  # Relative import

        if package_path.startswith("@"):
            parts = package_path.split("/")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"
            else:
                return package_path  # Should not happen often
        else:
            # For non-scoped paths like 'hardhat/console.sol' or 'lib/solmate/src/...'
            parts = package_path.split("/")
            if parts[0] == "lib" and len(parts) > 1:
                # If it starts with 'lib/' and has something after, take the second part
                # e.g., 'lib/solmate/...' -> 'solmate'
                return parts[1]
            # Otherwise, return the first part as before
            return parts[0]

    def extract_imports(self, tree_node, rel_path, file_components_dict, local_resolver_func, logger=None):
        """
        Extract external package imports and resolved local imports from a Solidity source file

        Uses the SolidityImportVisitor based on the grammar definition

        Args:
            tree_node (object): Tree-sitter node
            rel_path (str): Relative path of the file
            file_components_dict (dict): Dictionary to track imported external components
            local_resolver_func (callable): Function to resolve local Solidity import paths
            logger (Logger): Optional logger instance for debug output

        Returns:
            Tuple of (list of external package names, list of resolved local file paths)
        """
        logger = getattr(self, "logger", None)

        # Log entry and root node type
        if logger:
            root_node_type = "None" if tree_node is None else tree_node.type
            logger.debug(f"[Solidity Handler Entry] Called for: {rel_path}, Root Node Type: {root_node_type}")
            if tree_node is None:
                return [], []  # Cannot proceed without a tree

        visitor = SolidityImportVisitor(rel_path, file_components_dict, local_resolver_func, logger)
        visitor.visit(tree_node)

        # Deduplicate imports before returning
        return list(set(visitor.imports)), list(set(visitor.local_imports))
