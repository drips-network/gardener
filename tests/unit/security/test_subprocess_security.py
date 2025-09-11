"""
Test security fixes for subprocess execution
"""

import tempfile
from pathlib import Path

import pytest

from gardener.common.input_validation import InputValidator, ValidationError
from gardener.common.subprocess import SecureSubprocess, SubprocessSecurityError


class TestSecureSubprocess:
    """Test secure subprocess execution"""

    def test_validate_cwd_within_allowed_root(self):
        """Test that cwd must be within allowed root"""
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed_root = Path(tmpdir)
            secure = SecureSubprocess(allowed_root)

            # Valid cwd within allowed root
            subdir = allowed_root / "subdir"
            subdir.mkdir()
            validated = secure.validate_cwd(subdir)
            # Compare resolved paths to handle symlinks
            assert validated.resolve() == subdir.resolve()

            # Invalid cwd outside allowed root
            with pytest.raises(SubprocessSecurityError) as exc:
                secure.validate_cwd("/tmp")
            assert "outside allowed root" in str(exc.value)

    def test_validate_cwd_path_traversal(self):
        """Test that path traversal attempts are blocked"""
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed_root = Path(tmpdir)
            secure = SecureSubprocess(allowed_root)

            # Create a subdirectory
            subdir = allowed_root / "subdir"
            subdir.mkdir()

            # Try path traversal
            traversal_path = subdir / ".." / ".." / "etc"
            with pytest.raises(SubprocessSecurityError) as exc:
                secure.validate_cwd(traversal_path)
            assert "outside allowed root" in str(exc.value)

    def test_command_validation_blocks_dangerous_chars(self):
        """Test that dangerous shell characters are blocked"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secure = SecureSubprocess(tmpdir)

            # Test various dangerous patterns
            dangerous_commands = [
                ["echo", "test; rm -rf /"],  # Command separator
                ["echo", "test | cat /etc/passwd"],  # Pipe
                ["echo", "$(cat /etc/passwd)"],  # Command substitution
                ["echo", "test & background"],  # Background execution
                ["echo", "test\nrm -rf /"],  # Newline injection
            ]

            for cmd in dangerous_commands:
                with pytest.raises(SubprocessSecurityError) as exc:
                    secure.validate_command(cmd)
                assert "dangerous character" in str(exc.value)

    def test_safe_command_execution(self):
        """Test that safe commands can be executed"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secure = SecureSubprocess(tmpdir, timeout=5)

            # Simple safe command
            result = secure.run(["echo", "hello world"])
            assert result.returncode == 0
            assert "hello world" in result.stdout

    def test_timeout_enforcement(self):
        """Test that subprocess timeout is enforced"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secure = SecureSubprocess(tmpdir, timeout=1)

            # Command that would run forever
            with pytest.raises(SubprocessSecurityError) as exc:
                secure.run(["sleep", "10"])
            assert "exceeded timeout" in str(exc.value)

    def test_environment_sanitization(self):
        """Test that environment is properly sanitized"""
        with tempfile.TemporaryDirectory() as tmpdir:
            secure = SecureSubprocess(tmpdir)

            # Test that dangerous env vars are filtered
            dangerous_env = {
                "PATH": "/evil/path:/usr/bin",
                "LD_PRELOAD": "/evil/lib.so",
                "NODE_ENV": "production",  # This should be allowed
                "MALICIOUS": "value",
            }

            safe_env = secure.create_safe_env(dangerous_env)

            # Check allowed vars are present
            assert "NODE_ENV" in safe_env
            assert safe_env["NODE_ENV"] == "production"

            # Check dangerous vars are filtered
            assert "LD_PRELOAD" not in safe_env
            assert "MALICIOUS" not in safe_env

            # Check PATH is sanitized
            assert safe_env["PATH"] == "/usr/local/bin:/usr/bin:/bin"


class TestInputValidation:
    """Test input validation functions"""

    def test_validate_file_path_blocks_traversal(self):
        """Test that path traversal is blocked"""
        dangerous_paths = [
            "../../../etc/passwd",
            "/etc/passwd",
            "~/../../etc/passwd",
            "test/../../../etc/passwd",
            "test/..\\..\\..\\windows\\system32",
        ]

        for path in dangerous_paths:
            with pytest.raises(ValidationError):
                InputValidator.validate_file_path(path)

    def test_validate_file_path_blocks_special_chars(self):
        """Test that special characters are blocked"""
        dangerous_paths = [
            "test; rm -rf /",
            "test | cat /etc/passwd",
            "test$(whoami)",
            "test`id`",
            "test\0null",
        ]

        for path in dangerous_paths:
            with pytest.raises(ValidationError):
                InputValidator.validate_file_path(path)

    def test_validate_url_blocks_ssrf(self):
        """Test that SSRF attempts are blocked"""
        dangerous_urls = [
            "http://localhost/admin",
            "http://127.0.0.1:8080",
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal",
            "file:///etc/passwd",
        ]

        for url in dangerous_urls:
            with pytest.raises(ValidationError):
                InputValidator.validate_url(url)

    def test_validate_url_allows_safe_urls(self):
        """Test that safe URLs are allowed"""
        safe_urls = [
            "https://github.com/user/repo.git",
            "https://pypi.org/project/example/",
            "https://registry.npmjs.org/package",
        ]

        for url in safe_urls:
            validated = InputValidator.validate_url(url)
            assert validated == url

    def test_validate_git_url(self):
        """Test git URL validation"""
        # Valid git URLs
        valid_urls = [
            "https://github.com/user/repo.git",
            "git@github.com:user/repo.git",
            "git://github.com/user/repo.git",
        ]

        for url in valid_urls:
            validated = InputValidator.validate_git_url(url)
            assert validated == url

        # Invalid git URLs
        with pytest.raises(ValidationError):
            InputValidator.validate_git_url("ftp://example.com/repo.git")

    def test_validate_package_name(self):
        """Test package name validation"""
        # Valid package names
        assert InputValidator.validate_package_name("requests", "pypi") == "requests"
        assert InputValidator.validate_package_name("@angular/core", "npm") == "@angular/core"

        # Invalid package names
        with pytest.raises(ValidationError):
            InputValidator.validate_package_name("../../etc/passwd", "pypi")

        with pytest.raises(ValidationError):
            InputValidator.validate_package_name("test\0null", "npm")


pytestmark = pytest.mark.security
