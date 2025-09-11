"""
Resolver for JSON-based package manifests (package.json)
"""

import json

from gardener.common.secure_file_ops import FileOperationError
from gardener.package_metadata.name_resolvers.base import BaseResolver


class JsonManifestResolver(BaseResolver):
    """
    Resolver for package.json-based ecosystems (JavaScript/TypeScript, Solidity)

    Handles both JS/TS and Solidity import resolution from package.json files
    """

    def __init__(self, mode="javascript", secure_file_ops=None):
        """
        Args:
            mode (str): Either 'javascript' or 'solidity'
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations
        """
        super().__init__(secure_file_ops)
        if mode not in ["javascript", "solidity"]:
            raise ValueError(f"Mode must be 'javascript' or 'solidity', got '{mode}'")
        self.mode = mode

    def resolve_from_manifest(self, manifest_path, logger=None, sections=None, **kwargs):
        """
        Resolve imports from package.json

        Args:
            manifest_path (str): Path to package.json
            logger (Logger): Optional logger instance
            sections (list): List of sections to process ('dependencies', etc.)
            **kwargs: Additional resolver-specific parameters

        Returns:
            dict: Mapping of {package_name: [import_names]}
        """
        sections = sections or ["dependencies"]
        logger and logger.debug(f"Resolving imports from package.json: {manifest_path}")

        try:
            data = self.safe_json_load(manifest_path)
        except FileOperationError as e:
            logger and logger.error(f"Failed to read {manifest_path}: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger and logger.error(f"Invalid JSON in {manifest_path}: {e}")
            return {}
        except Exception as e:
            logger and logger.error(f"Unexpected error reading {manifest_path}: {e}")
            return {}

        result = {}
        for section in sections:
            deps = data.get(section, {})
            if not isinstance(deps, dict):
                continue

            for dep_key, dep_value in deps.items():
                alias_note = ""
                alias_target = None

                if isinstance(dep_value, str) and dep_value.startswith("npm:"):
                    without_prefix = dep_value[len("npm:") :]
                    alias_target = without_prefix.split("@")[0]
                    alias_note = f"alias for '{alias_target}'"

                # For both JS/TS and Solidity, the import name is the package name
                # (no transformation needed)
                result[dep_key] = [dep_key]

                # Store alias info if needed
                if alias_note and self.mode == "javascript":
                    # For JavaScript/TypeScript, we might want to store the alias info
                    pass

        logger and logger.debug(f"{self.mode} imports resolved: found {len(result)} packages")
        return result

    def resolve_package_imports(self, package_name, logger=None, **kwargs):
        """
        Resolve a single package name to its import names

        For JavaScript/TypeScript/Solidity packages, the import name is typically
        the same as the package name

        Args:
            package_name (str): Name of the package
            logger (Logger): Optional logger instance
            **kwargs: Additional resolver-specific parameters

        Returns:
            list: List of possible import names for the package
        """
        # For JS/TS/Solidity, the import name is the same as the package name
        return [package_name]
