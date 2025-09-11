"""
Go-specific visitors and handlers
"""

import os
import re

from gardener.common.secure_file_ops import FileOperationError
from gardener.common.utils import Logger
from gardener.treewalk.base import LanguageHandler, TreeVisitor

# Module-level logger instance
logger = Logger(verbose=False)  # Will be configured by the caller


class GoImportVisitor(TreeVisitor):
    """
    Visitor for extracting imports from Go tree
    """

    def __init__(self, rel_path, file_components_dict, local_resolver_func):
        super().__init__()
        self.rel_path = rel_path
        self.file_components_dict = file_components_dict
        self.imports = []  # External imports
        self.local_imports = []  # Resolved local import paths
        self._resolve_local = local_resolver_func  # Store resolver

    def visit_import_declaration(self, node):
        """
        Process Go import declarations to extract package dependencies

        Handles various Go import forms including aliased imports, dot imports,
        blank imports, and grouped imports. Distinguishes between local imports
        (within the same module) and external imports (from other modules or
        standard library)

        Args:
            node (object): AST node representing a Go import declaration
        """
        import_specs = self._collect_import_specs(node)

        for spec in import_specs:
            package_path_node = self._extract_package_path_node(spec)

            if package_path_node:
                package_path = self._decode_import_path(package_path_node)
                self._resolve_and_record_import(package_path)

    def _collect_import_specs(self, node):
        """
        Collect all 'import_spec' nodes from an import_declaration

        Args:
            node: The tree-sitter node for a Go import_declaration

        Returns:
            List of import_spec nodes in the order they appear
        """
        specs = []
        for child in node.children:
            if child.type == "import_spec_list":
                for spec_in_list in child.children:
                    if spec_in_list.type == "import_spec":
                        specs.append(spec_in_list)
            elif child.type == "import_spec":
                specs.append(child)
        return specs

    def _extract_package_path_node(self, spec):
        """
        Return the string-literal node holding the import path, or None if absent

        Args:
            spec: An 'import_spec' node

        Returns:
            The string literal node that contains the import path or None
        """
        for spec_child in spec.children:
            if spec_child.type == "interpreted_string_literal" or spec_child.type == "raw_string_literal":
                return spec_child
        return None

    def _decode_import_path(self, path_node):
        """
        Decode and strip quotes from a Go string literal path node

        Args:
            path_node: The string literal node (interpreted or raw)

        Returns:
            Decoded import path string
        """
        return path_node.text.decode("utf-8").strip('"')

    def _resolve_and_record_import(self, package_path):
        """
        Use self._resolve_local to classify and record imports

        Mutates:
            self.local_imports, self.imports, self.file_components_dict
        """
        resolved_local_path = self._resolve_local(self.rel_path, package_path)
        if resolved_local_path:
            self.local_imports.append(resolved_local_path)
        else:
            self.imports.append(package_path)
            import_name = package_path.split("/")[-1]
            component_name = f"{package_path}.{import_name}"
            self.file_components_dict[self.rel_path].append((package_path, component_name))


class GoLanguageHandler(LanguageHandler):
    """Handler for Go language"""

    def __init__(self, logger=None):
        """
        Args:
            logger (Logger): Optional logger instance
        """
        self.logger = logger

    def get_manifest_files(self):
        return ["go.mod", "go.sum"]

    def get_file_extensions(self):
        return [".go"]

    def process_manifest(self, file_path, packages_dict, secure_file_ops=None):
        basename = os.path.basename(file_path)

        if basename == "go.mod":
            try:
                content = self.read_file_content(file_path, secure_file_ops)
                # Look for require block or individual require lines
                require_pattern = r"require\s+\((.*?)\)|require\s+([^\s]+)\s+v[^\s]+"
                matches = re.finditer(require_pattern, content, re.DOTALL)

                for match in matches:
                    if match.group(1):  # Block require
                        requires = match.group(1)
                        dep_pattern = r"([^\s]+)\s+v[0-9.]+"
                        deps = re.findall(dep_pattern, requires)
                        for dep in deps:
                            packages_dict[dep] = {"ecosystem": "go"}
                    elif match.group(2):  # Single require line
                        dep = match.group(2)
                        packages_dict[dep] = {"ecosystem": "go"}

            except FileOperationError as e:
                logger.error(f"Failed to process Go mod file {file_path}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error processing Go mod file {file_path}", exception=e)

        return packages_dict

    def normalize_package_name(self, package_path):
        """Go imports are usually full paths, return as is if external"""
        if package_path.startswith("."):
            return None  # Relative import
        # Assume external if contains '/' or '.'
        if "/" in package_path or "." in package_path:
            return package_path
        return None  # Likely standard library

    def extract_imports(self, tree_node, rel_path, file_components_dict, local_resolver_func, logger=None):
        """
        Extract external package imports and resolved local imports from a Go source file

        Args:
            tree_node (object): Tree-sitter node
            rel_path (str): Relative path of the file
            file_components_dict (dict): Dictionary to track imported external components
            local_resolver_func (callable): Function to resolve local imports
            logger (Logger): Optional logger instance for debug output

        Returns:
            Tuple of (external_imports, local_imports)
        """
        visitor = GoImportVisitor(rel_path, file_components_dict, local_resolver_func)
        visitor.visit(tree_node)
        return visitor.imports, visitor.local_imports
