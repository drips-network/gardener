"""
Pytest configuration and shared fixtures
"""

import os
import random

import pytest

# Expose additional fixtures from support library
pytest_plugins = ["tests.support.fixtures"]

from gardener.common.tsl import get_parser

from gardener.analysis.graph import DependencyGraphBuilder
from gardener.common.utils import Logger


@pytest.fixture
def logger():
    """Provide a verbose logger for tests"""
    return Logger(verbose=True)


@pytest.fixture
def graph_builder(logger):
    """DependencyGraphBuilder instance wired with test logger"""
    return DependencyGraphBuilder(logger)


@pytest.fixture
def tree_parser():
    """
    Return a callable that parses code for a given language and returns the root node

    Usage:
        root = tree_parser('python', "import os\n")
    """

    def _parse(language, code):
        parser = get_parser(language)
        tree = parser.parse(code.encode())
        return tree.root_node

    return _parse


def pytest_configure(config):
    os.environ.setdefault("TZ", "UTC")
    random.seed(1337)
