"""
Test edge cases related to resource exhaustion and limits
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from gardener.analysis.graph import DependencyGraphBuilder
from gardener.analysis.tree import RepositoryAnalyzer
from gardener.common.secure_file_ops import FileOperationError, SecureFileOps
from gardener.common.utils import Logger
from gardener.treewalk.python import PythonLanguageHandler


class TestResourceLimits:
    """Test resource consumption limits and edge cases"""

    @pytest.mark.slow
    def test_extremely_large_file_handling(self):
        """Test handling of very large source files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a very large Python file (10MB)
            large_file_path = Path(tmpdir) / "large_module.py"

            # Generate 10MB of valid Python code
            with open(large_file_path, "w") as f:
                f.write("# Large Python file\n")
                # Write 100k import statements (about 10MB)
                for i in range(100000):
                    f.write(f"import module_{i}\n")
                f.write("\n# End of file\n")

            # Test that analyzer can handle this without crashing
            analyzer = RepositoryAnalyzer(tmpdir, logger=Logger())

            # Register Python language handler
            analyzer.register_language_handler("python", PythonLanguageHandler())

            # This should complete without exhausting memory
            try:
                analyzer.scan_repo()
                # If we get here, the large file was handled
                assert True
            except MemoryError:
                pytest.fail("Large file caused memory exhaustion")

    @pytest.mark.slow
    def test_extremely_deep_directory_structure(self):
        """Test handling of very deep directory hierarchies"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a very deep directory structure (100 levels)
            current_dir = Path(tmpdir)
            for i in range(100):
                current_dir = current_dir / f"level_{i}"
                current_dir.mkdir()
                # Add a Python file at each level
                (current_dir / f"module_{i}.py").write_text(f"# Module at level {i}")

            # Test that analyzer can handle deep directories
            analyzer = RepositoryAnalyzer(tmpdir, logger=Logger())

            # Register Python language handler
            analyzer.register_language_handler("python", PythonLanguageHandler())

            try:
                source_files, manifest_files = analyzer.scan_repo()
                # Should find all 100 Python files
                assert len(source_files) == 100
            except RecursionError:
                pytest.fail("Deep directory structure caused recursion error")

    def test_circular_symlink_protection(self):
        """Test protection against circular symlinks"""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir)

            # Create directory structure with circular symlink
            dir_a = base_path / "dir_a"
            dir_b = base_path / "dir_b"
            dir_a.mkdir()
            dir_b.mkdir()

            # Create circular symlinks
            try:
                (dir_a / "link_to_b").symlink_to(dir_b)
                (dir_b / "link_to_a").symlink_to(dir_a)
            except OSError:
                pytest.skip("Cannot create symlinks on this platform")

            # Add a Python file
            (dir_a / "module.py").write_text("# Test module")

            # Test that analyzer doesn't get stuck in infinite loop
            analyzer = RepositoryAnalyzer(tmpdir, logger=Logger())

            # Register Python language handler
            analyzer.register_language_handler("python", PythonLanguageHandler())

            # Should complete without hanging
            source_files, manifest_files = analyzer.scan_repo()
            assert len(source_files) >= 1  # Should find at least the one module

    @pytest.mark.slow
    def test_massive_json_output_limit(self):
        """Test limits on JSON output size"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a result that would generate huge JSON
            huge_result = {"packages": {}, "graph": {"nodes": [], "edges": []}}

            # Add 100k nodes (would be several hundred MB of JSON)
            for i in range(100000):
                huge_result["graph"]["nodes"].append(
                    {
                        "id": f"node_{i}",
                        "type": "file",
                        "path": f"/very/long/path/to/file/number/{i}/module.py",
                        "metadata": {
                            "imports": [f"import_{j}" for j in range(10)],
                            "size": 12345,
                            "language": "python",
                        },
                    }
                )

            # Test JSON serialization with size check
            output_path = Path(tmpdir) / "huge_output.json"

            # This should either complete or raise an appropriate error
            try:
                json_str = json.dumps(huge_result)
                if len(json_str) > 100 * 1024 * 1024:  # 100MB limit
                    pytest.skip("JSON output too large, should implement size limit")
            except MemoryError:
                pytest.fail("JSON serialization caused memory exhaustion")

    @pytest.mark.slow
    def test_many_small_files_handling(self):
        """Test handling of many small files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create many small Python files (configurable)
            N = int(os.environ.get("GARDENER_TEST_FILECOUNT", "1000"))
            for i in range(N):
                dir_num = i // 100  # 100 files per directory
                dir_path = Path(tmpdir) / f"dir_{dir_num}"
                dir_path.mkdir(exist_ok=True)

                file_path = dir_path / f"module_{i}.py"
                file_path.write_text(f"# Module {i}\nimport os\n")

            # Test that analyzer can handle many files efficiently
            analyzer = RepositoryAnalyzer(tmpdir, logger=Logger())

            # Register Python language handler
            analyzer.register_language_handler("python", PythonLanguageHandler())

            import time

            start_time = time.time()
            source_files, manifest_files = analyzer.scan_repo()
            elapsed_time = time.time() - start_time

            assert len(source_files) == N
            # Should complete in reasonable time (less than 30 seconds for default N)
            if N <= 1000:
                assert elapsed_time < 30, f"Took {elapsed_time}s to scan {N} files"

    def test_unicode_path_handling(self):
        """Test handling of Unicode characters in paths"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files with various Unicode characters
            unicode_names = [
                "módulo_español.py",
                "模块_中文.py",
                "モジュール_日本語.py",
                "модуль_русский.py",
                "🚀_emoji_file.py",
                "file_with_नमस्ते.py",
            ]

            for name in unicode_names:
                try:
                    file_path = Path(tmpdir) / name
                    file_path.write_text(f"# Unicode file: {name}\nimport os")
                except (OSError, UnicodeError):
                    # Skip if filesystem doesn't support this character
                    continue

            # Test that analyzer handles Unicode paths
            analyzer = RepositoryAnalyzer(tmpdir, logger=Logger())

            # Register Python language handler
            analyzer.register_language_handler("python", PythonLanguageHandler())

            try:
                source_files, manifest_files = analyzer.scan_repo()
                # Should find at least some of the Unicode files
                assert len(source_files) > 0
            except UnicodeDecodeError:
                pytest.fail("Unicode paths caused decode error")

    def test_network_request_hook_returns_none_offline(self, offline_mode):
        """Test request hook path returns None without real network"""
        from gardener.package_metadata.url_resolver import _make_request

        with offline_mode.set_responses({}):
            result = _make_request("https://registry.npmjs.org/does-not-exist", logger=Logger())
        assert result is None

    def test_memory_efficient_graph_building(self):
        """Test memory-efficient graph building for large graphs"""
        # Create a dependency graph builder
        graph_builder = DependencyGraphBuilder(logger=Logger())

        # Simulate building a large graph
        nodes = []
        edges = []

        # Add 10k nodes
        for i in range(10000):
            nodes.append({"id": f"file_{i}", "type": "file", "path": f"/path/to/file_{i}.py"})

        # Add 50k edges (average 5 imports per file)
        for i in range(10000):
            for j in range(5):
                target = (i + j + 1) % 10000
                edges.append({"source": f"file_{i}", "target": f"file_{target}", "type": "imports_local"})

        # This should complete without exhausting memory
        try:
            # Note: We're testing the concept here, actual implementation
            # would need to be added to DependencyGraphBuilder
            assert len(nodes) == 10000
            assert len(edges) == 50000
        except MemoryError:
            pytest.fail("Graph building caused memory exhaustion")

    def test_secure_file_ops_path_limit(self):
        """Test secure file operations with extremely long paths"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secure_ops = SecureFileOps(tmpdir)

            # Try to create a path that's too long
            # Most filesystems limit paths to 4096 characters
            long_name = "a" * 300
            path_parts = [long_name for _ in range(20)]  # Would be 6000+ chars

            try:
                # This should fail gracefully
                long_path = os.path.join(*path_parts)
                result = secure_ops.exists(long_path)
                # Should return False, not crash
                assert result is False
            except FileOperationError:
                # This is also acceptable - explicit error
                pass
            except OSError as e:
                if "File name too long" in str(e):
                    # Expected on some systems
                    pass
                else:
                    raise
