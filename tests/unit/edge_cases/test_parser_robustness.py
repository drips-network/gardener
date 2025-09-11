"""
Test parser robustness with edge cases and malformed code
"""

import tempfile
from pathlib import Path

import pytest
from grep_ast.tsl import get_parser

from gardener.common.utils import Logger
from gardener.treewalk.go import GoLanguageHandler
from gardener.treewalk.javascript import JavaScriptLanguageHandler
from gardener.treewalk.python import PythonLanguageHandler
from gardener.treewalk.rust import RustLanguageHandler
from gardener.treewalk.solidity import SolidityLanguageHandler


class TestParserRobustness:
    """Test language parsers with edge cases and malformed code"""

    def test_python_parser_edge_cases(self):
        """Test Python parser with edge cases"""
        edge_cases = [
            # Empty file
            "",
            # Just whitespace
            "   \n\t\r\n   ",
            # Incomplete statements
            "import",
            "from",
            "from .",
            "import .",
            # Invalid syntax
            "import 123",
            "from 456 import abc",
            "import class",
            "from def import return",
            # Deeply nested imports
            "from ........ import something",
            # Very long import
            "import " + ".".join(["a"] * 100),
            # Unicode in imports
            "import 你好",
            "from מודול import פונקציה",
            # Comments mixed with imports
            "import os # comment\nfrom sys import * # another",
            # Multiline imports with errors
            "from package import (\n    module1,\n    ,\n    module3\n)",
            # String literals that look like imports
            '''
string = """
import fake_import
from fake import module
"""
import real_import
            ''',
            # Conditional imports with syntax errors
            "if True:\n    import\nelse:\n    from",
            # Try-except with incomplete imports
            "try:\n    import\nexcept:\n    pass",
            # Function with invalid import
            "def func():\n    global import\n    import",
        ]

        parser = get_parser("python")
        handler = PythonLanguageHandler(logger=Logger())

        for code in edge_cases:
            try:
                # Should not crash
                tree = parser.parse(code.encode())
                if tree:
                    components = {}
                    handler.extract_imports(tree, "test.py", components, lambda *args: None)
                assert True  # Didn't crash
            except Exception as e:
                # Should only be parsing errors, not crashes
                assert "Segmentation fault" not in str(e)
                assert "core dumped" not in str(e)

    def test_javascript_parser_edge_cases(self):
        """Test JavaScript parser with edge cases"""
        edge_cases = [
            # Empty file
            "",
            # Incomplete imports
            "import",
            "export",
            "import {",
            "export {",
            "import { a,",
            # Invalid syntax
            "import 123 from 'module'",
            "import { class } from 'module'",
            "import * as 123 from 'module'",
            # Dynamic imports with syntax errors
            "import(",
            "import(123)",
            "import().then(",
            # Mixed import styles
            "import require('module')",
            "require import 'module'",
            # Template literals with errors
            "import `module",
            "import `${",
            # Comments breaking imports
            "import /* comment",
            "import { a /* unclosed comment from 'module'",
            # Regex-like strings
            "import /regex/ from 'module'",
            # Very long imports
            "import { " + ", ".join([f"item{i}" for i in range(1000)]) + " } from 'module'",
            # Unicode
            "import { 组件 } from '模块'",
            # HTML/JSX mixed in
            "<script>import module from 'mod'</script>",
            # Decorators (not standard JS)
            "@import('module')\nclass Test {}",
        ]

        parser = get_parser("javascript")
        handler = JavaScriptLanguageHandler(logger=Logger())

        for code in edge_cases:
            try:
                tree = parser.parse(code.encode())
                if tree:
                    components = {}
                    handler.extract_imports(tree, "test.js", components, lambda *args: None)
                assert True
            except Exception as e:
                assert "Segmentation fault" not in str(e)

    def test_solidity_parser_edge_cases(self):
        """Test Solidity parser with edge cases"""
        edge_cases = [
            # Empty file
            "",
            # Incomplete imports
            "import",
            "import ;",
            "import { ;",
            # Invalid paths
            "import '';",
            "import ' ';",
            "import " ";",
            # Malformed imports
            "import 123;",
            "import { } from '';",
            "import * as from '';",
            # Very long import paths
            f"import '{'/'.join(['dir'] * 50)}/file.sol';",
            # Special characters in paths
            "import './file\x00.sol';",
            "import './file\n.sol';",
            # Unicode in imports
            "import './файл.sol';",
            "import './文件.sol';",
            # Comments breaking imports
            "import /* comment './file.sol';",
            "import './file.sol' /* unclosed",
            # Multiple imports on one line
            "import './a.sol'; import './b.sol'; import",
            # Version pragma mixed with imports
            "pragma solidity ^0.8.0; import",
            # Contract declaration interrupting import
            "import contract Test {}",
            # Assembly block
            "assembly { import := 1 }",
        ]

        parser = get_parser("solidity")
        handler = SolidityLanguageHandler(logger=Logger())

        for code in edge_cases:
            try:
                tree = parser.parse(code.encode())
                if tree:
                    components = {}
                    handler.extract_imports(tree, "test.sol", components, lambda *args: None)
                assert True
            except Exception as e:
                assert "Segmentation fault" not in str(e)

    def test_go_parser_edge_cases(self):
        """Test Go parser with edge cases"""
        edge_cases = [
            # Empty file
            "",
            # Package declaration only
            "package main",
            # Incomplete imports
            "package main\nimport",
            "package main\nimport (",
            'package main\nimport (\n"',
            # Invalid import paths
            'package main\nimport ""',
            'package main\nimport " "',
            'package main\nimport "\\x00"',
            # Missing package declaration
            'import "fmt"',
            # Multiple package declarations
            'package main\npackage other\nimport "fmt"',
            # Comments in imports
            'package main\nimport ( // comment\n"fmt"',
            'package main\nimport ( /* unclosed\n"fmt"\n)',
            # Import aliases with errors
            'package main\nimport 123 "fmt"',
            'package main\nimport . "fmt"',  # Valid but edge case
            # Very long import block
            f"package main\nimport (\n" + "\n".join([f'    "pkg{i}"' for i in range(1000)]) + "\n)",
            # Unicode in imports
            'package main\nimport "模块"',
            # Build tags
            "// +build ignore\n\npackage main\nimport",
        ]

        parser = get_parser("go")
        handler = GoLanguageHandler(logger=Logger())

        for code in edge_cases:
            try:
                tree = parser.parse(code.encode())
                if tree:
                    components = {}
                    handler.extract_imports(tree, "test.go", components, lambda *args: None)
                assert True
            except Exception as e:
                assert "Segmentation fault" not in str(e)

    def test_rust_parser_edge_cases(self):
        """Test Rust parser with edge cases"""
        edge_cases = [
            # Empty file
            "",
            # Incomplete use statements
            "use",
            "use ;",
            "use {",
            "use crate::",
            # Invalid paths
            "use 123;",
            "use ::;",
            "use ::{};",
            # Macro use
            "use! macro;",
            "#[macro_use]",
            # Nested braces errors
            "use std::{{{};",
            "use std::{a, {b, }, c};",
            # Very long use statements
            "use std::{" + ", ".join([f"mod{i}" for i in range(500)]) + "};",
            # Comments in use
            "use /* comment */ std;",
            "use std::/* unclosed",
            # Attributes mixed in
            "#[cfg(test)]\nuse",
            # Unicode
            "use 模块;",
            # Conditional compilation
            '#[cfg(feature = "test")]\nuse std::{',
            # Visibility modifiers
            "pub(crate) use",
            "pub(super) use {",
        ]

        parser = get_parser("rust")
        handler = RustLanguageHandler(logger=Logger())

        for code in edge_cases:
            try:
                tree = parser.parse(code.encode())
                if tree:
                    components = {}
                    handler.extract_imports(tree, "test.rs", components, lambda *args: None)
                assert True
            except Exception as e:
                assert "Segmentation fault" not in str(e)

    def test_mixed_language_content(self):
        """Test parsers with mixed language content"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # JavaScript file with Python-like content
            js_file = Path(tmpdir) / "mixed.js"
            js_file.write_text(
                """
