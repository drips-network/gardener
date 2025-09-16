"""
Sandboxed subprocess execution with security constraints
"""

import os
import shlex
import subprocess
from pathlib import Path

# resource module is not available on Windows
try:
    import resource

    HAS_RESOURCE = True
except ImportError:
    HAS_RESOURCE = False

from .input_validation import InputValidator


class SubprocessSecurityError(Exception):
    """Raised when subprocess security constraints are violated"""

    pass


class SecureSubprocess:
    """
    Provides secure subprocess execution with sandboxing
    """

    # Default security constraints
    DEFAULT_TIMEOUT = 300  # 5 minutes
    MAX_OUTPUT_SIZE = 10 * 1024 * 1024  # 10MB
    DEFAULT_PATH_ENTRIES = ("/usr/local/bin", "/usr/bin", "/bin")
    DEFAULT_ALLOWED_ENV_VARS = {
        "NODE_ENV",
        "NPM_CONFIG_PREFIX",
        "PYTHONPATH",
        "NODE_PATH",
        "GEM_HOME",
        "CARGO_HOME",
        "GOPATH",
        # Allowlist Git-related envs to disable interactive prompts safely
        "GIT_TERMINAL_PROMPT",
        "GIT_ASKPASS",
        "GIT_SSH_COMMAND",
    }
    MAX_LOGGED_OUTPUT_CHARS = 4000

    def __init__(self, allowed_root, timeout=DEFAULT_TIMEOUT, max_output_size=MAX_OUTPUT_SIZE,
                 *, allowed_env_vars=None, extra_path_dirs=None):
        """
        Args:
            allowed_root (str or pathlib.Path): Root directory for subprocess operations
            timeout (int): Maximum execution time in seconds
            max_output_size (int): Maximum output size in bytes
            allowed_env_vars (Iterable[str] | None): Additional environment variable names allowed when
                forwarding env to subprocesses
            extra_path_dirs (Iterable[str] | None): Extra directories appended to safe PATH to locate
                binaries such as virtual environment interpreters
        """
        self.allowed_root = Path(allowed_root).resolve()
        self.timeout = timeout
        self.max_output_size = max_output_size

        self.allowed_env_vars = set(self.DEFAULT_ALLOWED_ENV_VARS)
        if allowed_env_vars:
            for key in allowed_env_vars:
                if isinstance(key, str) and key:
                    self.allowed_env_vars.add(key)

        self.extra_path_dirs = []
        if extra_path_dirs:
            for path_entry in extra_path_dirs:
                if not path_entry:
                    continue
                try:
                    resolved_entry = Path(path_entry).resolve()
                except (OSError, TypeError):
                    continue
                if resolved_entry.is_dir():
                    self.extra_path_dirs.append(str(resolved_entry))

        if not self.allowed_root.exists():
            raise ValueError(f"Allowed root does not exist: {allowed_root}")

    def validate_command(self, command):
        """
        Validate and prepare command for execution

        Args:
            command (str or list): Command to execute (string or list)

        Returns:
            Command as list of arguments

        Raises:
            SubprocessSecurityError: If command validation fails
        """
        # Convert string to list if needed
        if isinstance(command, str):
            # Use shlex to safely split command
            try:
                command_list = shlex.split(command)
            except Exception as e:
                raise SubprocessSecurityError(f"Invalid command format: {e}")
        else:
            command_list = list(command)

        if not command_list:
            raise SubprocessSecurityError("Command cannot be empty")

        # Validate each part of the command
        for part in command_list:
            if not isinstance(part, str):
                raise SubprocessSecurityError(f"Command part must be string, got {type(part)}")

            dangerous_chars = ["|", "&", ";", "$", "`", "\n", "\r"]
            for char in dangerous_chars:
                if char in part:
                    raise SubprocessSecurityError(f"Command contains dangerous character: {char}")

        return command_list

    def validate_cwd(self, cwd):
        """
        Validate working directory for subprocess

        Args:
            cwd (str or pathlib.Path): Working directory path

        Returns:
            Validated Path object

        Raises:
            SubprocessSecurityError: If cwd validation fails
        """
        if cwd is None:
            return self.allowed_root

        cwd_path = Path(cwd).resolve()

        # Ensure cwd is within allowed root
        try:
            cwd_path.relative_to(self.allowed_root)
        except ValueError:
            raise SubprocessSecurityError(f"Working directory '{cwd}' is outside allowed root '{self.allowed_root}'")

        if not cwd_path.exists():
            raise SubprocessSecurityError(f"Working directory does not exist: {cwd}")

        if not cwd_path.is_dir():
            raise SubprocessSecurityError(f"Working directory is not a directory: {cwd}")

        return cwd_path

    def create_safe_env(self, env=None):
        """
        Create a safe environment for subprocess execution

        Args:
            env (dict): Optional environment variables to include

        Returns:
            Safe environment dictionary
        """
        path_entries = list(self.DEFAULT_PATH_ENTRIES)
        for entry in self.extra_path_dirs:
            if entry not in path_entries:
                path_entries.append(entry)

        safe_env = {
            "PATH": os.pathsep.join(path_entries),
            "LC_ALL": "C.UTF-8",
            "LANG": "C.UTF-8",
        }

        if env:
            for key, value in env.items():
                if key in self.allowed_env_vars and isinstance(value, str):
                    # Validate environment variable value
                    if "\0" not in value and len(value) < 1024:
                        safe_env[key] = value

        return safe_env

    def run(self, command, cwd=None, env=None, capture_output=True, check=False):
        """
        Run a subprocess with security constraints

        Args:
            command (str or list): Command to execute
            cwd (str or pathlib.Path): Working directory (must be within allowed root)
            env (dict): Environment variables
            capture_output (bool): Whether to capture stdout/stderr
            check (bool): Whether to raise exception on non-zero exit

        Returns:
            CompletedProcess instance

        Raises:
            SubprocessSecurityError: If security constraints violated
            subprocess.TimeoutExpired: If process exceeds timeout
            subprocess.CalledProcessError: If check=True and exit code non-zero
        """
        # Validate inputs
        command_list = self.validate_command(command)
        safe_cwd = self.validate_cwd(cwd)
        safe_env = self.create_safe_env(env)

        # Prepare subprocess arguments
        kwargs = {
            "cwd": str(safe_cwd),
            "env": safe_env,
            "timeout": self.timeout,
            "capture_output": capture_output,
            "text": True,
            "check": check,
        }

        if HAS_RESOURCE and os.name != "nt":  # Not Windows

            def set_limits():
                try:
                    # Limit CPU time
                    resource.setrlimit(resource.RLIMIT_CPU, (self.timeout, self.timeout))
                    # Note: Memory and process limits can be too restrictive on some systems
                    # Only set them if we can get current limits
                    try:
                        current = resource.getrlimit(resource.RLIMIT_NOFILE)
                        resource.setrlimit(resource.RLIMIT_NOFILE, (min(256, current[0]), current[1]))
                    except:
                        pass
                except Exception:
                    # If setting limits fails, continue without them
                    # Better to run with fewer restrictions than to fail
                    pass

            kwargs["preexec_fn"] = set_limits

        try:
            result = subprocess.run(command_list, **kwargs)

            if capture_output:
                total_size = len(result.stdout or "") + len(result.stderr or "")
                if total_size > self.max_output_size:
                    raise SubprocessSecurityError(
                        f"Subprocess output too large: {total_size} > {self.max_output_size}"
                    )

            return result

        except subprocess.TimeoutExpired as exc:
            raise SubprocessSecurityError(f"Process exceeded timeout of {self.timeout}s") from exc
        except subprocess.CalledProcessError as exc:
            safe_cmd = " ".join(shlex.quote(arg) for arg in command_list[:5])
            if len(command_list) > 5:
                safe_cmd += " ..."
            stdout_snippet = (exc.stdout or "").strip()
            stderr_snippet = (exc.stderr or "").strip()
            message_parts = [
                f"Command exited with {exc.returncode}: {safe_cmd}"
            ]
            if stdout_snippet:
                message_parts.append(
                    "stdout:\n" + stdout_snippet[: self.MAX_LOGGED_OUTPUT_CHARS]
                )
            if stderr_snippet:
                message_parts.append(
                    "stderr:\n" + stderr_snippet[: self.MAX_LOGGED_OUTPUT_CHARS]
                )
            raise SubprocessSecurityError("\n".join(message_parts)) from exc
        except Exception as exc:
            safe_cmd = " ".join(shlex.quote(arg) for arg in command_list[:5])
            if len(command_list) > 5:
                safe_cmd += " ..."
            raise SubprocessSecurityError(f"Subprocess failed for command: {safe_cmd}") from exc
