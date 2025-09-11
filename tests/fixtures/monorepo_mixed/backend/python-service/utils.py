"""
Utility functions for the Python service
"""


def validate_request(request):
    """Validate incoming request"""
    return hasattr(request, "id") and request.id > 0


def format_response(data):
    """Format response data"""
    return {"success": True, "data": data, "timestamp": None}
