"""
Alias configuration and unified resolver tests
"""

import json
import os
import tempfile

import pytest

from gardener.common.alias_config import AliasConfiguration, AliasRule, UnifiedAliasResolver


@pytest.mark.unit
def test_alias_rule_creation():
    rule1 = AliasRule(pattern="@utils/*", target="src/utils/*", priority=10, description="Utils alias")
    assert rule1.get_targets() == ["src/utils/*"]

    rule2 = AliasRule(pattern="shared/*", target=["../shared/*", "./src/shared/*"], priority=5)
    assert rule2.get_targets() == ["../shared/*", "./src/shared/*"]


@pytest.mark.unit
def test_add_custom_rules_sorted_by_priority():
    config = AliasConfiguration()
    config.add_custom_rule("@components/*", "src/components/*", priority=10)
    config.add_custom_rule("@utils", "src/utils", priority=5)
    config.add_custom_rule("@api/*", "src/api/*", priority=15)

    assert len(config.custom_rules) == 3
    assert [r.pattern for r in config.custom_rules] == ["@api/*", "@components/*", "@utils"]


@pytest.mark.unit
def test_from_ts_js_config():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        data = {
            "compilerOptions": {
                "baseUrl": "./src",
                "paths": {
                    "@components/*": ["components/*"],
                    "@utils/*": ["utils/*", "shared/utils/*"],
                    "@api": ["api/index.ts"],
                },
            }
        }
        json.dump(data, f)
        f.flush()
        try:
            config = AliasConfiguration.from_ts_js_config(f.name)
            assert config.base_url == "./src"
            assert len(config.ts_js_paths) == 3
            assert config.ts_js_paths["@components/*"] == ["components/*"]
            assert config.ts_js_paths["@utils/*"] == ["utils/*", "shared/utils/*"]
            assert config.ts_js_paths["@api"] == ["api/index.ts"]
        finally:
            os.unlink(f.name)


@pytest.mark.unit
def test_merge_configurations():
    config1 = AliasConfiguration()
    config1.base_url = "./src"
    config1.ts_js_paths = {"@components/*": ["components/*"]}
    config1.add_custom_rule("@utils", "utils", priority=5)

    config2 = AliasConfiguration()
    config2.ts_js_paths = {"@api/*": ["api/*"]}
    config2.add_custom_rule("@lib", "lib", priority=10)
    config2.extensions_to_try.append(".vue")

    config1.merge_with(config2)
    assert config1.base_url == "./src"
    assert len(config1.ts_js_paths) == 2
    assert len(config1.custom_rules) == 2
    assert ".vue" in config1.extensions_to_try
    assert [r.pattern for r in config1.custom_rules] == ["@lib", "@utils"]


@pytest.mark.unit
def test_unified_resolver_custom_rule_takes_precedence():
    repo_path = "/test/repo"
    files = {
        "src/components/Button.tsx": "/test/repo/src/components/Button.tsx",
        "src/components/Input.tsx": "/test/repo/src/components/Input.tsx",
        "src/utils/helpers.ts": "/test/repo/src/utils/helpers.ts",
        "src/utils/index.ts": "/test/repo/src/utils/index.ts",
        "src/api/index.ts": "/test/repo/src/api/index.ts",
        "src/lib/components/Card.svelte": "/test/repo/src/lib/components/Card.svelte",
        "shared/types.ts": "/test/repo/shared/types.ts",
    }
    cfg = AliasConfiguration()
    cfg.base_url = "src"
    cfg.ts_js_paths = {
        "@components/*": ["components/*"],
        "@utils/*": ["utils/*"],
        "@utils": ["utils/index.ts"],
        "@api": ["api/index.ts"],
        "@types": ["../shared/types.ts"],
    }
    cfg.add_custom_rule("utils", "src/utils", priority=20)
    resolver = UnifiedAliasResolver(cfg, repo_path, files)
    assert resolver.resolve("src/app.ts", "utils") == "src/utils/index.ts"


