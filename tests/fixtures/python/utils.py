"""
Utility functions for the Python fixtures
"""

import math  # Standard library import

# Example of a commented-out relative import
# from . import config


def helper_function():
    """
    A simple helper function

    Returns:
        A string message
    """
    return f"Helper function using math.pi: {math.pi}"


def another_util():
    """
    Another utility function

    Returns:
        An integer
    """
    # Import inside function
    from random import randint

    return randint(1, 100)
