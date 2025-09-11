"""
Fixture for a simple User model
"""

from datetime import datetime as dt  # Aliased member import


class User:
    """
    Represents a user in the system fixture
    """

    def __init__(self, name, email):
        self.name = name
        self.email = email
        self.created_at = dt.now()

    def get_info(self):
        """
        Returns user information
        """
        return f"User: {self.name}, Email: {self.email}, Created: {self.created_at}"


def create_guest_user():
    """
    Factory function for creating a guest user
    """
    # Import inside function
    import uuid

    guest_id = str(uuid.uuid4())[:8]
    return User(f"Guest_{guest_id}", f"guest_{guest_id}@example.com")
