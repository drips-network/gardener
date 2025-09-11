"""
Focused tests for malformed/edge-case inputs validated by InputValidator
"""

import pytest

from gardener.common.input_validation import InputValidator, ValidationError

pytestmark = pytest.mark.security


def test_empty_and_null_inputs():
    # Empty strings
    with pytest.raises(ValidationError):
        InputValidator.validate_file_path("")
    with pytest.raises(ValidationError):
        InputValidator.validate_url("")
    with pytest.raises(ValidationError):
        InputValidator.validate_package_name("", "npm")

    # None inputs
    with pytest.raises((ValidationError, AttributeError)):
        InputValidator.validate_file_path(None)


def test_extremely_long_inputs():
    # Very long file path
    long_path = "a" * 5000
    with pytest.raises(ValidationError) as exc:
        InputValidator.validate_file_path(long_path)
    assert "too long" in str(exc.value)

    # Very long URL
    long_url = "https://example.com/" + "a" * 2980
    with pytest.raises(ValidationError) as exc:
        InputValidator.validate_url(long_url)
    assert "too long" in str(exc.value)


def test_special_characters_in_inputs():
    dangerous_inputs = [
        "\0",
        "\n\r\t",
        "../../etc/passwd\0",
        "test\nrm -rf /",
        "test\r\nSet-Cookie: evil=true",
        "test%00.txt",
        "test%2e%2e%2f%2e%2e%2f",
        "test\x00\x01\x02",
        "test\ufeff",
        "../etc/passwd",
        "test\u200b",
    ]
    for s in dangerous_inputs:
        with pytest.raises(ValidationError):
            InputValidator.validate_file_path(s)
        with pytest.raises(ValidationError):
            InputValidator.validate_package_name(s, "npm")


def test_url_edge_cases():
    edge_case_urls = [
        "https://",
        "https://.",
        "https://..",
        "https://example.com:99999",
        "https://example.com:-1",
        "https://[::1]",
        "https://0.0.0.0",
        "https://255.255.255.255",
        "https://example.com@attacker.com",
        "https://example.com#@attacker.com",
        "https://example.com?@attacker.com",
        "https://user:pass@example.com",
        "https://example.com\\.attacker.com",
        "https://example.com%00.attacker.com",
        "https://exąmple.com",
    ]
    for url in edge_case_urls:
        try:
            safe = InputValidator.validate_url(url)
            assert "localhost" not in safe
            assert "0.0.0.0" not in safe
            assert "::1" not in safe
        except ValidationError:
            pass


def test_package_name_edge_cases():
    edge_cases = [
        ("", "npm"),
        (" ", "npm"),
        (".", "npm"),
        ("..", "npm"),
        ("@", "npm"),
        ("@/", "npm"),
        ("@scope", "npm"),
        ("@scope/", "npm"),
        ("@scope/package/extra", "npm"),
        ("package/../../etc", "npm"),
        ("-package", "pypi"),
        ("package-", "pypi"),
        ("pack age", "pypi"),
        ("pack\tage", "pypi"),
        ("pack\nage", "pypi"),
        ("пакет", "pypi"),
        ("📦", "npm"),
    ]
    for name, ecosystem in edge_cases:
        try:
            valid = InputValidator.validate_package_name(name, ecosystem)
            assert len(valid) > 0 and "\n" not in valid and "\t" not in valid
        except ValidationError:
            pass
