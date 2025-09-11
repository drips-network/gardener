"""
Data-driven mock resolutions and expected invariants for Python fixture tests

Provides a small mapping used by the mock resolver and a centralized set of
expected imports/components per file so tests stay concise and robust
"""

PYTHON_FIXTURE_RESOLUTIONS = {
    "main.py": {
        # Relative imports
        ("utils", 1): "utils.py",
        ("config", 1): "config.py",
        ("config.settings", 0): "config.py",  # For resolving settings from config
        ("models", 1): "models/__init__.py",
        ("models.user", 0): "models/user.py",
        ("services", 1): "services/__init__.py",
        ("services.api", 0): "services/api.py",
        ("common", 1): "common/__init__.py",
        ("common.constants", 0): "common/constants.py",
    },
    "services/api.py": {
        # Relative imports (level 2 = ../)
        ("common", 2): "common/constants.py",
        ("models", 2): "models/user.py",
        ("utils", 2): "utils.py",
        ("config", 2): "config.py",
        # Absolute imports
        ("tests.fixtures.python.models", 0): "models/__init__.py",
        ("tests.fixtures.python.models.user", 0): "models/user.py",
    },
    # Files with no local imports
    "utils.py": {},
    "config.py": {},
    "models/user.py": {},
}


def create_mock_resolver(resolution_map=None):
    """
    Create a mock resolver function compatible with PythonLanguageHandler.extract_imports

    Args:
        resolution_map: Optional overrides for PYTHON_FIXTURE_RESOLUTIONS
    """
    if resolution_map is None:
        resolution_map = PYTHON_FIXTURE_RESOLUTIONS

    def mock_resolver(importing_file_rel_path, module_str, level):
        """Resolve (module_str, level) for a given importing file if present"""
        file_resolutions = resolution_map.get(importing_file_rel_path, {})
        return file_resolutions.get((module_str, level))

    return mock_resolver


# Expected minimal invariants per fixture file
EXPECTED_IMPORTS = {
    "main.py": {
        "external": [
            "os",
            "sys",
            "logging",  # Standard library
            "requests",
            "numpy",
            "pandas",  # Third-party
            "collections",
            "datetime",  # From imports
            "json",  # Inside function
            "io",  # Inside class
        ],
        "local": ["utils.py", "config.py", "models/user.py", "services/api.py", "common/constants.py"],
        "components": {
            "main.py": [
                ("collections", "defaultdict"),
                ("os", "path"),
                ("datetime", "datetime"),
                ("io", "StringIO"),
                ("numpy", "numpy"),
                ("pandas", "pandas"),
            ]
        },
    },
    "services/api.py": {
        "external": ["requests", "flask"],
        "local": ["common/constants.py", "models/user.py", "config.py"],
        "components": {"services/api.py": []},
    },
    "utils.py": {"external": ["math", "random"], "local": [], "components": {"utils.py": [("random", "randint")]}},
    "config.py": {"external": ["os", "sys"], "local": [], "components": {"config.py": []}},
    "models/user.py": {
        "external": ["datetime", "uuid"],
        "local": [],
        "components": {"models/user.py": [("datetime", "datetime")]},
    },
}
