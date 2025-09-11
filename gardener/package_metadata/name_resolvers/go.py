"""
Resolver for Go package manifests (go.mod)
"""

import re

from gardener.common.secure_file_ops import FileOperationError
from gardener.package_metadata.name_resolvers.base import BaseResolver


class GoResolver(BaseResolver):
    """
    Resolver for Go modules based on go.mod files

    Extracts module import paths from require directives in go.mod files
    """

    def __init__(self, secure_file_ops=None):
        """
        Args:
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations
        """
        super().__init__(secure_file_ops)

    def resolve_from_manifest(self, manifest_path, logger=None, **kwargs):
        """
        Resolve imports from go.mod

        Args:
            manifest_path (str): Path to go.mod file
            logger (Logger): Optional logger instance
            **kwargs: Additional resolver-specific parameters

        Returns:
            dict: Mapping of {package_name: [import_names]}
        """
        logger and logger.debug(f"Resolving imports from go.mod: {manifest_path}")
        try:
            content = self.read_file_content(manifest_path)
            lines = content.splitlines()
        except FileOperationError as e:
            logger and logger.error(f"Failed to read {manifest_path}: {e}")
            return {}
        except Exception as e:
            logger and logger.error(f"Unexpected error reading {manifest_path}: {e}")
            return {}

        result = {}
        in_require_block = False

        for line in lines:
            line = re.sub(r"//.*", "", line).strip()
            if not line:
                continue

            if line.startswith("require ("):
                in_require_block = True
                continue

            if in_require_block and line == ")":
                in_require_block = False
                continue

            package_name = None
            if in_require_block:
                # In block, each line is expected to be: <module_path> <version> [optional comment]
                tokens = line.split()
                if tokens:
                    package_name = tokens[0]
            elif line.startswith("require "):
                # Single-line require
                remainder = line[len("require ") :].strip()
                tokens = remainder.split()
                if tokens:
                    package_name = tokens[0]

            # In Go, the import path is the same as the package name (no transformation needed)
            if package_name:
                result[package_name] = [package_name]

        logger and logger.debug(f"Go imports resolved: found {len(result)} packages")
        return result

    def resolve_package_imports(self, package_name, logger=None, **kwargs):
        """
        Resolve a single package name to its import names

        For Go packages, the import name is the same as the package name

        Args:
            package_name (str): Name of the package
            logger (Logger): Optional logger instance
            **kwargs: Additional resolver-specific parameters

        Returns:
            list: List of possible import names for the package
        """
        # In Go, the import path is the same as the package name
        return [package_name]
