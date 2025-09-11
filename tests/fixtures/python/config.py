"""
Configuration settings for the Python fixtures
"""

import os

# Example configuration dictionary
settings = {"API_ENDPOINT": os.getenv("API_ENDPOINT", "http://default.api"), "TIMEOUT": 30, "DEBUG_MODE": False}

# Example of an import with a trailing comment
import sys  # System-specific parameters and functions


def get_debug_status():
    """
    Returns the debug status
    """
    return settings.get("DEBUG_MODE", False)
