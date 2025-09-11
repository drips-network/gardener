"""
Framework-specific configuration for alias resolution
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class FrameworkAliasConfig:
    """Configuration for framework-specific alias resolution"""

    # The alias prefix to match (e.g., '$lib' for SvelteKit)
    alias_prefix: str

    # The base path to resolve to (e.g., 'src/lib' for SvelteKit)
    base_path: str

    extra_extensions: List[str]

    # Whether this framework uses conventional paths
    is_conventional: bool = True

    # Optional package name if this alias resolves to an external package
    resolves_to_package: Optional[str] = None

    # Description for documentation
    description: str = ""


# Default framework configurations
FRAMEWORK_CONFIGS = {
    "sveltekit_lib": FrameworkAliasConfig(
        alias_prefix="$lib/",
        base_path="src/lib/",
        extra_extensions=[".svelte"],
        is_conventional=True,
        description="SvelteKit $lib alias convention",
    ),
    "sveltekit_app": FrameworkAliasConfig(
        alias_prefix="$app/",
        base_path="",  # Not used when resolves_to_package is set
        extra_extensions=[],
        is_conventional=True,
        resolves_to_package="@sveltejs/kit",
        description="SvelteKit $app virtual module",
    ),
    "sveltekit_env": FrameworkAliasConfig(
        alias_prefix="$env/",
        base_path="",  # Not used when resolves_to_package is set
        extra_extensions=[],
        is_conventional=True,
        resolves_to_package="@sveltejs/kit",
        description="SvelteKit $env virtual module",
    ),
}


class FrameworkAliasResolver:
    """Resolves framework-specific aliases based on configuration"""

    def __init__(self, configs=None):
        """
        Args:
            configs (dict): Optional custom framework configurations. If None, uses defaults
        """
        # Make a copy to avoid modifying the global FRAMEWORK_CONFIGS
        self.configs = configs or dict(FRAMEWORK_CONFIGS)

        # Build a map from alias prefix to config for faster lookup
        self.prefix_to_config = {}
        for _, config in self.configs.items():
            self.prefix_to_config[config.alias_prefix] = config

    def get_config_for_import(self, module_str):
        """
        Get the framework config that matches the given import string

        Args:
            module_str (str): The import string (e.g., '$lib/utils')

        Returns:
            The matching framework config, or None if no match
        """
        for prefix, config in self.prefix_to_config.items():
            if module_str.startswith(prefix):
                return config
        return None

    def resolve_framework_alias(self, module_str):
        """
        Resolve a framework alias to a conventional path

        Args:
            module_str (str): The import string with framework alias

        Returns:
            The resolved path, or None if not a framework alias
        """
        config = self.get_config_for_import(module_str)
        if not config:
            return None

        relative_part = module_str[len(config.alias_prefix) :]

        # Combine with the base path, handling trailing slashes properly
        base_path = config.base_path.rstrip("/")
        if relative_part:
            resolved_path = f"{base_path}/{relative_part}"
        else:
            resolved_path = base_path

        return resolved_path

    def get_extra_extensions(self, module_str):
        """
        Get additional file extensions to try for a given import

        Args:
            module_str (str): The import string

        Returns:
            List of extra extensions to try
        """
        config = self.get_config_for_import(module_str)
        return config.extra_extensions if config else []

    def get_package_name(self, module_str):
        """
        Get the package name if this alias resolves to an external package

        Args:
            module_str (str): The import string (e.g., '$app/environment')

        Returns:
            The package name if this is a package alias, None otherwise
        """
        config = self.get_config_for_import(module_str)
        if config and config.resolves_to_package:
            return config.resolves_to_package
        return None

    def add_framework_config(self, name, config):
        """
        Add or update a framework configuration

        Args:
            name (str): The framework name (e.g., 'sveltekit', 'nextjs')
            config (FrameworkAliasConfig): The framework configuration

        Example:
            resolver.add_framework_config('nextjs', FrameworkAliasConfig(
                alias_prefix='@/',
                base_path='src/',
                extra_extensions=[],
                is_conventional=True,
                description='Next.js @ alias convention'
            ))
        """
        self.configs[name] = config
        self.prefix_to_config[config.alias_prefix] = config

    def remove_framework_config(self, name):
        """
        Remove a framework configuration

        Args:
            name (str): The framework name to remove
        """
        if name in self.configs:
            config = self.configs[name]
            del self.configs[name]
            del self.prefix_to_config[config.alias_prefix]
