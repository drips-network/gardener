"""
Path-based scope classification and filtering for analysis evidence
"""

from dataclasses import dataclass
from pathlib import Path

SCOPE_CLASSIFIER_VERSION = "path-heuristic-v1"

SCOPE_PRODUCTION = "production"
SCOPE_TESTS = "tests"
SCOPE_FIXTURES = "fixtures"
SCOPE_EXAMPLES = "examples"
SCOPE_DOCS = "docs"
SCOPE_SCRIPTS = "scripts"
SCOPE_UNKNOWN = "unknown"

SCOPE_ORDER = (
    SCOPE_PRODUCTION,
    SCOPE_TESTS,
    SCOPE_FIXTURES,
    SCOPE_EXAMPLES,
    SCOPE_DOCS,
    SCOPE_SCRIPTS,
    SCOPE_UNKNOWN,
)

_SCOPE_ORDER_INDEX = {scope: index for index, scope in enumerate(SCOPE_ORDER)}

_SCOPE_ALIASES = {
    "production": SCOPE_PRODUCTION,
    "prod": SCOPE_PRODUCTION,
    "test": SCOPE_TESTS,
    "tests": SCOPE_TESTS,
    "fixture": SCOPE_FIXTURES,
    "fixtures": SCOPE_FIXTURES,
    "example": SCOPE_EXAMPLES,
    "examples": SCOPE_EXAMPLES,
    "doc": SCOPE_DOCS,
    "docs": SCOPE_DOCS,
    "documentation": SCOPE_DOCS,
    "script": SCOPE_SCRIPTS,
    "scripts": SCOPE_SCRIPTS,
    "unknown": SCOPE_UNKNOWN,
}

_FIXTURE_COMPONENTS = frozenset({"fixtures", "fixture", "__fixtures__", "testdata", "test-data"})
_TEST_COMPONENTS = frozenset({"tests", "test", "__tests__"})
_EXAMPLE_COMPONENTS = frozenset({"examples", "example", "demo", "demos", "samples", "sample"})
_DOC_COMPONENTS = frozenset({"docs", "doc", "documentation"})
_SCRIPT_COMPONENTS = frozenset({"scripts", "script", "ci", "build-scripts", "deploy-scripts"})
_TEST_FILE_SUFFIXES = (
    ".test.js",
    ".spec.js",
    ".test.jsx",
    ".spec.jsx",
    ".test.mjs",
    ".spec.mjs",
    ".test.cjs",
    ".spec.cjs",
    ".test.ts",
    ".spec.ts",
    ".test.tsx",
    ".spec.tsx",
)


@dataclass(frozen=True)
class ScopeFilter:
    """
    Include/exclude filter over canonical evidence scopes
    """

    include: frozenset[str] | None
    exclude: frozenset[str]

    def __post_init__(self):
        if self.include is not None:
            object.__setattr__(self, "include", frozenset(normalize_scope(scope) for scope in self.include))
        object.__setattr__(self, "exclude", frozenset(normalize_scope(scope) for scope in self.exclude))

    @classmethod
    def all(cls) -> "ScopeFilter":
        return cls(include=None, exclude=frozenset())

    def allows(self, scope: str) -> bool:
        canonical_scope = normalize_scope(scope)
        if self.include is not None and canonical_scope not in self.include:
            return False
        return canonical_scope not in self.exclude

    def active_scopes(self) -> list[str]:
        return [scope for scope in SCOPE_ORDER if self.allows(scope)]

    def to_metadata(self) -> dict:
        if self.include is None and not self.exclude:
            mode = "all"
        elif self.include is None:
            mode = "exclude"
        elif not self.exclude:
            mode = "include"
        else:
            mode = "include-exclude"

        return {
            "mode": mode,
            "include": sort_scopes(self.include) if self.include is not None else None,
            "exclude": sort_scopes(self.exclude),
            "active": self.active_scopes(),
            "classifier": SCOPE_CLASSIFIER_VERSION,
        }


def sort_scopes(scopes) -> list[str]:
    """
    Return canonical scopes in stable display order
    """
    return sorted({normalize_scope(scope) for scope in scopes}, key=lambda scope: _SCOPE_ORDER_INDEX[scope])


def normalize_scope(scope: str) -> str:
    """
    Normalize a scope token or raise ValueError
    """
    normalized = str(scope).strip().lower()
    if normalized in _SCOPE_ALIASES:
        return _SCOPE_ALIASES[normalized]
    raise ValueError(f"Unknown scope: {scope}")


def parse_scope_filter(scope_value: str | None, exclude_scope_value: str | None) -> ScopeFilter:
    """
    Parse CLI scope strings into a ScopeFilter
    """
    include_tokens = _parse_scope_tokens(scope_value, allow_all=True, option_name="--scope")
    exclude_tokens = _parse_scope_tokens(exclude_scope_value, allow_all=False, option_name="--exclude-scope")
    exclude = frozenset(exclude_tokens or [])

    if include_tokens is None:
        include = None
    elif include_tokens == ["all"]:
        include = None
    elif "all" in include_tokens:
        raise ValueError("--scope all cannot be combined with other scopes")
    else:
        include = frozenset(include_tokens)

    return ScopeFilter(include=include, exclude=exclude)


def classify_path_scope(rel_path) -> str:
    """
    Classify a repository-relative path into a canonical path scope
    """
    if rel_path is None:
        return SCOPE_UNKNOWN

    path_text = str(rel_path).strip()
    if not path_text:
        return SCOPE_UNKNOWN

    try:
        path = Path(path_text)
        components = tuple(part.lower() for part in path.parts if part not in ("", "."))
    except (TypeError, ValueError):
        return SCOPE_UNKNOWN

    if not components:
        return SCOPE_UNKNOWN

    filename = components[-1]
    stem = Path(filename).stem.lower()

    if any(component in _FIXTURE_COMPONENTS for component in components):
        return SCOPE_FIXTURES
    if any(component in _TEST_COMPONENTS for component in components) or _is_test_filename(filename, stem):
        return SCOPE_TESTS
    if any(component in _EXAMPLE_COMPONENTS for component in components):
        return SCOPE_EXAMPLES
    if any(component in _DOC_COMPONENTS for component in components):
        return SCOPE_DOCS
    if any(component in _SCRIPT_COMPONENTS for component in components):
        return SCOPE_SCRIPTS
    return SCOPE_PRODUCTION


def _parse_scope_tokens(value: str | None, *, allow_all: bool, option_name: str) -> list[str] | None:
    if value is None:
        return None

    raw_tokens = str(value).split(",")
    if any(not token.strip() for token in raw_tokens):
        raise ValueError(f"{option_name} contains an empty scope")

    tokens = []
    for token in raw_tokens:
        normalized = token.strip().lower()
        if normalized == "all":
            if not allow_all:
                raise ValueError(f"{option_name} all is not valid")
            tokens.append("all")
        else:
            tokens.append(normalize_scope(normalized))

    if len(tokens) > 1 and "all" in tokens:
        raise ValueError(f"{option_name} all cannot be combined with other scopes")
    return tokens


def _is_test_filename(filename: str, stem: str) -> bool:
    return (
        filename.startswith("test_")
        or filename.endswith(_TEST_FILE_SUFFIXES)
        or stem.endswith("_test")
        or stem.endswith("_spec")
    )
