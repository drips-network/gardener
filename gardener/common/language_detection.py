"""
Maps filenames to tree-sitter language keys
"""

import os

from gardener.treewalk.go import GoLanguageHandler
from gardener.treewalk.javascript import JavaScriptLanguageHandler
from gardener.treewalk.python import PythonLanguageHandler
from gardener.treewalk.rust import RustLanguageHandler
from gardener.treewalk.solidity import SolidityLanguageHandler
from gardener.treewalk.typescript import TypeScriptLanguageHandler
from gardener.common.tsl import USING_TSL_PACK


def _build_parser_map():
    """
    Build an extension → language map using Gardener's handlers

    Returns:
        Dict mapping file extensions (with dot) or basenames to language keys
    """
    handlers = {
        "python": PythonLanguageHandler,
        "javascript": JavaScriptLanguageHandler,
        "typescript": TypeScriptLanguageHandler,
        "go": GoLanguageHandler,
        "rust": RustLanguageHandler,
        "solidity": SolidityLanguageHandler,
    }

    mapping = {}
    for lang, Handler in handlers.items():
        try:
            exts = Handler(None).get_file_extensions()
        except Exception:
            exts = []
        for ext in exts:
            mapping[ext] = lang

    if mapping.get(".pyi") == "python":
        mapping.pop(".pyi", None)  # Don't treat .pyi type stubs as Python source

    # Prefer the dedicated Svelte grammar when the language pack is available; otherwise parse as JavaScript
    if ".svelte" in mapping:
        mapping[".svelte"] = "svelte" if USING_TSL_PACK else "javascript"

    return mapping


# Build mapping once at import
PARSERS = _build_parser_map()


def filename_to_lang(filename):
    """
    Return a tree-sitter language key for a given filename, or None

    Args:
        filename (str): Absolute or relative path to a file

    Returns:
        str|None: Language key compatible with get_parser, or None if unknown
    """
    basename = os.path.basename(filename)
    if basename in PARSERS:
        return PARSERS[basename]

    _, ext = os.path.splitext(basename)
    return PARSERS.get(ext)


__all__ = ["filename_to_lang", "PARSERS"]
