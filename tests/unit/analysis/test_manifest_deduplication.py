"""
Unit tests for manifest deduplication functionality
"""

import json
import os
import tempfile

import pytest

from gardener.analysis.tree import RepositoryAnalyzer
from gardener.treewalk.javascript import JavaScriptLanguageHandler


@pytest.mark.slow
def test_deduplicate_package_version_conflict():
    """Test that version conflicts are detected and resolved"""
    with tempfile.TemporaryDirectory() as repo_dir:
        # Create root package.json with lodash 4.17.21
        root_package = {"name": "my-app", "dependencies": {"lodash": "^4.17.21", "express": "^4.18.0"}}
        with open(os.path.join(repo_dir, "package.json"), "w") as f:
            json.dump(root_package, f)

        # Create subdirectory with another package.json with different lodash version
        sub_dir = os.path.join(repo_dir, "submodule")
        os.makedirs(sub_dir)
        sub_package = {"name": "my-submodule", "dependencies": {"lodash": "^3.10.1", "axios": "^1.0.0"}}
        with open(os.path.join(sub_dir, "package.json"), "w") as f:
            json.dump(sub_package, f)

        # Analyze with ALL_MANIFESTS strategy
        analyzer = RepositoryAnalyzer(
            repo_dir,
        )
        # Register JavaScript handler for package.json
        analyzer.register_language_handler("javascript", JavaScriptLanguageHandler())

        analyzer.scan_repo()
        packages = analyzer.process_manifest_files()

        # Check that lodash was deduplicated
        assert "lodash" in packages
        assert packages["lodash"]["ecosystem"] == "npm"

        # Check that version conflict was detected
        assert "version_conflicts" in packages["lodash"]
        assert len(packages["lodash"]["version_conflicts"]) == 1

        # Check that the higher version was chosen (4.17.21 > 3.10.1)
        assert packages["lodash"]["version"] == "^4.17.21"

        # Check that both manifests are tracked
        assert "found_in_manifests" in packages["lodash"]
        assert len(packages["lodash"]["found_in_manifests"]) == 2

        # Check that other packages were also found
        assert "express" in packages
        assert "axios" in packages


@pytest.mark.slow
def test_deduplicate_package_no_conflict():
    """Test deduplication when there's no version conflict"""
    with tempfile.TemporaryDirectory() as repo_dir:
        # Create root package.json
        root_package = {"name": "my-app", "dependencies": {"react": "^18.2.0"}}
        with open(os.path.join(repo_dir, "package.json"), "w") as f:
            json.dump(root_package, f)

        # Create subdirectory with same react version
        sub_dir = os.path.join(repo_dir, "components")
        os.makedirs(sub_dir)
        sub_package = {"name": "my-components", "dependencies": {"react": "^18.2.0"}}
        with open(os.path.join(sub_dir, "package.json"), "w") as f:
            json.dump(sub_package, f)

        # Analyze with ALL_MANIFESTS strategy
        analyzer = RepositoryAnalyzer(
            repo_dir,
        )
        # Register JavaScript handler for package.json
        analyzer.register_language_handler("javascript", JavaScriptLanguageHandler())

        analyzer.scan_repo()
        packages = analyzer.process_manifest_files()

        # Check that react was found
        assert "react" in packages

        # Check that no version conflicts were detected
        assert "version_conflicts" not in packages["react"]

        # Check that both manifests are tracked
        assert "found_in_manifests" in packages["react"]
        assert len(packages["react"]["found_in_manifests"]) == 2


