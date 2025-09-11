"""
Base resolver for package imports
"""

from gardener.common.file_helpers import read_file_content, safe_json_load


class BaseResolver:
    """
    Base class for all package import name resolvers

    Defines the common interface that all language-specific resolvers must implement
    """

    def __init__(self, secure_file_ops=None):
        """
        Args:
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations
        """
        self.secure_file_ops = secure_file_ops

    def resolve_from_manifest(self, manifest_path, logger=None, **kwargs):
        """
        Resolve import names from a manifest file

        Args:
            manifest_path (str): Path to manifest file
            logger (Logger): Optional logger instance
            **kwargs: Additional resolver-specific parameters

        Returns:
            dict: Mapping of {package_name: [import_names]} where import_names is a list
        """
        raise NotImplementedError("Subclasses must implement resolve_from_manifest")

    def read_file_content(self, file_path, encoding="utf-8"):
        """
        Read file content using the shared utility function

        This method delegates to the shared file_helpers module to eliminate code duplication

        Args:
            file_path (str): Path to the file to read
            encoding (str): File encoding (default: 'utf-8')

        Returns:
            The content of the file as a string
        """
        return read_file_content(file_path, self.secure_file_ops, encoding)

    def safe_json_load(self, file_path):
        """
        Load JSON content from a file using the shared utility function

        This method delegates to the shared file_helpers module to eliminate code duplication

        Args:
            file_path (str): Path to the JSON file to read

        Returns:
            The parsed JSON content as a dictionary or list
        """
        return safe_json_load(file_path, self.secure_file_ops)
