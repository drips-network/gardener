"""
Rust-specific visitors and handlers
"""

import os
import re

try:
    import toml as _toml
except Exception:  # pragma: no cover - optional dependency
    _toml = None

from gardener.common.secure_file_ops import FileOperationError
from gardener.common.utils import Logger
from gardener.treewalk.base import LanguageHandler, TreeVisitor

# Module-level logger instance
logger = Logger(verbose=False)  # Will be configured by the caller


class RustImportVisitor(TreeVisitor):
    """
    Visitor for extracting imports (use declarations) from Rust tree

    Traverses the syntax tree to find and process 'use' statements
    to determine external package dependencies
    """

    # Class-level constants to avoid per-instance reallocation
    CRATE_LOCAL_ROOTS = {"crate", "super", "self"}
    STD_CRATES = {"std", "core", "alloc"}
    KNOWN_NON_CRATE_ATTRIBUTES = {"derive", "cfg", "test", "allow", "warn", "deny", "forbid", "deprecated"}

    def __init__(self, rel_path, file_components_dict, local_resolver_func):
        """
        Args:
            rel_path (str): Relative path of the source file
            file_components_dict (dict): Dictionary to track imported components
            local_resolver_func (callable): Function to resolve local Rust imports
        """
        super().__init__()
        self.rel_path = rel_path
        self.file_components_dict = file_components_dict
        self.imports = []  # External crate imports
        self.local_imports = []  # Resolved local import paths
        self._resolve_local = local_resolver_func  # Store resolver
        self.current_file_inline_modules = set()  # Stores names of inline modules in the current file

    def _scan_for_inline_modules(self, node):
        """
        Perform a preliminary scan for top-level inline module names in the current file

        This method populates `self.current_file_inline_modules` with names of modules
        defined like `mod foo { ... }` at the top level of the file being processed
        It should be called once on the 'source_file' node before other visitations

        Args:
            node (object): The current AST node, expected to be 'source_file' for the initial scan
        """
        if node.type == "source_file":
            for child in node.children:  # Iterate over top-level items in the file
                if child.type == "mod_item":
                    # An inline module has a 'body' field, which is a 'block' or similar node
                    body_node = child.child_by_field_name("body")
                    if body_node:  # This confirms it's an inline module
                        name_node = None
                        for sub_child in child.children:  # Iterate children of mod_item
                            if sub_child.type == "identifier":
                                name_node = sub_child
                                break
                        if name_node:
                            module_name = name_node.text.decode("utf-8")
                            self.current_file_inline_modules.add(module_name)

    def visit(self, node):
        """
        Override the generic visit method to perform a pre-scan for inline modules

        This ensures that inline module names are collected before processing use declarations

        Args:
            node (object): The current AST node to visit
        """
        # Perform the pre-scan for inline modules at the root of the file
        if node.type == "source_file":  # Assuming the top node passed is always source_file
            self._scan_for_inline_modules(node)

        # Then proceed with the normal visitation logic for all nodes
        super().visit(node)

    def _get_initial_segment(self, node):
        """Helper to get the first textual segment of a use path node"""
        if node.type == "identifier":
            return node.text.decode("utf-8")
        elif node.type == "scoped_identifier":
            path_child = node.child_by_field_name("path")
            if path_child:
                return self._get_initial_segment(path_child)
        elif node.type in ["crate", "super", "self"]:
            return node.text.decode("utf-8")

        return None

    def _collect_import_details(self, use_item_node, current_path_prefix_parts, is_truly_local_path):
        """
        Recursively collects full import path strings from a use item
        Args:
            use_item_node (object): The current node in the use path (identifier, scoped_identifier,
                                    use_list, use_wildcard)
            current_path_prefix_parts (list): List of path segments leading up to this item
            is_truly_local_path (bool): Boolean indicating if the entire use statement is local
        Returns:
            A list of (full_path_parts_list, is_truly_local_path_bool) tuples
        """
        collected = []
        node_type = use_item_node.type

        if node_type == "identifier" or node_type in ["crate", "super", "self"]:
            part = use_item_node.text.decode("utf-8")
            collected.append((current_path_prefix_parts + [part], is_truly_local_path))

        elif node_type == "scoped_identifier":
            path_child = use_item_node.child_by_field_name("path")
            name_child = use_item_node.child_by_field_name("name")  # This is an identifier
            if path_child and name_child:
                # Recursively process the 'path' (left) part, passing the current prefix
                details_from_left = self._collect_import_details(
                    path_child, current_path_prefix_parts, is_truly_local_path
                )
                for left_parts, _ in details_from_left:  # is_truly_local_path is already determined
                    # Append the 'name' (right) part to each path from the left
                    collected.append((left_parts + [name_child.text.decode("utf-8")], is_truly_local_path))
            # else: malformed scoped_identifier, or simple identifier handled above

        elif node_type == "use_list":
            for item_in_list in use_item_node.children:
                if item_in_list.type in ["identifier", "scoped_identifier", "use_wildcard"]:
                    # Each item in the list uses the same prefix and local status
                    collected.extend(
                        self._collect_import_details(item_in_list, current_path_prefix_parts, is_truly_local_path)
                    )

        elif node_type == "use_wildcard":
            collected.append((current_path_prefix_parts + ["*"], is_truly_local_path))

        return collected

    def visit_use_declaration(self, node):
        path_node = self._find_use_path_node(node)
        if not path_node:
            return

        is_truly_local_path, base_path_parts_for_collect, adjusted_path_node = self._assess_locality_and_base_parts(
            path_node
        )

        all_import_details = self._collect_import_details(
            adjusted_path_node, base_path_parts_for_collect, is_truly_local_path
        )

        for full_path_parts, initial_local_assessment_flag in all_import_details:
            if not full_path_parts:
                continue
            self._process_import_detail(full_path_parts, initial_local_assessment_flag)

    def _find_use_path_node(self, node):
        """
        Identify the primary path node within a use_declaration, handling use_as_clause

        Args:
            node (object): The 'use_declaration' AST node

        Returns:
            The path node to analyze (identifier/scoped_identifier/use_list/use_wildcard/scoped_use_list) or None
        """
        path_node = None
        children = list(node.children)
        i = 0
        while i < len(children):
            child = children[i]
            if child.type == "use":
                i += 1
                continue
            if child.type in ["identifier", "scoped_identifier", "use_list", "use_wildcard", "scoped_use_list"]:
                path_node = child
                break
            elif child.type == "use_as_clause":
                original_path_candidate = child.child_by_field_name("path")
                if original_path_candidate:
                    path_node = original_path_candidate
                else:
                    for sub_child in child.children:
                        if sub_child.type in ["identifier", "scoped_identifier", "scoped_use_list", "use_list"]:
                            path_node = sub_child
                            break
                if path_node:
                    break
            i += 1
        return path_node

    def _assess_locality_and_base_parts(self, path_node):
        """
        Determine locality and base parts for a Rust 'use' path

        Handles:
            - use_wildcard: extracts prefix and detects locality
            - scoped_use_list: detects prefix locality and uses its list node
            - identifier / scoped_identifier / use_list: extracts first segment and detects locality

        Returns:
            Tuple of (is_truly_local_path, base_path_parts_for_collect, adjusted_path_node)
        """
        is_truly_local_path = False
        base_path_parts_for_collect = []
        adjusted_node = path_node

        if path_node.type == "use_wildcard":
            full_wildcard_path_str = path_node.text.decode("utf-8")
            if "::*" == full_wildcard_path_str[-3:]:
                prefix_str = full_wildcard_path_str[:-3]
                current_base_parts = prefix_str.split("::")
                if current_base_parts:
                    base_path_parts_for_collect = current_base_parts
                    first_segment_text = base_path_parts_for_collect[0]
                    if (
                        first_segment_text in self.CRATE_LOCAL_ROOTS
                        or first_segment_text in self.current_file_inline_modules
                    ):
                        is_truly_local_path = True

        elif path_node.type == "scoped_use_list":
            prefix_node = path_node.child_by_field_name("path")
            list_node_from_scoped = path_node.child_by_field_name("list")
            if prefix_node and list_node_from_scoped:
                first_segment_of_prefix = self._get_initial_segment(prefix_node)
                current_prefix_is_local = False
                if first_segment_of_prefix:
                    if (
                        first_segment_of_prefix in self.CRATE_LOCAL_ROOTS
                        or first_segment_of_prefix in self.current_file_inline_modules
                    ):
                        current_prefix_is_local = True
                is_truly_local_path = current_prefix_is_local
                prefix_details = self._collect_import_details(prefix_node, [], current_prefix_is_local)
                if prefix_details and prefix_details[0] and prefix_details[0][0]:
                    base_path_parts_for_collect = prefix_details[0][0]
                adjusted_node = list_node_from_scoped
            else:
                return False, [], path_node
        else:
            first_segment_text = self._get_initial_segment(path_node)
            if first_segment_text:
                if (
                    first_segment_text in self.CRATE_LOCAL_ROOTS
                    or first_segment_text in self.current_file_inline_modules
                ):
                    is_truly_local_path = True

        return is_truly_local_path, base_path_parts_for_collect, adjusted_node

    def _process_import_detail(self, full_path_parts, initial_local_assessment_flag):
        """
        Process a single collected import detail and record local/external components
        """
        full_path_str = "::".join(full_path_parts)
        resolved_local_path = self._resolve_local(self.rel_path, full_path_parts)
        if resolved_local_path:
            if resolved_local_path not in self.local_imports:
                self.local_imports.append(resolved_local_path)
            if not initial_local_assessment_flag:
                component_root_for_local = "self"
                actual_component_path_for_local = f"self::{full_path_str}"
            else:
                component_root_for_local = full_path_parts[0]
                actual_component_path_for_local = full_path_str
            if full_path_parts[-1] != "*" and component_root_for_local != "*":
                self.file_components_dict[self.rel_path].append(
                    (component_root_for_local, actual_component_path_for_local)
                )
        else:
            if not initial_local_assessment_flag:
                crate_name = full_path_parts[0]
                if crate_name == "*":
                    return
                if crate_name not in self.imports:
                    self.imports.append(crate_name)
                if len(full_path_parts) > 1 and full_path_parts[-1] != "*":
                    self.file_components_dict[self.rel_path].append((crate_name, full_path_str))
            else:
                if full_path_parts[-1] != "*":
                    component_root_name = full_path_parts[0]
                    if component_root_name != "*":
                        self.file_components_dict[self.rel_path].append((component_root_name, full_path_str))

    def visit_attribute_item(self, node):
        meta_item_node = self._attribute_meta_item(node)
        if not meta_item_node:
            return

        path_text_to_process = self._attribute_path_text(meta_item_node)
        if not path_text_to_process:
            return

        path_parts = path_text_to_process.split("::")
        if not path_parts or not path_parts[0]:
            return

        package_name = path_parts[0]
        if self._is_crate_based_attribute(package_name):
            if package_name not in self.imports:
                self.imports.append(package_name)
            self._append_attribute_component_if_needed(package_name, path_text_to_process)

    def _attribute_meta_item(self, node):
        """
        Return the meta item node or None
        """
        meta_item_node = node.child_by_field_name("item")
        if not meta_item_node:
            for named_child in node.named_children:
                if named_child.type == "attribute":
                    meta_item_node = named_child
                    break
        return meta_item_node

    def _attribute_path_text(self, meta_item_node):
        """
        Return 'tokio::main' / 'serde::Serialize' etc., or None
        """
        if meta_item_node.type in ["identifier", "scoped_identifier"]:
            return meta_item_node.text.decode("utf-8")
        elif meta_item_node.type == "meta_list":
            path_child = meta_item_node.child_by_field_name("path")
            if path_child and path_child.type in ["identifier", "scoped_identifier"]:
                return path_child.text.decode("utf-8")
            return None
        elif meta_item_node.type == "meta_name_value":
            return None
        elif meta_item_node.type == "attribute":
            attr_content_text = meta_item_node.text.decode("utf-8")
            if "(" in attr_content_text:
                return attr_content_text.split("(", 1)[0]
            return attr_content_text
        return None

    def _is_crate_based_attribute(self, package_name):
        """
        Return True if this attribute is a crate path, not std or non-crate attrs
        """
        return (
            package_name not in self.CRATE_LOCAL_ROOTS
            and package_name not in self.STD_CRATES
            and package_name not in self.KNOWN_NON_CRATE_ATTRIBUTES
        )

    def _append_attribute_component_if_needed(self, package_name, path_text):
        """
        Append (package_name, path_text) to components if not already present and multi-part path
        """
        if "::" in path_text:
            component_tuple = (package_name, path_text)
            if component_tuple not in self.file_components_dict[self.rel_path]:
                self.file_components_dict[self.rel_path].append(component_tuple)

    def visit_mod_item(self, node):
        """
        Handle Rust module declarations

        For 'mod foo;', it's a file import

        For 'mod foo { ... }', its contents (like use statements) need to be visited
        """
        name_node, body_block_node = self._mod_name_and_body(node)
        if not name_node:
            return

        if body_block_node:
            self._visit_inline_mod_body(body_block_node)
            return

        module_name = name_node.text.decode("utf-8")
        self._resolve_and_record_file_module(module_name)

    def _mod_name_and_body(self, node):
        """
        Return (name_node, body_block_node)
        """
        name_node = None
        body_block_node = node.child_by_field_name("body")
        for child in node.children:
            if child.type == "identifier":
                name_node = child
                break
        return name_node, body_block_node

    def _visit_inline_mod_body(self, body_block_node):
        """
        Iterate children and dispatch to visit methods exactly as today
        """
        for item_in_body in body_block_node.children:
            if item_in_body.type == "use_declaration":
                self.visit_use_declaration(item_in_body)
            elif item_in_body.type == "attribute_item":
                self.visit_attribute_item(item_in_body)
            elif item_in_body.type == "mod_item":
                self.visit_mod_item(item_in_body)

    def _resolve_and_record_file_module(self, module_name):
        """
        Resolve with self._resolve_local and append to self.local_imports if needed
        """
        module_path_parts = [module_name]
        resolved_local_path = self._resolve_local(self.rel_path, module_path_parts)
        if resolved_local_path:
            if resolved_local_path not in self.local_imports:
                self.local_imports.append(resolved_local_path)