@pytest.mark.unit
def test_unified_resolver_ts_js_wildcard_and_exact():
    repo_path = "/test/repo"
    files = {
        "src/components/Button.tsx": "/test/repo/src/components/Button.tsx",
        "src/utils/helpers.ts": "/test/repo/src/utils/helpers.ts",
        "src/utils/index.ts": "/test/repo/src/utils/index.ts",
        "src/api/index.ts": "/test/repo/src/api/index.ts",
        "shared/types.ts": "/test/repo/shared/types.ts",
    }
    cfg = AliasConfiguration()
    cfg.base_url = "src"
    cfg.ts_js_paths = {
        "@components/*": ["components/*"],
        "@utils/*": ["utils/*"],
        "@utils": ["utils/index.ts"],
        "@api": ["api/index.ts"],
        "@types": ["../shared/types.ts"],
    }
    resolver = UnifiedAliasResolver(cfg, repo_path, files)
    assert resolver.resolve("src/app.ts", "@components/Button") == "src/components/Button.tsx"
    assert resolver.resolve("src/app.ts", "@utils/helpers") == "src/utils/helpers.ts"
    assert resolver.resolve("src/app.ts", "@utils") == "src/utils/index.ts"
    assert resolver.resolve("src/app.ts", "@api") == "src/api/index.ts"
    assert resolver.resolve("src/app.ts", "@types") == "shared/types.ts"


@pytest.mark.unit
def test_unified_resolver_framework_alias():
    repo_path = "/test/repo"
    files = {"src/lib/components/Card.svelte": "/test/repo/src/lib/components/Card.svelte"}
    cfg = AliasConfiguration()
    cfg.base_url = "src"
    resolver = UnifiedAliasResolver(cfg, repo_path, files)
    assert resolver.resolve("src/routes/+page.svelte", "$lib/components/Card") == "src/lib/components/Card.svelte"


@pytest.mark.unit
def test_pattern_matching_helpers():
    cfg = AliasConfiguration()
    resolver = UnifiedAliasResolver(cfg, "/r", {})
    assert resolver._matches_pattern("@components/Button", "@components/*")
    assert resolver._matches_pattern("@components", "@components/*")
    assert not resolver._matches_pattern("components/Button", "@components/*")
    assert resolver._matches_pattern("@utils", "@utils")
    assert not resolver._matches_pattern("@utils/helpers", "@utils")
    assert resolver._resolve_pattern_match("@components/Button", "@components/*", "components/*") == "components/Button"
    assert resolver._resolve_pattern_match("@utils/helpers", "@utils/*", "utils") == "utils/helpers"
    assert resolver._resolve_pattern_match("@api", "@api", "api/index.ts") == "api/index.ts"


@pytest.mark.unit
def test_non_matching_imports_return_none():
    repo_path = "/test/repo"
    files = {}
    cfg = AliasConfiguration()
    resolver = UnifiedAliasResolver(cfg, repo_path, files)
    assert resolver.resolve("src/app.ts", "react") is None
    assert resolver.resolve("src/app.ts", "express") is None
    assert resolver.resolve("src/app.ts", "./components") is None
    assert resolver.resolve("src/app.ts", "../utils") is None
    assert resolver.resolve("src/app.ts", "@unknown/path") is None


@pytest.mark.unit
def test_file_extension_resolution():
    repo_path = "/test/repo"
    files = {"src/components/Button.tsx": "/test/repo/src/components/Button.tsx"}
    cfg = AliasConfiguration()
    cfg.base_url = "src"
    cfg.ts_js_paths = {"@components/*": ["components/*"]}
    resolver = UnifiedAliasResolver(cfg, repo_path, files)
    assert resolver.resolve("src/app.ts", "@components/Button") == "src/components/Button.tsx"
    assert resolver.resolve("src/app.ts", "@components/NonExistent") is None
