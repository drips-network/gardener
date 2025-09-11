"""
Unit tests for subprocess security environment
"""

import shutil
import tempfile

from gardener.common.subprocess import SecureSubprocess


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
