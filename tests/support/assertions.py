"""
Assertion helpers used across tests
"""


def assert_contains_all(actual, expected, label="set"):
    """
    Assert that all items in expected are contained in actual

    Args:
        actual (Iterable): Actual collection
        expected (Iterable): Expected collection
        label (str): Label for error messages
    """
    missing = [x for x in expected if x not in actual]
    if missing:
        raise AssertionError(f"{label} missing expected items: {missing}")


def assert_warning_logged(logger, contains):
    """
    Assert logger.warning was called with a message containing substring
    """
    # Support both spy and mock styles
    calls = (
        getattr(logger, "warning").call_args_list
        if hasattr(logger, "warning") and hasattr(logger.warning, "call_args_list")
        else []
    )
    for call in calls:
        msg = call[0][0] if call and call[0] else ""
        if contains in str(msg):
            return
    raise AssertionError(f"Expected warning containing '{contains}' was not logged")
