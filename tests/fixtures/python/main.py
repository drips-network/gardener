"""
Main fixture file demonstrating various import types
"""

import logging  # Standard logger
import os
import sys

# Specific member imports
from collections import defaultdict

# Aliased member import
from datetime import datetime as dt
from os import path

import numpy as np
import pandas as pd

# Third-party imports
import requests

# Absolute local import (within the fixtures package)
# Relative imports (assuming utils.py and config.py exist)
from . import config  # Importing the config module directly # Changed to relative
from . import utils
from .common import constants  # Import for common constants
from .config import settings  # Assuming settings is defined in config.py

# Multi-line import
from .models import (  # Changed to relative; product # Example of commented item in multi-line
    user,
)

# Import for services
from .services import api

# Commented-out import (should be ignored)
# import unused_package


def main_function():
    """
    Demonstrates imports inside a function
    """
    import json  # Import inside function

    data = {"key": "value"}
    print(f"Using json inside function: {json.dumps(data)}")
    print(f"Using requests: {requests.get}")
    print(f"Using numpy: {np.array([1, 2])}")
    print(f"Using pandas: {pd.DataFrame()}")
    print(f"Using defaultdict: {defaultdict(int)}")
    print(f"Using os.path: {path.join('a', 'b')}")
    print(f"Using datetime as dt: {dt.now()}")
    print(f"Using local utils: {utils.helper_function()}")
    print(f"Using local config settings: {settings}")
    print(f"Using local config module: {config}")
    print(f"Using local models.user: {user.User}")
    print(f"Using os: {os.name}")
    print(f"Using sys: {sys.platform}")
    logging.info("Logging from main_function")


class MainClass:
    """
    Demonstrates imports inside a class
    """

    from io import StringIO  # Import inside class

    def __init__(self):
        self.buffer = self.StringIO("Class buffer")
        print(f"Using StringIO inside class: {self.buffer.getvalue()}")


if __name__ == "__main__":
    main_function()
    main_instance = MainClass()
