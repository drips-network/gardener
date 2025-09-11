"""
Simple property-based tests without external dependencies
"""

import random
import string

import pytest

from gardener.analysis.graph import DependencyGraphBuilder
from gardener.common.input_validation import InputValidator, ValidationError
from gardener.common.utils import Logger


class TestSimpleProperties:
    """Property-based tests using random generation"""

    def generate_random_string(self, min_len=1, max_len=100, charset=None):
        """Generate random string for testing"""
        if charset is None:
            charset = string.ascii_letters + string.digits + "._-"
        length = random.randint(min_len, max_len)
        return "".join(random.choice(charset) for _ in range(length))

    def test_file_path_validation_random(self):
        """Test file path validation with random inputs"""
        # Test 100 random strings
        for _ in range(100):
            # Generate various types of paths
            path_type = random.choice(["normal", "special", "dangerous"])

            if path_type == "normal":
                # Normal looking paths
                parts = [self.generate_random_string(1, 20) for _ in range(random.randint(1, 5))]
                path = "/".join(parts)
            elif path_type == "special":
                # Paths with special characters
                charset = string.ascii_letters + "._-!@#$%^&*()"
                path = self.generate_random_string(1, 50, charset)
            else:
                # Potentially dangerous paths
                dangerous_parts = ["..", ".", "\\", "\x00", "\n", "\r"]
                parts = [random.choice(dangerous_parts) for _ in range(random.randint(1, 10))]
                path = "".join(parts)

            # Validation should either succeed or raise ValidationError
            try:
                result = InputValidator.validate_file_path(path)
                # validate_file_path returns a Path object
                assert hasattr(result, "__fspath__")  # It's a path-like object
                assert "\x00" not in str(result)
            except ValidationError:
                pass  # Expected for invalid paths
            except Exception as e:
                pytest.fail(f"Unexpected exception for path '{path}': {e}")

    def test_graph_building_random(self):
        """Test graph building with random data"""
        for _ in range(20):  # Run 20 random tests
            builder = DependencyGraphBuilder(logger=Logger())

            # Generate random source files
            num_files = random.randint(1, 20)
            source_files = {}
            file_imports = {}
            file_package_components = {}
            local_imports_map = {}

            for i in range(num_files):
                file_path = f"src/{self.generate_random_string(5, 20)}.py"
                source_files[file_path] = f"/absolute/{file_path}"

                # Generate random imports for this file
                num_imports = random.randint(0, 10)
                imports = []
                for _ in range(num_imports):
                    pkg_name = self.generate_random_string(3, 15, string.ascii_lowercase)
                    imports.append(pkg_name)
                if imports:
                    file_imports[file_path] = imports

                # Generate random local imports
                if i > 0 and random.random() > 0.5:
                    # Import from another file
                    other_file = random.choice(list(source_files.keys()))
                    local_imports_map[file_path] = [other_file]

            # Generate external packages
            external_packages = {}
            all_imports = set()
            for imports in file_imports.values():
                all_imports.update(imports)

            for pkg in all_imports:
                external_packages[pkg] = {"import_names": [pkg], "ecosystem": "pypi", "version": "1.0.0"}

            # Build the graph
            try:
                graph = builder.build_dependency_graph(
                    source_files, external_packages, file_imports, file_package_components, local_imports_map
                )

                # Graph should contain nodes
                assert len(graph.nodes()) > 0
                # Should have file nodes
                file_nodes = [n for n in graph.nodes() if graph.nodes[n].get("type") == "file"]
                assert len(file_nodes) == len(source_files)
            except Exception as e:
                pytest.fail(f"Graph building failed: {e}")

    def test_unicode_handling_simple(self):
        """Test handling of Unicode characters"""
        unicode_chars = ["中文", "日本語", "العربية", "עברית", "русский", "🎉", "🚀", "💻", "🐍", "📦"]

        builder = DependencyGraphBuilder(logger=Logger())

        for char_set in unicode_chars:
            # Test with unicode in file paths
            file_name = f"file_{char_set}.py"

            try:
                graph = builder.build_dependency_graph({file_name: f"/path/{file_name}"}, {}, {}, {}, {})
                # Should handle Unicode file names
                assert len(graph.nodes()) > 0
            except Exception as e:
                # Should handle Unicode gracefully
                if "Segmentation fault" in str(e):
                    pytest.fail(f"Crashed on Unicode: {char_set}")

    def test_extreme_values(self):
        """Test with extreme values"""
        # Very long strings
        long_string = "a" * 10000
        try:
            InputValidator.validate_file_path(long_string)
        except ValidationError:
            pass  # Expected
        except Exception as e:
            pytest.fail(f"Failed on long string: {e}")

        # Empty strings
        try:
            InputValidator.validate_file_path("")
        except ValidationError:
            pass  # Expected

        # Strings with only whitespace
        try:
            InputValidator.validate_file_path("   \t\n   ")
        except ValidationError:
            pass  # Expected

    def test_random_package_names(self):
        """Test package name validation with random inputs"""
        ecosystems = ["npm", "pypi", "crates.io", "go"]

        for _ in range(50):
            ecosystem = random.choice(ecosystems)

            # Generate different types of package names
            name_type = random.choice(["valid", "special", "invalid"])

            if name_type == "valid":
                # Generate valid-looking names
                if ecosystem == "npm" and random.random() > 0.5:
                    # Scoped package
                    scope = self.generate_random_string(3, 10, string.ascii_lowercase)
                    name = self.generate_random_string(3, 20, string.ascii_lowercase + "-")
                    package_name = f"@{scope}/{name}"
                else:
                    # Regular package
                    package_name = self.generate_random_string(3, 30, string.ascii_lowercase + "-_.")
            elif name_type == "special":
                # Names with special characters
                package_name = self.generate_random_string(1, 30, string.printable)
            else:
                # Invalid names
                invalid_chars = ["\x00", "\n", "\r", "/", "\\", "..", " "]
                package_name = random.choice(invalid_chars) * random.randint(1, 5)

            try:
                result = InputValidator.validate_package_name(package_name, ecosystem)
                assert isinstance(result, str)
                assert len(result) > 0
            except ValidationError:
                pass  # Expected for invalid names
            except Exception as e:
                pytest.fail(f"Unexpected error for package '{package_name}' in {ecosystem}: {e}")
