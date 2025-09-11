"""
JavaScript-specific visitors and handlers
"""

import json
import os
import re

from gardener.common.secure_file_ops import FileOperationError
from gardener.common.utils import Logger
from gardener.treewalk.base import LanguageHandler, TreeVisitor

# Module-level logger instance
logger = Logger(verbose=False)  # Will be configured by the caller


class JSImportVisitor(TreeVisitor):
    """
    Visitor for extracting imports from JavaScript/TypeScript tree
    """

    def __init__(self, rel_path, file_components_dict, local_resolver_func, logger=None):
        super().__init__()
        self.rel_path = rel_path
        self.file_components_dict = file_components_dict
        self.imports = []  # External imports
        self.local_imports = []  # Resolved local import paths
        self._resolve_local = local_resolver_func  # Store resolver
        self.logger = logger  # Store logger

    def normalize_js_package_name(self, module_path):
        """
        Normalize JS/TS package names from import paths

        Args:
            module_path (str): The import path to normalize

        Returns:
            Normalized package name or None if it's a relative/framework import
        """
        if module_path.startswith("."):  # Relative
            return None

        if module_path.startswith(("$lib/", "$app/", "$env/")) or module_path in ("$lib", "$app", "$env"):
            return None

        # For node built-ins like 'node:fs'
        if module_path.startswith("node:"):
            return module_path  # Keep the 'node:' prefix

        if module_path.startswith("@"):  # Scoped package
            parts = module_path.split("/")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"  # @scope/package
            else:
                return module_path  # @scope (unlikely but handle)
        else:  # Regular package
            return module_path.split("/")[0]  # Takes 'express' from 'express/router'

    def _ensure_component_bucket(self):
        """
        Ensure the component list exists for the current file

        Creates an empty list at `file_components_dict[self.rel_path]` if missing
        """
        if self.rel_path not in self.file_components_dict:
            self.file_components_dict[self.rel_path] = []

    def _add_component(self, package_key, component_name):
        """
        Append a component tuple for the current file

        Args:
            package_key (str): Package name or resolved local path used as the tuple key
            component_name (str): Fully qualified component name string
        """
        self._ensure_component_bucket()
        self.file_components_dict[self.rel_path].append((package_key, component_name))

    def _first_named_arg_string(self, call_node):
        """
        Return the first named argument node if it is a string literal; else None

        Args:
            call_node (object): A call_expression node
        """
        if not call_node:
            return None
        args = call_node.child_by_field_name("arguments")
        if args and args.named_child_count > 0:
            candidate = args.named_child(0)
            if candidate and candidate.type == "string":
                return candidate
        return None

    def _is_require_call(self, node):
        """
        True if call_expression is require('...')
        """
        if not node:
            return False
        func = node.child_by_field_name("function")
        return bool(func and func.type == "identifier" and func.text.decode("utf-8") == "require")

    def _is_dynamic_import_call(self, node):
        """
        True if call_expression is import('...')
        """
        if not node:
            return False
        func = node.child_by_field_name("function")
        return bool(func and func.type == "import")

    def _string_literal_from_call(self, node):
        """
        Return (raw_text, module_path) if first named arg is string; else (None, None)
        """
        arg_node = self._first_named_arg_string(node)
        if arg_node is None:
            return None, None
        raw = arg_node.text.decode("utf-8")
        return raw, raw.strip("'\"")

    def _resolve_module_for_import(self, module_path):
        """
        Categorize a module path without mutating state

        Returns:
            Tuple (category, resolved_value, package_key, name_prefix) where:
                - category in {'framework', 'local', 'external', None}
                - resolved_value is '__PACKAGE:<name>' or resolved local path or None
                - package_key is key used in components (package or resolved path)
                - name_prefix is prefix used to build component names
        """
        resolved_local_path = self._resolve_local(self.rel_path, module_path)
        if resolved_local_path:
            if resolved_local_path.startswith("__PACKAGE:"):
                package_name = resolved_local_path[10:]
                return ("framework", resolved_local_path, package_name, package_name)
            # Local file path
            return ("local", resolved_local_path, resolved_local_path, resolved_local_path)

        if not module_path.startswith("."):  # External or unresolvable alias
            package_name = self.normalize_js_package_name(module_path)
            if package_name:
                return ("external", None, package_name, package_name)

        return (None, None, None, None)

    def _extract_components_from_import_clause(self, import_stmt_node, component_prefix_for_name, package_key):
        """
        Record components for default, named, and namespace imports from an import statement

        Args:
            import_stmt_node (object): The import_statement node
            component_prefix_for_name (str): Prefix used when constructing component names
            package_key (str): Key used in file_components_dict tuples (package name or resolved path)
        """
        if not import_stmt_node or not component_prefix_for_name or not package_key:
            return

        import_clause = None
        for child in import_stmt_node.children:
            if child.type == "import_clause":
                import_clause = child
                break
        if not import_clause:
            return

        for clause_child in import_clause.children:
            if clause_child.type == "identifier":
                default_import_name = clause_child.text.decode("utf-8")
                component_name = f"{component_prefix_for_name}.{default_import_name}"
                self._add_component(package_key, component_name)
            elif clause_child.type == "named_imports":
                for named_import_child in clause_child.children:
                    if named_import_child.type == "import_specifier":
                        original_name_node = named_import_child.child_by_field_name("name")
                        if original_name_node:
                            original_name_text = original_name_node.text.decode("utf-8")
                            component_name = f"{component_prefix_for_name}.{original_name_text}"
                            self._add_component(package_key, component_name)
            elif clause_child.type == "namespace_import":
                ns_alias_node = None
                for ns_child in clause_child.children:
                    if ns_child.type == "identifier":
                        ns_alias_node = ns_child
                        break
                if ns_alias_node:
                    component_name = f"{component_prefix_for_name}.*"
                    self._add_component(package_key, component_name)

    def _record_destructured_require_components(self, call_node, package_key):
        """
        Handle parent variable_declarator/object_pattern for require() destructuring

        Records components like '{ prop }' and '{ prop: alias }' using the original property name
        """
        parent = call_node.parent
        if parent and parent.type == "variable_declarator":
            id_node = parent.child_by_field_name("name")
            if id_node and id_node.type == "object_pattern":
                for pattern_child in id_node.children:
                    if pattern_child.type == "shorthand_property_identifier_pattern":
                        prop_name = pattern_child.text.decode("utf-8")
                        self._add_component(package_key, f"{package_key}.{prop_name}")
                    elif pattern_child.type == "pair_pattern":
                        key_node = pattern_child.child_by_field_name("key")
                        if key_node and key_node.type == "property_identifier":
                            original_prop_name = key_node.text.decode("utf-8")
                            self._add_component(package_key, f"{package_key}.{original_prop_name}")

    def _export_source_string(self, node):
        """
        Return the export source string literal if present, else None
        """
        if not node:
            return None
        source_node_field = node.child_by_field_name("source")
        if source_node_field and source_node_field.type == "string":
            return source_node_field.text.decode("utf-8").strip("'\"")
        for child in node.children:
            if child.type == "string":
                return child.text.decode("utf-8").strip("'\"")
        return None

    def _record_export_resolution(self, module_path):
        """
        Perform the same resolution/mutation logic used for exports
        """
        resolved_local_path = self._resolve_local(self.rel_path, module_path)

        if resolved_local_path and resolved_local_path.startswith("__PACKAGE:"):
            package_name = resolved_local_path[10:]
            if package_name not in self.imports:
                self.imports.append(package_name)
        elif resolved_local_path:
            if resolved_local_path not in self.local_imports:
                self.local_imports.append(resolved_local_path)
        elif not module_path.startswith("."):  # External or unresolvable alias
            package_name = self.normalize_js_package_name(module_path)
            if package_name and package_name not in self.imports:
                self.imports.append(package_name)

    def visit_import_statement(self, node):
        """
        Process JavaScript/TypeScript import statements to extract dependencies

        Handles ES6 module imports including default imports, named imports, namespace
        imports, and side-effect imports. Resolves local paths, framework aliases
        (e.g., SvelteKit's $lib), and external package imports. Tracks both the imported
        packages and specific components imported from them

        Args:
            node (object): AST node representing an import statement
        """

        for child in node.children:
            if child.type == "string":
                module_path = child.text.decode("utf-8").strip("'\"")

                category, resolved_value, package_key, name_prefix = self._resolve_module_for_import(module_path)

                if category == "framework":
                    # For framework package aliases, create a component using the original module path
                    self.imports.append(package_key)
                    self._ensure_component_bucket()
                    self.file_components_dict[self.rel_path].append((package_key, module_path))
                    continue

                package_name_for_components_key = None
                component_prefix_for_name = None

                if category == "local":
                    self.local_imports.append(resolved_value)
                    package_name_for_components_key = package_key
                    component_prefix_for_name = name_prefix
                elif category == "external":
                    self.imports.append(package_key)
                    package_name_for_components_key = package_key
                    component_prefix_for_name = name_prefix

                if package_name_for_components_key and component_prefix_for_name:
                    self._extract_components_from_import_clause(
                        node, component_prefix_for_name, package_name_for_components_key
                    )

        # After the loop, or if no string child was found that led to an early exit,
        # allow generic visit to process other children like import_clause for components
        # This ensures component logic (which iterates node.children again) is reached
        super().generic_visit(node)

    def visit_export_statement(self, node):
        """
        Process JavaScript/TypeScript export statements to extract re-exported dependencies

        Handles export statements that re-export from other modules (e.g., 'export * from',
        'export { foo } from'). These statements indicate dependencies on the source modules
        being re-exported. Does not track local exports that don't reference other modules

        Args:
            node (object): AST node representing an export statement
        """
        module_path = self._export_source_string(node)
        if module_path:
            self._record_export_resolution(module_path)

        super().generic_visit(node)

    def visit_call_expression(self, node):
        """
        Process JavaScript/TypeScript call expressions to extract CommonJS and dynamic imports

        Handles require() calls for CommonJS modules and dynamic import() expressions
        Extracts both the module being imported and any destructured components from
        require() calls. Resolves local paths, framework aliases, and external packages

        Args:
            node (object): AST node representing a call expression
        """
        is_require = self._is_require_call(node)
        is_dynamic_import = self._is_dynamic_import_call(node)

        raw_text_from_node, module_path = (None, None)
        if is_require or is_dynamic_import:
            raw_text_from_node, module_path = self._string_literal_from_call(node)

        if (is_require or is_dynamic_import) and module_path:
            category, resolved_value, package_key, _ = self._resolve_module_for_import(module_path)

            package_name_for_components = None  # This will hold the key for components_dict

            if category == "framework":
                self.imports.append(package_key)
                package_name_for_components = package_key
            elif category == "local":
                self.local_imports.append(resolved_value)
                package_name_for_components = resolved_value
            elif category == "external":
                self.imports.append(package_key)
                package_name_for_components = package_key

            if is_require and package_name_for_components:
                self._record_destructured_require_components(node, package_name_for_components)

        # We need to visit ALL children to ensure we find imports/requires in function bodies
        for child in node.children:
            self.visit(child)


