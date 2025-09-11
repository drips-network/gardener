"""
Resolver for Rust package manifests (Cargo.toml)
"""

import toml

from gardener.common.secure_file_ops import FileOperationError
from gardener.package_metadata.name_resolvers.base import BaseResolver


class RustResolver(BaseResolver):
    """
    Resolver for Rust crates based on Cargo.toml

    Handles the conversion of package names to crate import names (dash to underscore)
    and processes aliased dependencies via the "package" field
    """

    def __init__(self, secure_file_ops=None):
        """
        Args:
            secure_file_ops (object): Optional SecureFileOps instance for safe file operations
        """
        super().__init__(secure_file_ops)

    def resolve_from_manifest(self, manifest_path, logger=None, sections=None, **kwargs):
        """
        Resolve imports from Cargo.toml

        Args:
            manifest_path (str): Path to Cargo.toml
            logger (Logger): Optional logger instance
            sections (list): List of sections to process (defaults to standard dependency sections)
            **kwargs: Additional resolver-specific parameters

        Returns:
            dict: Mapping of {package_name: [import_names]}
        """
        sections = sections or ["dependencies", "dev-dependencies", "build-dependencies"]
        logger and logger.debug(f"Resolving imports from Cargo.toml: {manifest_path}")

        try:
            content = self.read_file_content(manifest_path)
            cargo_data = toml.loads(content)
        except FileOperationError as e:
            logger and logger.error(f"Failed to read {manifest_path}: {e}")
            return {}
        except toml.TomlDecodeError as e:
            logger and logger.error(f"Invalid TOML in {manifest_path}: {e}")
            return {}
        except Exception as e:
            logger and logger.error(f"Unexpected error reading {manifest_path}: {e}")
            return {}

        result = {}

        for section in sections:
            deps = cargo_data.get(section, {})
            if not isinstance(deps, dict):
                continue

            for dep_key, dep_value in deps.items():
                # Transform hyphens to underscores per Rust crate naming rules
                import_names = []
                crate_name = dep_key.replace("-", "_")
                import_names.append(crate_name)

                if isinstance(dep_value, dict) and "package" in dep_value:
                    # When a dependency is renamed, code may import using the original crate name too
                    original_pkg = str(dep_value.get("package", "")).strip()
                    if original_pkg:
                        orig_import = original_pkg.replace("-", "_")
                        if orig_import not in import_names:
                            import_names.append(orig_import)

                # Unexpected formats are ignored gracefully
                result[dep_key] = import_names

        logger and logger.debug(f"Rust imports resolved: found {len(result)} packages")
        return result

    def resolve_package_imports(self, package_name, logger=None, **kwargs):
        """
        Resolve a single package name to its import names

        For Rust crates, transform hyphens to underscores per Rust crate naming rules

        Args:
            package_name (str): Name of the package
            logger (Logger): Optional logger instance
            **kwargs: Additional resolver-specific parameters

        Returns:
            list: List of possible import names for the package
        """
        # Transform hyphens to underscores per Rust crate naming rules
        crate_name = package_name.replace("-", "_")
        return [crate_name]
