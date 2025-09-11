"""
Tests for framework configuration
"""

import pytest

from gardener.common.framework_config import FRAMEWORK_CONFIGS, FrameworkAliasConfig, FrameworkAliasResolver


@pytest.mark.unit
def test_default_sveltekit_config_present():
    """
    SvelteKit config exists and has expected defaults
    """
    assert "sveltekit_lib" in FRAMEWORK_CONFIGS
    cfg = FRAMEWORK_CONFIGS["sveltekit_lib"]
    assert cfg.alias_prefix == "$lib/"
    assert cfg.base_path == "src/lib/"
    assert ".svelte" in cfg.extra_extensions
    assert cfg.is_conventional is True


@pytest.mark.unit
def test_resolver_initializes_with_defaults():
    """
    Resolver loads default framework configs
    """
    resolver = FrameworkAliasResolver()
    cfg = resolver.get_config_for_import("$lib/utils")
    assert cfg is not None and cfg.alias_prefix == "$lib/"


@pytest.mark.unit
@pytest.mark.parametrize(
    "module_str,expected",
    [
        ("$lib/utils", "src/lib/utils"),
        ("$lib/components/Button", "src/lib/components/Button"),
        ("$lib/stores/auth.js", "src/lib/stores/auth.js"),
    ],
)
def test_resolve_sveltekit_alias_paths(module_str, expected):
    """
    Resolves $lib/* to src/lib/*
    """
    resolver = FrameworkAliasResolver()
    assert resolver.resolve_framework_alias(module_str) == expected


@pytest.mark.unit
def test_get_extra_extensions_includes_svelte():
    """
    SvelteKit adds .svelte extension; non-framework returns []
    """
    resolver = FrameworkAliasResolver()
    assert ".svelte" in resolver.get_extra_extensions("$lib/Component")
    assert resolver.get_extra_extensions("react") == []


@pytest.mark.unit
def test_add_custom_framework_config_supports_nextjs():
    """
    Adding a Next.js @/ alias resolves to src/* paths
    """
    resolver = FrameworkAliasResolver()
    nextjs = FrameworkAliasConfig(
        alias_prefix="@/",
        base_path="src/",
        extra_extensions=[],
        is_conventional=True,
        description="Next.js @ alias convention",
    )
    resolver.add_framework_config("nextjs", nextjs)
    cfg = resolver.get_config_for_import("@/components/Header")
    assert cfg is not None and cfg.alias_prefix == "@/"
    assert resolver.resolve_framework_alias("@/components/Header") == "src/components/Header"


@pytest.mark.unit
def test_remove_framework_config_disables_resolution():
    """
    Removing a framework config stops alias resolution for that prefix
    """
    resolver = FrameworkAliasResolver()
    assert resolver.get_config_for_import("$lib/test") is not None
    resolver.remove_framework_config("sveltekit_lib")
    assert resolver.get_config_for_import("$lib/test") is None


@pytest.mark.unit
@pytest.mark.parametrize(
    "module_str",
    ["react", "express", "./relative/path", "../another/relative", "some-npm-package", "@scoped/package"],
)
def test_non_framework_imports_return_none(module_str):
    """
    Non-framework imports do not match any framework config
    """
    resolver = FrameworkAliasResolver()
    assert resolver.get_config_for_import(module_str) is None
    assert resolver.resolve_framework_alias(module_str) is None


@pytest.mark.unit
def test_custom_resolver_with_no_defaults():
    """
    Resolver can be initialized with custom-only configs
    """
    custom = {
        "custom": FrameworkAliasConfig(
            alias_prefix="~/~/",
            base_path="custom/path/",
            extra_extensions=[".custom"],
            is_conventional=False,
            description="Custom framework",
        )
    }
    resolver = FrameworkAliasResolver(configs=custom)
    assert resolver.get_config_for_import("$lib/test") is None
    cfg = resolver.get_config_for_import("~/~/module")
    assert cfg is not None and cfg.alias_prefix == "~/~/"
    assert resolver.resolve_framework_alias("~/~/module") == "custom/path/module"