class RustLanguageHandler(LanguageHandler):
    """
    Handler for Rust language

    Provides functionality for processing Rust source files and Cargo.toml manifest files
    to extract imports, definitions, and references
    """

    def __init__(self, logger=None):
        """
        Args:
            logger (Logger): Optional logger instance
        """
        self.logger = logger

    def get_manifest_files(self):
        """
        Get the list of manifest files for Rust projects

        Returns:
            List of manifest filenames
        """
        return ["Cargo.toml"]

    def get_file_extensions(self):
        """
        Get the file extensions for Rust source files

        Returns:
            List of file extensions used by Rust
        """
        return [".rs"]

    def process_manifest(self, file_path, packages_dict, secure_file_ops=None):
        """
        Process a Rust manifest file to extract dependencies

        Args:
            file_path (str): Path to the manifest file
            packages_dict (dict): Dictionary to update with package information
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations

        Returns:
            Updated packages_dict with Rust dependencies
        """
        basename = os.path.basename(file_path)

        if basename == "Cargo.toml":
            try:
                content = self.read_file_content(file_path, secure_file_ops)
                added = False
                if _toml is not None:
                    try:
                        data = _toml.loads(content)

                        def _add_dep(pkg_key, pkg_val):
                            nonlocal added
                            # Use the canonical package name from 'package' field when present
                            if isinstance(pkg_val, dict) and "package" in pkg_val:
                                dist_name = str(pkg_val["package"])
                                alias = str(pkg_key)
                            else:
                                dist_name = str(pkg_key)
                                alias = None

                            entry = packages_dict.get(dist_name, {"ecosystem": "cargo"})
                            # If an alias exists, seed import_names so Graph can map alias imports
                            alias_names = entry.get("import_names", [])
                            # Canonical import name from distribution
                            canon_import = dist_name.replace("-", "_")
                            if canon_import not in alias_names:
                                alias_names.append(canon_import)
                            if alias:
                                alias_import = alias.replace("-", "_")
                                if alias_import not in alias_names:
                                    alias_names.append(alias_import)
                            entry["import_names"] = alias_names
                            packages_dict[dist_name] = entry
                            added = True

                        # Top-level dependency tables
                        for key in ["dependencies", "dev-dependencies", "build-dependencies"]:
                            tbl = data.get(key, {}) or {}
                            if isinstance(tbl, dict):
                                for dep_name, dep_val in tbl.items():
                                    _add_dep(dep_name, dep_val)
                        # Target-specific dependency tables
                        tgt = data.get("target", {}) or {}
                        if isinstance(tgt, dict):
                            for _cfg, cfg_tbl in tgt.items():
                                if not isinstance(cfg_tbl, dict):
                                    continue
                                for key in ["dependencies", "dev-dependencies", "build-dependencies"]:
                                    tbl = cfg_tbl.get(key, {}) or {}
                                    if isinstance(tbl, dict):
                                        for dep_name, dep_val in tbl.items():
                                            _add_dep(dep_name, dep_val)
                    except Exception:
                        # Fall back to regex if TOML parsing fails
                        pass

                if not added:
                    # Regex fallback: also match target.*.dependencies headers
                    deps_pattern = r"\[(?:target\.[^\]]+\.)?(?:dev-|build-)?dependencies\](.*?)(\n\[|\Z)"
                    matches = re.finditer(deps_pattern, content, re.DOTALL | re.IGNORECASE)
                    for m in matches:
                        deps_section = m.group(1)
                        lines = deps_section.strip().split("\n")
                        for line in lines:
                            line = line.strip()
                            if not line or line.startswith("#"):
                                continue
                            mm = re.match(r"^([a-zA-Z0-9_-]+)\s*=", line)
                            if mm:
                                dep_name = mm.group(1)
                                packages_dict[dep_name] = {"ecosystem": "cargo"}
            except FileOperationError as e:
                if self.logger:
                    self.logger.error(f"Failed to read Cargo.toml at {file_path}: {e}")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Unexpected error processing Cargo.toml at {file_path}", exception=e)

        return packages_dict

    def normalize_package_name(self, package_path):
        """
        Normalize Rust crate names from import paths

        Args:
            package_path (str): The raw import path

        Returns:
            Normalized package name or None if it's a relative import
        """
        if package_path.startswith("."):
            return None  # Relative
        # Standard library crates often don't have '::'
        if "::" in package_path:
            return package_path.split("::")[0]
        else:
            # Could be std lib (like 'std') or a top-level crate import
            # Assume external for now if it's not 'std', 'core', 'alloc', 'crate', 'super', 'self'
            if package_path not in ["std", "core", "alloc", "crate", "super", "self"]:
                return package_path
            else:
                return None

    def extract_imports(self, tree_node, rel_path, file_components_dict, local_resolver_func, logger=None):
        """
        Extract external crate imports and resolved local imports from a Rust source file

        Args:
            tree_node (object): Tree-sitter node for the source file
            rel_path (str): Relative path of the source file
            file_components_dict (dict): Dictionary to track imported external components
            local_resolver_func (callable): Function to resolve local Rust module paths
            logger (Logger): Optional logger instance for debug output

        Returns:
            Tuple of (list of external crate names, list of resolved local file paths)
        """
        visitor = RustImportVisitor(rel_path, file_components_dict, local_resolver_func)
        visitor.visit(tree_node)
        # Deduplicate external imports before returning
        return list(set(visitor.imports)), visitor.local_imports
