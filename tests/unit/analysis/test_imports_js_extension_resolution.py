from gardener.analysis.imports import LocalImportResolver
from gardener.common.alias_config import AliasConfiguration, UnifiedAliasResolver


def test_relative_js_resolution_uses_alias_extensions_when_available(tmp_path):
    """
    LocalImportResolver should consult alias configuration extensions for relative imports
    """
    # Simulate a tiny repo structure in-memory via source_files map
    repo_path = str(tmp_path)

    # Create files on disk to mirror source map (not strictly required for source_map lookups)
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'main.js').write_text("import './foo'\n")
    (tmp_path / 'src' / 'foo.customx').write_text("export const x = 1\n")

    source_files = {
        'src/main.js': {
            'absolute_path': str(tmp_path / 'src' / 'main.js'),
            'language': 'javascript',
        },
        'src/foo.customx': {
            'absolute_path': str(tmp_path / 'src' / 'foo.customx'),
            'language': 'javascript',
        },
    }

    # Configure alias resolver with a custom extension so we can observe preference
    cfg = AliasConfiguration()
    # Prepend a custom extension to ensure it is tried before defaults
    cfg.extensions_to_try = ['.customx', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.json']
    resolver = UnifiedAliasResolver(config=cfg, repo_path=repo_path, source_files=source_files, logger=None)

    lir = LocalImportResolver(
        repo_path=repo_path,
        source_files=source_files,
        alias_resolver=resolver,
        js_ts_base_url=None,
        js_ts_path_aliases=None,
        go_module_path=None,
        remappings=None,
        hardhat_remappings=None,
        solidity_src_path=None,
        logger=None,
    )

    resolved = lir.resolve_js('src/main.js', './foo')
    assert resolved == 'src/foo.customx'
