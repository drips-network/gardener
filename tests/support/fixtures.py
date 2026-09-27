"""
Reusable pytest fixtures for deterministic, offline testing
"""

import contextlib
import io
import json
import zipfile
import os
import random

import pytest
import requests

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
                response = self._responses.get(url)
                if callable(response):
                    return response(url)
                if isinstance(response, Exception):
                    raise response
                return response

            url_resolver.set_request_fn(_hook)
            try:
                yield
            finally:
                url_resolver.set_request_fn(None)

    return Offline()


@pytest.fixture
def fake_pypi(monkeypatch):
    """Serve registered release metadata and tiny wheels without network access"""
    class PyPI:
        def __init__(self):
            self.responses = {}
            self.requested_urls = []

        def add_release(self, name, version, files):
            archive_url = f"https://files.example/{name}-{version}.whl"
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                for path, content in files.items():
                    archive.writestr(path, content)
            self.responses[archive_url] = buffer.getvalue()
            url = f"https://pypi.org/pypi/{name}/json"
            metadata = json.loads(self.responses.get(url, b'{"info": {}, "releases": {}}'))
            metadata["releases"][version] = [{"filename": f"{name}-py3-none-any.whl", "url": archive_url}]
            metadata["info"]["version"] = version
            self.responses[url] = json.dumps(metadata).encode()
            return archive_url

        def get(self, url, **kwargs):
            self.requested_urls.append(url)
            if url not in self.responses:
                raise requests.ConnectionError(url)
            response = requests.Response()
            response.status_code = 200
            response._content = self.responses[url]
            return response

    pypi = PyPI()
    monkeypatch.setattr("gardener.package_metadata.name_resolvers.python.requests.get", pypi.get)
    return pypi
