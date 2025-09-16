"""
Unit tests for subprocess security environment
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from gardener.common.subprocess import SecureSubprocess, SubprocessSecurityError


def test_secure_subprocess_allows_git_env():
    """
    Ensure SecureSubprocess.create_safe_env preserves allowed Git env vars
    """
    tmp_dir = tempfile.mkdtemp(prefix="gardener-test-subprocess-")
    try:
        sp = SecureSubprocess(allowed_root=tmp_dir, timeout=1)
        env = sp.create_safe_env(
            {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/echo", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"}
        )
        assert env.get("GIT_TERMINAL_PROMPT") == "0"
        assert env.get("GIT_ASKPASS") == "/bin/echo"
        assert env.get("GIT_SSH_COMMAND") == "ssh -o BatchMode=yes"
        # PATH should always be set in safe env
        assert "PATH" in env and env["PATH"]
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_secure_subprocess_allows_custom_env_vars():
    """Ensure additional allowed env vars are preserved when forwarded"""
    tmp_dir = tempfile.mkdtemp(prefix="gardener-test-subprocess-")
    try:
        sp = SecureSubprocess(allowed_root=tmp_dir, timeout=1, allowed_env_vars={"DATABASE_URL"})
        env = sp.create_safe_env({"DATABASE_URL": "postgresql://example"})
        assert env.get("DATABASE_URL") == "postgresql://example"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_secure_subprocess_extra_path_dirs():
    """Ensure custom path entries are appended to the safe PATH"""
    tmp_dir = tempfile.mkdtemp(prefix="gardener-test-subprocess-")
    try:
        extra_dir = Path(tmp_dir) / "bin"
        extra_dir.mkdir(exist_ok=True)
        sp = SecureSubprocess(allowed_root=tmp_dir, timeout=1, extra_path_dirs=[str(extra_dir)])
        env = sp.create_safe_env()
        path_entries = env["PATH"].split(os.pathsep)
        assert str(extra_dir.resolve()) in path_entries
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_secure_subprocess_reports_failure_output():
    """Ensure subprocess failures include stdout and stderr snippets"""
    tmp_dir = tempfile.mkdtemp(prefix="gardener-test-subprocess-")
    try:
        script_path = Path(tmp_dir) / "failing_script.py"
        with open(script_path, "w", encoding="utf-8") as script_file:
            script_file.write(
                "import sys\n"
                "sys.stdout.write('hello from stdout\\n')\n"
                "sys.stderr.write('boom on stderr\\n')\n"
                "sys.exit(5)\n"
            )
        sp = SecureSubprocess(allowed_root=tmp_dir, timeout=1)
        with pytest.raises(SubprocessSecurityError) as exc_info:
            sp.run([sys.executable, str(script_path)], cwd=tmp_dir, check=True)
        message = str(exc_info.value)
        assert "stdout:\nhello from stdout" in message
        assert "stderr:\nboom on stderr" in message
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
