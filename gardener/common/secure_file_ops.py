"""
Secure file operations available in lieu of standard file operations
"""

import json
import os
from contextlib import contextmanager
from pathlib import Path


class SecurityError(Exception):
    """Raised when a security constraint is violated"""

    pass


class FileOperationError(Exception):
    """Raised when a file operation fails"""

    pass


class SecureFileAccess:
    """
    Provides secure file access within a restricted directory

    This class ensures all file operations stay within an allowed root directory,
    preventing path traversal attacks and unauthorized file access
    """

    def __init__(self, allowed_root):
        """
        Args:
            allowed_root (str): The root directory within which all operations must stay
        """
        self.allowed_root = Path(allowed_root).resolve()
        if not self.allowed_root.exists():
            raise ValueError(f"Allowed root directory does not exist: {allowed_root}")
        if not self.allowed_root.is_dir():
            raise ValueError(f"Allowed root must be a directory: {allowed_root}")

    def validate_path(self, path):
        """
        Validate that a path is within the allowed directory

        Args:
            path (str): Path to validate (can be relative or absolute)

        Returns:
            Resolved absolute path

        Raises:
            SecurityError: If path would escape the allowed directory
        """
        # Convert to Path object
        path_obj = Path(path)

        # If relative, make it relative to allowed_root
        if not path_obj.is_absolute():
            path_obj = self.allowed_root / path_obj

        # Resolve to absolute path (follows symlinks and removes ..)
        try:
            resolved = path_obj.resolve()
        except Exception as e:
            raise SecurityError(f"Cannot resolve path: {path}: {e}")

        try:
            resolved.relative_to(self.allowed_root)
        except ValueError:
            raise SecurityError(
                f"Path traversal attempt detected. "
                f"Path '{path}' resolves to '{resolved}' which is outside '{self.allowed_root}'"
            )

        return resolved

    def safe_open(self, path, mode="r", **kwargs):
        """
        Safely open a file within the allowed directory

        Args:
            path (str): Path to the file
            mode (str): File open mode
            **kwargs: Additional arguments for open()

        Returns:
            File handle

        Raises:
            SecurityError: If path validation fails
            IOError: If file operation fails
        """
        safe_path = self.validate_path(path)

        if "w" in mode or "a" in mode or "x" in mode:
            # For write operations, ensure parent directory exists and is safe
            parent = safe_path.parent
            if not parent.exists():
                raise IOError(f"Parent directory does not exist: {parent}")

        return open(safe_path, mode, **kwargs)

    def exists(self, path):
        """
        Check if a path exists within the allowed directory

        Args:
            path (str): Path to check

        Returns:
            True if path exists and is within allowed directory, False otherwise
        """
        try:
            safe_path = self.validate_path(path)
            return safe_path.exists()
        except SecurityError:
            return False

    def is_file(self, path):
        """
        Check if a path is a file within the allowed directory

        Args:
            path (str): Path to check

        Returns:
            True if path is a file within allowed directory, False otherwise
        """
        try:
            safe_path = self.validate_path(path)
            return safe_path.is_file()
        except SecurityError:
            return False

    def is_dir(self, path):
        """
        Check if a path is a directory within the allowed directory

        Args:
            path (str): Path to check

        Returns:
            True if path is a directory within allowed directory, False otherwise
        """
        try:
            safe_path = self.validate_path(path)
            return safe_path.is_dir()
        except SecurityError:
            return False

    def list_dir(self, path="."):
        """
        List directory contents within the allowed directory

        Args:
            path (str): Directory path (defaults to allowed root)

        Returns:
            List of Path objects for directory contents

        Raises:
            SecurityError: If path validation fails
            IOError: If path is not a directory
        """
        safe_path = self.validate_path(path)
        if not safe_path.is_dir():
            raise IOError(f"Not a directory: {safe_path}")

        return list(safe_path.iterdir())

    def read_text(self, path, encoding="utf-8"):
        """
        Read text file content

        Args:
            path (str): Path to the file
            encoding (str): Text encoding

        Returns:
            File content as string

        Raises:
            SecurityError: If path validation fails
            IOError: If file operation fails
        """
        safe_path = self.validate_path(path)
        return safe_path.read_text(encoding=encoding)

    def write_text(self, path, content, encoding="utf-8"):
        """
        Write text to file

        Args:
            path (str): Path to the file
            content (str): Text content to write
            encoding (str): Text encoding

        Raises:
            SecurityError: If path validation fails
            IOError: If file operation fails
        """
        safe_path = self.validate_path(path)
        safe_path.write_text(content, encoding=encoding)


