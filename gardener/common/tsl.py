"""
Compatibility wrapper around tree-sitter parser factories

Provides get_parser, get_language, and USING_TSL_PACK flag
"""

try:
    from tree_sitter_language_pack import get_language, get_parser

    USING_TSL_PACK = True
except ImportError:
    try:
        from tree_sitter_languages import get_language, get_parser

        USING_TSL_PACK = False
    except ImportError as exc:
        raise ImportError(
            "Unable to import tree-sitter parser backends. Install tree-sitter-language-pack "
            "or tree_sitter_languages to enable parsing."
        ) from exc

__all__ = ["get_parser", "get_language", "USING_TSL_PACK"]
