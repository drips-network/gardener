"""
Shared file operation utilities
"""

import json


def read_file_content(file_path, secure_file_ops=None, encoding="utf-8"):
    """
    Read file content using secure_file_ops if available, otherwise use standard file operations

    This utility function provides a consistent pattern for reading files across all components,
    eliminating code duplication and standardizing error handling

    Args:
        file_path (str): Path to the file to read
        secure_file_ops (object): Optional SecureFileOps instance for safe file operations
        encoding (str): File encoding (default: 'utf-8')

    Returns:
        The content of the file as a string

    Raises:
        FileOperationError: If secure file operations fail
        Exception: If standard file operations fail
    """
    if secure_file_ops:
        return secure_file_ops.read_file(file_path, encoding=encoding)
    else:
        with open(file_path, "r", encoding=encoding) as f:
            return f.read()


def safe_json_load(file_path, secure_file_ops=None):
    """
    Load JSON content from a file using secure_file_ops if available

    This utility function provides a consistent pattern for loading JSON files across all components,
    with standardized error handling

    Args:
        file_path (str): Path to the JSON file to read
        secure_file_ops (object): Optional SecureFileOps instance for safe file operations

    Returns:
        The parsed JSON content as a dictionary or list

    Raises:
        FileOperationError: If secure file operations fail
        json.JSONDecodeError: If JSON parsing fails
        Exception: If standard file operations fail
    """
    if secure_file_ops:
        return secure_file_ops.read_json(file_path)
    else:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