class SecureFileOps:
    """
    Secure file operations for handling arbitrary external repos' files
    """

    def __init__(self, repo_path, logger=None):
        """
        Args:
            repo_path (str): Root path of the repository to analyze
            logger (Logger): Optional logger instance
        """
        self.repo_path = Path(repo_path).resolve()
        self.logger = logger

        try:
            self.secure_access = SecureFileAccess(self.repo_path)
        except Exception as e:
            raise FileOperationError(f"Failed to initialize secure file access: {e}")

    @contextmanager
    def open_file(self, path, mode="r", **kwargs):
        """
        Safely open a file within the repository

        Args:
            path (str): Path to the file (absolute or relative to repo)
            mode (str): File open mode
            **kwargs: Additional arguments for open()

        Yields:
            File handle

        Raises:
            FileOperationError: If file operation fails
            SecurityError: If security constraints are violated
        """
        try:
            with self.secure_access.safe_open(path, mode, **kwargs) as f:
                yield f
        except SecurityError as e:
            if self.logger:
                self.logger.error(f"Security error opening file {path}: {e}")
            raise
        except Exception as e:
            raise FileOperationError(f"Failed to open file {path}: {e}")

    def read_file(self, path, encoding="utf-8"):
        """
        Read file content safely

        Args:
            path (str): Path to the file
            encoding (str): Text encoding

        Returns:
            File content as string

        Raises:
            FileOperationError: If read fails
            SecurityError: If security constraints are violated
        """
        try:
            return self.secure_access.read_text(path, encoding=encoding)
        except SecurityError as e:
            if self.logger:
                self.logger.error(f"Security error reading file {path}: {e}")
            raise
        except Exception as e:
            raise FileOperationError(f"Failed to read file {path}: {e}")

    def write_file(self, path, content, encoding="utf-8"):
        """
        Write content to file safely

        Args:
            path (str): Path to the file
            content (str): Content to write
            encoding (str): Text encoding

        Raises:
            FileOperationError: If write fails
            SecurityError: If security constraints are violated
        """
        try:
            self.secure_access.write_text(path, content, encoding=encoding)
        except SecurityError as e:
            if self.logger:
                self.logger.error(f"Security error writing file {path}: {e}")
            raise
        except Exception as e:
            raise FileOperationError(f"Failed to write file {path}: {e}")

    def exists(self, path):
        """
        Check if a path exists within the repository

        Args:
            path (str): Path to check

        Returns:
            True if path exists and is within repository, False otherwise
        """
        return self.secure_access.exists(path)

    def is_file(self, path):
        """
        Check if a path is a file within the repository

        Args:
            path (str): Path to check

        Returns:
            True if path is a file within repository, False otherwise
        """
        return self.secure_access.is_file(path)

    def is_dir(self, path):
        """
        Check if a path is a directory within the repository

        Args:
            path (str): Path to check

        Returns:
            True if path is a directory within repository, False otherwise
        """
        return self.secure_access.is_dir(path)

    def list_dir(self, path="."):
        """
        List directory contents within the repository

        Args:
            path (str): Directory path (defaults to repo root)

        Returns:
            List of Path objects for directory contents

        Raises:
            FileOperationError: If operation fails
            SecurityError: If security constraints are violated
        """
        try:
            return self.secure_access.list_dir(path)
        except SecurityError as e:
            if self.logger:
                self.logger.error(f"Security error listing directory {path}: {e}")
            raise
        except Exception as e:
            raise FileOperationError(f"Failed to list directory {path}: {e}")

    def get_relative_path(self, path, start=None):
        """
        Get relative path within the repository

        Args:
            path (str): Path to make relative
            start (str): Optional start path (defaults to repo root)

        Returns:
            Relative path as string

        Raises:
            FileOperationError: If path is outside repository
        """
        try:
            # Validate path is within repo
            validated_path = self.secure_access.validate_path(path)

            if start is None:
                start = self.repo_path
            else:
                start = self.secure_access.validate_path(start)

            return os.path.relpath(validated_path, start)
        except SecurityError as e:
            raise FileOperationError(f"Path {path} is outside repository: {e}")

    def join_paths(self, *paths):
        """
        Join paths safely within the repository

        Args:
            *paths: Path components to join

        Returns:
            Joined Path object

        Raises:
            SecurityError: If resulting path would escape repository
        """
        if paths and not os.path.isabs(str(paths[0])):
            base = self.repo_path
        else:
            base = Path(paths[0])
            paths = paths[1:]

        # Join remaining paths
        result = base
        for p in paths:
            result = result / p

        # Validate result is within repo
        try:
            return self.secure_access.validate_path(result)
        except SecurityError:
            # If validation fails, it means path escapes repo
            raise SecurityError(f"Joined path {result} escapes repository bounds")

    def read_json(self, path):
        """
        Read and parse JSON file safely

        Args:
            path (str): Path to JSON file

        Returns:
            Parsed JSON data

        Raises:
            FileOperationError: If read or parse fails
            SecurityError: If security constraints are violated
        """
        try:
            content = self.read_file(path)
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise FileOperationError(f"Failed to parse JSON from {path}: {e}")
