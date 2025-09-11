"""
Robustness tests for malformed JavaScript manifests and related inputs
"""

import json
import tempfile
from pathlib import Path

import pytest

from gardener.treewalk.javascript import JavaScriptLanguageHandler

pytestmark = pytest.mark.security


def test_malformed_manifest_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        malformed_json_cases = [
            '{"name": "test", "dependencies": {',
            '{"name": "test", "dependencies": {"pkg": "1.0.0"',
            '{"dependencies": {"pkg": null}}',
            '{"dependencies": {"": "1.0.0"}}',
            '{"dependencies": {"\\x00pkg": "1.0.0"}}',
            '{"dependencies": ' + '{"a": "1"}' * 2000 + "}",
            '{"name": "' + "a" * 2000 + '"}',
            '\xff\xfe{"name": "test"}',
            '{"name": "test", "dependencies": {"pkg": {}}}',
        ]

        js_handler = JavaScriptLanguageHandler()
        for i, content in enumerate(malformed_json_cases):
            pkg_path = Path(tmpdir) / f"package_{i}.json"
            pkg_path.write_text(content)
            packages = {}
            try:
                js_handler.process_manifest(str(pkg_path), packages)
            except Exception as e:
                assert isinstance(e, (json.JSONDecodeError, ValueError, KeyError))
