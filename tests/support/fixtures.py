"""
Reusable pytest fixtures for deterministic, offline testing
"""

import contextlib
import os
import random

import pytest

from gardener.package_metadata import url_resolver


@pytest.fixture(scope="session", autouse=False)
def deterministic_env():
    """
    Set deterministic environment variables and random seed for tests
    """
    os.environ.setdefault("TZ", "UTC")
    random.seed(1337)
    yield


@pytest.fixture
def offline_mode():
    """
    Patch url_resolver to avoid real network calls. Tests can set a response map:

        responses = { 'https://registry.npmjs.org/pkg': '{"name":"pkg"}' }
        with offline_mode.set_responses(responses):
            ...
    """

    class Offline:
        def __init__(self):
            self._responses = {}

        @contextlib.contextmanager
        def set_responses(self, mapping):
            self._responses = dict(mapping or {})

            def _hook(url):
                return self._responses.get(url)

            url_resolver.set_request_fn(_hook)
            try:
                yield
            finally:
                url_resolver.set_request_fn(None)

    return Offline()
