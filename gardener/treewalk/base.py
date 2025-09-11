"""
Base classes for tree traversal
"""

from abc import ABC, abstractmethod

from gardener.common.file_helpers import read_file_content, safe_json_load


class TreeVisitor:
    """
    Base visitor class for traversing syntax tree nodes

    Implements the visitor pattern for cleaner tree traversal
    """

    def __init__(self):
        self._depth = 0
        self._max_depth = None  # Will be set from ResourceLimits if needed

    def visit(self, node):
        """
        Visit a node and return the result

        Args:
            node (object): The tree node to visit

        Returns:
            The result of visiting the node
        """
        if node is None:
            return None

        if self._max_depth is None:
            # Lazy load to avoid circular import
            from gardener.common.defaults import ResourceLimits

            self._max_depth = ResourceLimits.MAX_TREE_DEPTH

        if self._depth >= self._max_depth:
            # Log warning if logger is available
            if hasattr(self, "logger") and self.logger:
                self.logger.warning(f"Tree depth limit ({self._max_depth}) reached, skipping deeper nodes")
            return None

        # Ensure node.type is a string and stripped before use
        node_type_str = str(node.type).strip()

        method_name = f"visit_{node_type_str.replace('-', '_')}"
        method = getattr(self, method_name, self.generic_visit)

        # Increment depth before visiting
        self._depth += 1
        try:
            try:
                return method(node)
            except RecursionError:
                # Gracefully stop traversal if Python recursion limit is hit
                if hasattr(self, "logger") and self.logger:
                    self.logger.warning("Python recursion limit reached during tree traversal; stopping descent")
                return None
        finally:
            # Always decrement depth after visiting
            self._depth -= 1

    def generic_visit(self, node):
        """
        Default visit method that traverses all children

        Args:
            node (object): The tree node whose children to visit

        Returns:
            The result of the visitor
        """
        if node is None:
            return

        for child in node.children:
            self.visit(child)
        return


class LanguageHandler(ABC):
    """
    Abstract base class defining the interface for language-specific handlers

    This class will be extended as additional languages are supported
    """

    @abstractmethod
    def get_manifest_files(self):
        """
        Return a list of manifest filenames for this language

        Returns:
            List of manifest filenames
        """
        pass

    @abstractmethod
    def process_manifest(self, file_path, packages_dict, secure_file_ops=None):
        """
        Process a manifest file and update the packages dictionary

        Args:
            file_path (str): Path to the manifest file
            packages_dict (dict): Dictionary to update with package information
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations

        Returns:
            Updated packages_dict
        """
        pass

    @abstractmethod
    def extract_imports(self, tree_node, rel_path, file_components_dict, local_resolver_func, logger=None):
        """
        Extract imports from a tree node

        Args:
            tree_node (object): Tree-sitter node
            rel_path (str): Relative path of the file
            file_components_dict (dict): Dictionary to update with file components
            local_resolver_func (callable): Function to resolve local module paths
            logger (Logger): Optional logger instance for debug output

        Returns:
            Tuple of (external_imports, local_imports) where:
                - external_imports: List of imported external package names
                - local_imports: List of resolved local file paths
        """
        pass

    def get_file_extensions(self):
        """
        Get the file extensions supported by this language handler

        Returns:
            List of file extensions (with dot prefix)
        """
        return []

    def normalize_package_name(self, package_path):
        """
        Normalize a package name from an import statement

        Args:
            package_path (str): The raw import path

        Returns:
            Normalized package name or None if it's a relative import
        """
        pass

    def read_file_content(self, file_path, secure_file_ops=None, encoding="utf-8"):
        """
        Read file content using the shared utility function

        This method delegates to the shared file_helpers module to eliminate code duplication

        Args:
            file_path (str): Path to the file to read
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations
            encoding (str): File encoding (default: 'utf-8')

        Returns:
            The content of the file as a string
        """
        return read_file_content(file_path, secure_file_ops, encoding)

    def safe_json_load(self, file_path, secure_file_ops=None):
        """
        Load JSON content from a file using the shared utility function

        This method delegates to the shared file_helpers module to eliminate code duplication

        Args:
            file_path (str): Path to the JSON file to read
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations

        Returns:
            The parsed JSON content as a dictionary or list
        """
        return safe_json_load(file_path, secure_file_ops)
