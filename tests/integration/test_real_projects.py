"""
Integration tests against real project structures
"""

import os
import tempfile
from pathlib import Path

from gardener.analysis.main import run_analysis as analyze_repository


class TestRealProjects:
    """Test analysis against real-world project structures"""

    def create_minimal_python_project(self, root_dir):
        """Create a minimal Python project structure"""
        # Create project structure
        (root_dir / "src").mkdir()
        (root_dir / "tests").mkdir()

        # requirements.txt
        (root_dir / "requirements.txt").write_text("requests==2.28.0\n" "numpy>=1.20.0\n" "pytest\n")

        # Main module
        (root_dir / "src" / "__init__.py").touch()
        (root_dir / "src" / "main.py").write_text(
            "import requests\n"
            "import numpy as np\n"
            "from .utils import process_data\n"
            "\n"
            "def fetch_data(url):\n"
            "    response = requests.get(url)\n"
            "    return response.json()\n"
        )

        # Utils module
        (root_dir / "src" / "utils.py").write_text(
            "import numpy as np\n" "\n" "def process_data(data):\n" "    return np.array(data).mean()\n"
        )

        # Test file
        (root_dir / "tests" / "test_main.py").write_text(
            "import pytest\n"
            "from src.main import fetch_data\n"
            "\n"
            "def test_fetch_data():\n"
            "    # Test implementation\n"
            "    pass\n"
        )

    def create_minimal_javascript_project(self, root_dir):
        """Create a minimal JavaScript project structure"""
        # package.json
        package_json = {
            "name": "test-project",
            "version": "1.0.0",
            "dependencies": {"express": "^4.18.0", "lodash": "^4.17.21"},
            "devDependencies": {"jest": "^29.0.0"},
        }

        import json

        (root_dir / "package.json").write_text(json.dumps(package_json, indent=2))

        # Source files
        (root_dir / "index.js").write_text(
            "const express = require('express');\n"
            "const _ = require('lodash');\n"
            "const { processData } = require('./utils');\n"
            "\n"
            "const app = express();\n"
            "\n"
            "app.get('/', (req, res) => {\n"
            "    const data = processData([1, 2, 3, 4, 5]);\n"
            "    res.json({ result: data });\n"
            "});\n"
        )

        (root_dir / "utils.js").write_text(
            "const _ = require('lodash');\n"
            "\n"
            "function processData(arr) {\n"
            "    return _.mean(arr);\n"
            "}\n"
            "\n"
            "module.exports = { processData };\n"
        )

    def test_python_project_analysis(self):
        """Test analysis of a Python project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.create_minimal_python_project(root)

            # Change to project directory to avoid absolute path issues
            original_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Analyze the project
                result = analyze_repository(".", verbose=False)

                # Verify results
                assert result is not None
                assert "external_packages" in result
                assert "dependency_graph" in result

                # Check that external packages were found
                packages = result["external_packages"]
                assert "requests" in packages
                assert "numpy" in packages
                assert "pytest" in packages

                # Check graph structure
                graph = result["dependency_graph"]
                assert "nodes" in graph
                assert "links" in graph

                # Verify file nodes exist
                nodes = graph["nodes"]
                file_nodes = [n for n in nodes if n["type"] == "file"]
                assert len(file_nodes) >= 3  # main.py, utils.py, test_main.py

                # Verify package nodes exist
                package_nodes = [n for n in nodes if n["type"] == "package"]
                assert len(package_nodes) >= 3  # requests, numpy, pytest

                # Verify edges exist
                edges = graph["links"]
                assert len(edges) > 0

                # Check for imports
                imports_edges = [e for e in edges if e["type"] == "imports_package"]
                assert len(imports_edges) > 0

            finally:
                os.chdir(original_cwd)

    def test_javascript_project_analysis(self):
        """Test analysis of a JavaScript project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self.create_minimal_javascript_project(root)

            # Change to project directory
            original_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Analyze the project
                result = analyze_repository(".", verbose=False)

                # Verify results
                assert result is not None
                assert "external_packages" in result

                # Check packages
                packages = result["external_packages"]
                assert "express" in packages
                assert "lodash" in packages

                # Check graph
                graph = result["dependency_graph"]
                nodes = graph["nodes"]

                # Verify JavaScript files were found
                file_nodes = [n for n in nodes if n["type"] == "file"]
                js_files = [n for n in file_nodes if n["id"].endswith(".js")]
                assert len(js_files) >= 2  # index.js, utils.js

            finally:
                os.chdir(original_cwd)

    def test_mixed_language_project(self):
        """Test analysis of a project with multiple languages"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create both Python and JavaScript components
            self.create_minimal_python_project(root)
            self.create_minimal_javascript_project(root)

            # Change to project directory
            original_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Analyze the project
                result = analyze_repository(".", verbose=False)

                # Should find packages from both ecosystems
                packages = result["external_packages"]

                # Python packages
                assert "requests" in packages
                assert "numpy" in packages

                # JavaScript packages
                assert "express" in packages
                assert "lodash" in packages

                # Check that both types of files were analyzed
                graph = result["dependency_graph"]
                nodes = graph["nodes"]
                file_nodes = [n for n in nodes if n["type"] == "file"]

                py_files = [n for n in file_nodes if n["id"].endswith(".py")]
                js_files = [n for n in file_nodes if n["id"].endswith(".js")]

                assert len(py_files) > 0
                assert len(js_files) > 0

            finally:
                os.chdir(original_cwd)

    def test_empty_project(self):
        """Test handling of empty project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                # Analyze empty directory
                result = analyze_repository(".", verbose=False)

                # Should handle gracefully
                assert result is not None
                assert result["external_packages"] == {}
                # Empty projects might not have dependency_graph key
                if "dependency_graph" in result:
                    assert len(result["dependency_graph"].get("nodes", [])) == 0
                    assert len(result["dependency_graph"].get("links", [])) == 0

            finally:
                os.chdir(original_cwd)

    def test_project_with_local_imports_only(self):
        """Test project with only local imports"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create Python files with only local imports
            (root / "main.py").write_text(
                "from utils import helper\n"
                "from lib.core import process\n"
                "\n"
                "def main():\n"
                "    return helper() + process()\n"
            )

            (root / "utils.py").write_text("def helper():\n" "    return 42\n")

            (root / "lib").mkdir()
            (root / "lib" / "__init__.py").touch()
            (root / "lib" / "core.py").write_text("def process():\n" "    return 100\n")

            original_cwd = os.getcwd()
            os.chdir(tmpdir)

            try:
                result = analyze_repository(".", verbose=False)

                # Should have no external packages
                assert result["external_packages"] == {}

                # But should have file nodes and local import edges
                graph = result["dependency_graph"]
                nodes = graph["nodes"]
                edges = graph["links"]

                file_nodes = [n for n in nodes if n["type"] == "file"]
                assert len(file_nodes) >= 3

                local_edges = [e for e in edges if e["type"] == "imports_local"]
                assert len(local_edges) > 0

            finally:
                os.chdir(original_cwd)