def test_version_conflict_resolution_strategies():
    """Test various version conflict resolution strategies"""
    analyzer = RepositoryAnalyzer("/tmp")  # Dummy path

    # Test workspace dependency resolution
    assert analyzer._resolve_version_conflict("workspace:*", "^1.0.0") == "^1.0.0"
    assert analyzer._resolve_version_conflict("^1.0.0", "workspace:*") == "^1.0.0"

    # Test latest/* resolution
    assert analyzer._resolve_version_conflict("latest", "^2.0.0") == "^2.0.0"
    assert analyzer._resolve_version_conflict("*", "3.0.0") == "3.0.0"

    # Test semantic version comparison
    assert analyzer._resolve_version_conflict("^1.0.0", "^2.0.0") == "^2.0.0"
    assert analyzer._resolve_version_conflict("3.2.1", "3.1.9") == "3.2.1"
    assert analyzer._resolve_version_conflict("1.0.10", "1.0.9") == "1.0.10"

    # Test range vs exact version
    assert analyzer._resolve_version_conflict("^1.0.0", "1.0.5") == "1.0.5"
    assert analyzer._resolve_version_conflict("~2.0.0", "2.0.0") == "2.0.0"


def test_parse_semver():
    """Test semantic version parsing"""
    analyzer = RepositoryAnalyzer("/tmp")  # Dummy path

    # Test basic versions
    assert analyzer._parse_semver("1.2.3") == (1, 2, 3)
    assert analyzer._parse_semver("10.20.30") == (10, 20, 30)

    # Test with prefixes
    assert analyzer._parse_semver("^1.2.3") == (1, 2, 3)
    assert analyzer._parse_semver("~4.5.6") == (4, 5, 6)
    assert analyzer._parse_semver(">=7.8.9") == (7, 8, 9)

    # Test with pre-release
    assert analyzer._parse_semver("1.2.3-beta") == (1, 2, 3)
    assert analyzer._parse_semver("1.2.3-rc.1") == (1, 2, 3)

    # Test invalid versions
    assert analyzer._parse_semver("latest") is None
    assert analyzer._parse_semver("1.2") is None
    assert analyzer._parse_semver("invalid") is None


@pytest.mark.slow
def test_get_conflict_summary():
    """Test getting a summary of all conflicts"""
    with tempfile.TemporaryDirectory() as repo_dir:
        # Create multiple package.json files with conflicts
        root_package = {"name": "root", "dependencies": {"lodash": "^4.0.0", "moment": "^2.29.0"}}
        with open(os.path.join(repo_dir, "package.json"), "w") as f:
            json.dump(root_package, f)

        # Create first subdirectory
        sub1_dir = os.path.join(repo_dir, "module1")
        os.makedirs(sub1_dir)
        sub1_package = {
            "name": "module1",
            "dependencies": {"lodash": "^3.0.0", "moment": "^2.29.0"},  # Same version, no conflict
        }
        with open(os.path.join(sub1_dir, "package.json"), "w") as f:
            json.dump(sub1_package, f)

        # Create second subdirectory
        sub2_dir = os.path.join(repo_dir, "module2")
        os.makedirs(sub2_dir)
        sub2_package = {
            "name": "module2",
            "dependencies": {"lodash": "^5.0.0", "react": "^18.0.0"},  # Another different version
        }
        with open(os.path.join(sub2_dir, "package.json"), "w") as f:
            json.dump(sub2_package, f)

        # Analyze
        analyzer = RepositoryAnalyzer(
            repo_dir,
        )
        # Register JavaScript handler for package.json
        analyzer.register_language_handler("javascript", JavaScriptLanguageHandler())

        analyzer.scan_repo()
        analyzer.process_manifest_files()

        # Get conflict summary
        conflicts = analyzer.get_conflict_summary()

        # Check lodash has conflicts
        assert "lodash" in conflicts
        assert conflicts["lodash"]["resolved_version"] == "^5.0.0"  # Highest version
        assert len(conflicts["lodash"]["conflicts"]) == 2  # Two conflicts recorded
        assert len(conflicts["lodash"]["found_in_manifests"]) == 3  # Found in 3 files

        # Check moment has no conflicts
        assert "moment" not in conflicts

        # Check react has no conflicts (only in one manifest)
        assert "react" not in conflicts