class JavaScriptLanguageHandler(LanguageHandler):
    """Handler for JavaScript language"""

    def __init__(self, logger=None):
        """
        Args:
            logger (Logger): Optional logger instance
        """
        self.logger = logger

    def get_manifest_files(self):
        return ["package.json"]

    def get_file_extensions(self):
        return [".js", ".jsx", ".mjs", ".cjs", ".svelte"]

    def process_manifest(self, file_path, packages_dict, secure_file_ops=None):
        try:
            data = self.safe_json_load(file_path, secure_file_ops)

            dependencies = data.get("dependencies", {})
            dev_dependencies = data.get("devDependencies", {})
            peer_dependencies = data.get("peerDependencies", {})
            optional_dependencies = data.get("optionalDependencies", {})
            bundle_dependencies_list = data.get("bundleDependencies", data.get("bundledDependencies", []))
            # Convert list of bundled deps into dict format for merging
            # Ensure items are strings
            bundle_dependencies = {pkg: "bundled" for pkg in bundle_dependencies_list if isinstance(pkg, str)}

            pnpm_overrides = {}
            pnpm_patched = {}
            if "pnpm" in data and isinstance(data["pnpm"], dict):
                pnpm_data = data["pnpm"]
                if "overrides" in pnpm_data and isinstance(pnpm_data["overrides"], dict):
                    pnpm_overrides = {pkg: version for pkg, version in pnpm_data["overrides"].items()}
                if "patchedDependencies" in pnpm_data and isinstance(pnpm_data["patchedDependencies"], dict):
                    pnpm_patched = {pkg: "patched" for pkg in pnpm_data["patchedDependencies"].keys()}

            # Merge all dependency sources
            all_deps = {
                **dependencies,
                **dev_dependencies,
                **peer_dependencies,
                **optional_dependencies,
                **bundle_dependencies,
                **pnpm_overrides,
                **pnpm_patched,
            }

            for name, version in all_deps.items():
                # Ensure version is a string, handle cases like bundled/patched
                version_str = version if isinstance(version, str) else str(version)
                # Basic check to avoid adding non-package keys if parsing was too broad
                if isinstance(name, str) and (name.startswith("@") or "/" not in name or "." not in name):
                    packages_dict[name] = {"ecosystem": "npm", "version": version_str}

        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in {os.path.basename(file_path)} at {file_path}: {e}")
            # Try a more lenient parsing approach as fallback
            try:
                content = self.read_file_content(file_path, secure_file_ops)
                # Regex to extract package names and versions
                dep_pattern = r'"([@\w\-\/\.]+)"\s*:\s*"([^"]+)"'
                for section in ["dependencies", "devDependencies"]:
                    section_match = re.search(f'"{section}"\\s*:\\s*{{([^}}]+)}}', content)
                    if section_match:
                        section_content = section_match.group(1)
                        matches = re.findall(dep_pattern, section_content)
                        for name, version in matches:
                            packages_dict[name] = {"ecosystem": "npm", "version": version}
            except Exception as fallback_err:
                logger.error(f"Fallback parsing failed for {file_path}: {fallback_err}")
        except FileOperationError as e:
            logger.error(f"Failed to read manifest file {file_path}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error processing manifest file {file_path}", exception=e)

        return packages_dict

    def normalize_package_name(self, package_path):
        """Normalize JS/TS package names from import paths"""
        if package_path.startswith("."):
            return None

        if package_path.startswith("@"):
            parts = package_path.split("/")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"
            else:
                return package_path
        else:
            return package_path.split("/")[0]

    def extract_imports(self, tree_node, rel_path, file_components_dict, local_resolver_func, logger=None):
        """
        Extract external package imports and resolved local imports from a JS/TS source file
        """
        visitor = JSImportVisitor(rel_path, file_components_dict, local_resolver_func, logger)
        visitor.visit(tree_node)
        return list(set(visitor.imports)), list(set(visitor.local_imports))
