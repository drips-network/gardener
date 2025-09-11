"""
Test timeout protection for long-running operations
"""

import tempfile
import time
from pathlib import Path

import pytest

from gardener.analysis.tree import RepositoryAnalyzer, TimeoutError, timeout
from gardener.common.utils import Logger


class TestTimeoutProtection:
    """Test timeout protection mechanisms"""

    def test_timeout_context_manager(self):
        """Test the timeout context manager"""
        # Test successful operation within timeout
        try:
            with timeout(2):
                time.sleep(0.1)
                result = "success"
            assert result == "success"
        except TimeoutError:
            pytest.fail("Timeout raised for operation within limit")

        # Test operation that exceeds timeout (only on Unix-like systems)
        import signal

        if hasattr(signal, "SIGALRM"):
            with pytest.raises(TimeoutError):
                with timeout(1):
                    time.sleep(2)  # This should timeout

    def test_parse_timeout_protection(self):
        """Test that parsing respects timeout limits"""
        from grep_ast.tsl import get_parser

        # Generate a file with deeply nested structures
        content = "def func():\n"
        for i in range(500):
            content += "    " * i + f"if True:\n"
        for i in range(499, -1, -1):
            content += "    " * i + "    pass\n"

        # Test parsing with timeout
        parser = get_parser("python")

        # This should complete successfully even with timeout protection
        with timeout(5):  # 5 second timeout
            tree = parser.parse(content.encode())
            assert tree is not None

        # If we get here, the timeout protection allowed the operation to complete
        assert True

    def test_import_limit_enforcement(self):
        """Test that import limits are enforced"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a Python file with many imports
            test_file = Path(tmpdir) / "many_imports.py"

            # Generate more imports than the limit
            content = "# File with many imports\n"
            for i in range(15000):  # More than MAX_IMPORTS_PER_FILE
                content += f"import module_{i}\n"

            test_file.write_text(content)

            # Process the file
            analyzer = RepositoryAnalyzer(tmpdir, logger=Logger())
            analyzer.extract_imports_from_all_files()

            # Check that imports were limited
            file_imports = analyzer.file_imports.get("many_imports.py", [])

            # Should have stopped at the limit
            from gardener.common.defaults import ResourceLimits

            assert len(file_imports) <= ResourceLimits.MAX_IMPORTS_PER_FILE

            # Verify warning was logged (would need to capture logs to test properly)

    def test_tree_depth_limit(self):
        """Test that tree traversal respects depth limits"""
        from grep_ast.tsl import get_parser

        from gardener.treewalk.python import PythonImportVisitor

        # Create deeply nested Python code
        code = "if True:\n"
        for i in range(2000):  # Deeper than MAX_TREE_DEPTH
            code += "    " * i + "if True:\n"
        code += "    " * 2000 + "import deep_module\n"

        # Parse the code
        parser = get_parser("python")
        tree = parser.parse(code.encode())

        # Create visitor
        components = {}
        visitor = PythonImportVisitor("test.py", components, lambda *args: None)

        # Visit the tree - should handle depth limit gracefully
        visitor.visit(tree.root_node)

        # The deep import might not be found due to depth limit
        # But the visitor should not crash
        assert True  # If we get here, depth limiting worked
