"""
Fixture for a service that interacts with an API and uses models
"""

import flask  # Third-party import
import requests  # Third-party import

# Multi-level relative import (assuming common/constants.py exists)
from ..common import constants

# Relative import from parent package's sibling
# This demonstrates importing from a different top-level directory within the fixtures
from ..config import settings

# Absolute local import from sibling package
from ..models import user  # Changed to relative

# Example of potentially ambiguous syntax (import near complex string)
query = """
SELECT * FROM users;
"""
# import re # This import is fine, just placed near a multiline string


class ApiClient:
    """
    A simple API client fixture
    """

    def __init__(self):
        self.endpoint = settings.get("API_ENDPOINT", "http://fallback.api")
        self.timeout = constants.DEFAULT_TIMEOUT  # Using constant from common

    def fetch_user_data(self, user_id):
        """
        Fetches user data from the API

        Returns:
            Dictionary or None
        """
        try:
            response = requests.get(f"{self.endpoint}/users/{user_id}", timeout=self.timeout)
            response.raise_for_status()  # Raise an exception for bad status codes
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"API request failed: {e}")
            return None

    def create_user_object(self, data):
        """
        Creates a User object from API data
        """
        if data and "name" in data and "email" in data:
            # Using the imported user model
            return user.User(data["name"], data["email"])
        return None


# Example usage (not typically run, just for fixture structure)
if __name__ == "__main__":
    client = ApiClient()
    user_data = client.fetch_user_data(1)
    if user_data:
        user_obj = client.create_user_object(user_data)
        if user_obj:
            print(user_obj.get_info())
