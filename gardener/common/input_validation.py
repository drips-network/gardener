"""
Validation functions for various types of user input
"""

import os
import re
from pathlib import Path
from urllib.parse import urlparse

from gardener.common.defaults import ResourceLimits


class ValidationError(Exception):
    """Raised when input validation fails"""

    pass


class InputValidator:
    """
    Provides input validation methods for security
    """

    # Pattern for validation
    GIT_URL_PATTERN = re.compile(r"^(https?://|git@|git://)" r"[a-zA-Z0-9.-]+[.:][a-zA-Z0-9./_-]+\.git$")

    # Security constants
    MAX_PATH_LENGTH = ResourceLimits.MAX_PATH_LENGTH
    MAX_URL_LENGTH = ResourceLimits.MAX_URL_LENGTH
    ALLOWED_URL_SCHEMES = {"https", "git"}
    ALLOWED_REGISTRY_DOMAINS = {
        "registry.npmjs.org",
        "pypi.org",
        "files.pythonhosted.org",
        "crates.io",
        "proxy.golang.org",
        "github.com",
        "gitlab.com",
        "bitbucket.org",
    }

    @classmethod
    def validate_file_path(cls, path, must_exist=False, base_dir=None):
        """
        Validate a file path for security issues

        Args:
            path (str or pathlib.Path): Path to validate
            must_exist (bool): Whether the path must exist
            base_dir (str or pathlib.Path): Optional base directory to ensure path stays within

        Returns:
            Validated Path object

        Raises:
            ValidationError: If validation fails
        """
        if not path:
            raise ValidationError("Path cannot be empty")

        path_str = str(path)

        if len(path_str) > cls.MAX_PATH_LENGTH:
            raise ValidationError(f"Path too long: {len(path_str)} > {cls.MAX_PATH_LENGTH}")

        if "\0" in path_str:
            raise ValidationError("Path contains null bytes")

        # For absolute paths without a base_dir, we need to be more careful
        # They're allowed for repository roots but need extra validation
        if os.path.isabs(path_str) and not base_dir:
            # Allow absolute paths that point to actual directories (for repo roots)
            # but still check for dangerous patterns
            if must_exist:
                # If must_exist is True, we'll validate it exists later
                # This is typically for repository roots
                pass
            else:
                # For non-root paths, absolute paths without base_dir are suspicious
                raise ValidationError(f"Absolute paths not allowed without base directory: {path}")

        suspicious_patterns = [
            "..",  # Parent directory traversal
            "~",  # Home directory expansion
            "$",  # Variable expansion
            "|",  # Pipe
            ";",  # Command separator
            "&",  # Background execution
            "<",
            ">",  # Redirection
            "`",  # Command substitution
            "\n",
            "\r",
            "\t",  # Whitespace attacks
        ]

        # These could be used to bypass filters if decoded later
        if "%" in path_str:
            dangerous_encoded = [
                "%2e%2e",  # URL-encoded ..
                "%00",  # URL-encoded null byte
                "%2f",  # URL-encoded /
                "%5c",  # URL-encoded \
            ]
            path_lower = path_str.lower()
            for pattern in dangerous_encoded:
                if pattern in path_lower:
                    raise ValidationError(f"Path contains potentially dangerous URL-encoded pattern: {pattern}")

        for pattern in suspicious_patterns:
            if pattern in path_str:
                raise ValidationError(f"Path contains suspicious pattern: {pattern}")

        # These can cause security issues through visual spoofing or confusion
        problematic_unicode = [
            "\u200b",  # Zero-width space
            "\u200c",  # Zero-width non-joiner
            "\u200d",  # Zero-width joiner
            "\ufeff",  # Zero-width no-break space
            "\u202e",  # Right-to-left override
            "\u202d",  # Left-to-right override
            "\u2060",  # Word joiner
        ]

        for char in problematic_unicode:
            if char in path_str:
                raise ValidationError(f"Path contains problematic Unicode character: U+{ord(char):04X}")

        path_obj = Path(path)

        # If base_dir provided, ensure path stays within it
        if base_dir:
            base_dir = Path(base_dir).resolve()
            try:
                # Resolve path relative to base_dir
                if path_obj.is_absolute():
                    resolved = path_obj.resolve()
                else:
                    resolved = (base_dir / path_obj).resolve()

                # Ensure resolved path is within base_dir
                resolved.relative_to(base_dir)
            except ValueError:
                raise ValidationError(f"Path '{path}' escapes base directory '{base_dir}'")
            path_obj = resolved

        if must_exist and not path_obj.exists():
            raise ValidationError(f"Path does not exist: {path}")

        return path_obj

    @classmethod
    def validate_url(cls, url, allowed_schemes=None, allowed_domains=None):
        """
        Validate a URL for security issues

        Args:
            url (str): URL to validate
            allowed_schemes (set): Optional set of allowed URL schemes
            allowed_domains (set): Optional set of allowed domains

        Returns:
            Validated URL string

        Raises:
            ValidationError: If validation fails
        """
        if not url:
            raise ValidationError("URL cannot be empty")

        if len(url) > cls.MAX_URL_LENGTH:
            raise ValidationError(f"URL too long: {len(url)} > {cls.MAX_URL_LENGTH}")

        try:
            parsed = urlparse(url)
        except Exception as e:
            raise ValidationError(f"Invalid URL format: {e}")

        # Validate scheme
        schemes = allowed_schemes or cls.ALLOWED_URL_SCHEMES
        if parsed.scheme not in schemes:
            raise ValidationError(f"URL scheme '{parsed.scheme}' not allowed. " f"Allowed schemes: {schemes}")

        # Validate domain if specified
        if allowed_domains and parsed.netloc:
            domain = parsed.netloc.lower()
            if ":" in domain:
                domain = domain.split(":")[0]

            if domain not in allowed_domains:
                raise ValidationError(f"Domain '{domain}' not in allowed list")

        if ".." in url:
            raise ValidationError("URL contains parent directory traversal")

        if parsed.netloc:
            netloc_lower = parsed.netloc.lower()
            dangerous_hosts = [
                "localhost",
                "127.0.0.1",
                "0.0.0.0",
                "::1",
                "[::]",
                "metadata.google.internal",
                "169.254.169.254",  # AWS metadata
            ]
            for dangerous in dangerous_hosts:
                if dangerous in netloc_lower:
                    raise ValidationError(f"URL points to internal/local resource: {dangerous}")

        return url

    @classmethod
    def validate_git_url(cls, url):
        """
        Validate a git repository URL

        Args:
            url (str): Git URL to validate

        Returns:
            Validated URL string

        Raises:
            ValidationError: If validation fails
        """
        if url.startswith("git@"):
            # Basic validation for SSH-style git URLs
            if ":" not in url[4:]:
                raise ValidationError(f"Invalid SSH git URL format: {url}")
            if len(url) > cls.MAX_URL_LENGTH:
                raise ValidationError(f"URL too long: {len(url)} > {cls.MAX_URL_LENGTH}")
            if ".." in url:
                raise ValidationError("URL contains parent directory traversal")
            return url

        # For other URLs, do general URL validation
        url = cls.validate_url(url, allowed_schemes={"https", "git"})

        if not cls.GIT_URL_PATTERN.match(url):
            # Allow some flexibility for different git URL formats
            parsed = urlparse(url)
            if parsed.scheme not in {"https", "git"}:
                raise ValidationError(f"Invalid git URL format: {url}")

        return url

    @classmethod
    def validate_package_name(cls, name, ecosystem):
        """
        Validate a package name based on ecosystem rules

        Args:
            name (str): Package name to validate
            ecosystem (str): Package ecosystem (npm, pypi, etc.)

        Returns:
            Validated package name

        Raises:
            ValidationError: If validation fails
        """
        if not name:
            raise ValidationError("Package name cannot be empty")

        if any(char in name for char in ["\\", "\0", "\n", "\r"]):
            raise ValidationError(f"Package name contains invalid characters: {name}")

        # Ecosystem-specific validation
        if ecosystem == "npm":
            # NPM allows scoped packages like @scope/package
            if name.startswith("@"):
                if name.count("/") != 1:
                    raise ValidationError(f"Invalid scoped NPM package: {name}")
            elif "/" in name:
                raise ValidationError(f"Non-scoped NPM package cannot contain '/': {name}")

            # NPM security: reject URL-encoded and unusual characters
            # These could cause issues with registry lookups or file system operations
            if "%" in name:
                raise ValidationError(f"NPM package name contains URL-encoded characters: {name}")

            # Reject non-ASCII characters for NPM packages (security precaution)
            # Real NPM might allow some of these, but we're being conservative
            try:
                name.encode("ascii")
            except UnicodeEncodeError:
                raise ValidationError(f"NPM package name contains non-ASCII characters: {name}")

        elif ecosystem == "pypi":
            # PyPI names should be simple
            if not re.match(r"^[a-zA-Z0-9_\-\.]+$", name):
                raise ValidationError(f"Invalid PyPI package name: {name}")
        else:
            # For other ecosystems, disallow forward slash
            if "/" in name:
                raise ValidationError(f"Package name contains invalid character '/': {name}")

        return name