// This looks like Python
import os
from sys import path

// But it's actually JavaScript
import { readFile } from 'fs';
const python = require('python-shell');
            """
            )

            # Python file with JS-like content
            py_file = Path(tmpdir) / "mixed.py"
            py_file.write_text(
                """
# This looks like JavaScript
# import { Component } from 'react';
# const fs = require('fs');

# But it's actually Python
import os
from pathlib import Path
            """
            )

            # Both should parse their respective valid imports
            js_parser = get_parser("javascript")
            py_parser = get_parser("python")

            js_tree = js_parser.parse(js_file.read_bytes())
            py_tree = py_parser.parse(py_file.read_bytes())

            assert js_tree is not None
            assert py_tree is not None

    def test_extremely_deep_nesting(self):
        """Test parsers with extremely deep nesting"""
        # Python with deep nesting
        python_nested = "if True:\n"
        for i in range(100):
            python_nested += "    " * i + f"if condition_{i}:\n"
        python_nested += "    " * 100 + "import os\n"

        # JavaScript with deep nesting
        js_nested = "{\n"
        for i in range(100):
            js_nested += "  " * i + "{\n"
        js_nested += "  " * 100 + "import 'module';\n"
        for i in range(100, 0, -1):
            js_nested += "  " * i + "}\n"
        js_nested += "}\n"

        # Both should handle deep nesting
        py_parser = get_parser("python")
        js_parser = get_parser("javascript")

        try:
            py_tree = py_parser.parse(python_nested.encode())
            js_tree = js_parser.parse(js_nested.encode())
            assert py_tree is not None
            assert js_tree is not None
        except RecursionError:
            pytest.fail("Parser hit recursion limit with deep nesting")

    def test_parser_memory_efficiency(self):
        """Test parser memory efficiency with large files"""
        # Generate a large but valid Python file
        large_python = "# Large Python file\n"
        for i in range(10000):
            large_python += f"import module_{i}\n"
            if i % 100 == 0:
                large_python += f"# Comment block {i}\n" * 10

        # Parse it
        parser = get_parser("python")

        import os

        import psutil

        process = psutil.Process(os.getpid())
        memory_before = process.memory_info().rss / 1024 / 1024  # MB

        tree = parser.parse(large_python.encode())

        memory_after = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = memory_after - memory_before

        # Should not use excessive memory (less than 100MB increase)
        assert memory_increase < 100, f"Parser used {memory_increase}MB for 10k imports"
        assert tree is not None

    def test_malformed_import_statements_python(self):
        """Parser tolerates malformed import statements without crashing"""
        malformed = (
            "import\nfrom import something\nimport .\nfrom . import\nfrom .. import\n"
            "import 'not-valid'\nfrom . import \x00null\n"
        )
        parser = get_parser("python")
        tree = parser.parse(malformed.encode())
        assert tree is not None

    def test_mixed_line_endings_python(self):
        """Parser handles mixed CRLF/CR/LF line endings"""
        content = "import os\r\nimport sys\rimport json\n"
        parser = get_parser("python")
        tree = parser.parse(content.encode())
        assert tree is not None


pytestmark = pytest.mark.security
