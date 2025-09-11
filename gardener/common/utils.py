"""
Utility functions for dependency analysis
"""

import os
import re
import sys
import traceback

try:
    from gardener.common.input_validation import InputValidator, ValidationError

    SECURITY_AVAILABLE = True
except ImportError:
    SECURITY_AVAILABLE = False
    ValidationError = Exception  # Fallback


class RepositoryError(Exception):
    """
    Exception raised when repository operations fail

    Used by get_repo function to signal errors instead of calling sys.exit(1)
    """

    pass


class Logger:
    """
    Simple logger class with deduplication to avoid repetitive messages

    Maintains the same interface and behavior across the codebase
    """

    def __init__(self, verbose=False, name=None):
        """
        Args:
            verbose (bool): Enable verbose output
            name (str): Optional logger name
        """
        self.verbose = verbose
        self.name = name or "gardener"
        self.seen_messages = set()  # Track already seen messages to avoid duplication
        self.log_level = 1 if not verbose else 0  # 0=debug, 1=info, 2=warning, 3=error

    def debug(self, message):
        """
        Log a debug message (only in verbose mode)

        Args:
            message (str): Debug message to log
        """
        if self.log_level <= 0:
            # Only log if not seen before
            msg_hash = hash(message)
            if msg_hash not in self.seen_messages:
                print(f"... Debug: {message}")
                self.seen_messages.add(msg_hash)

    def info(self, message):
        """
        Log an informational message, avoiding duplicates

        Args:
            message (str): Message to log
        """
        if self.log_level <= 1:
            msg_hash = hash(message)
            if msg_hash not in self.seen_messages:
                print(message)
                self.seen_messages.add(msg_hash)

    def warning(self, message):
        """
        Log a warning message, always showing warnings

        Args:
            message (str): Warning message to log
        """
        if self.log_level <= 2:
            print(f"Warning: {message}", file=sys.stderr)

    def error(self, message, exception=None):
        """
        Log an error message with optional exception details

        Args:
            message (str): Error message to log
            exception (Exception): Optional exception to include traceback for (if verbose)
        """
        if self.log_level <= 3:
            error_msg = f"Error: {message}"
            print(error_msg, file=sys.stderr)
            if exception and self.verbose:
                traceback.print_exc()


# Module-level logger instance
_module_logger = None


def get_logger(name=None, verbose=False):
    """
    Get a logger instance

    Args:
        name (str): Optional name for the logger
        verbose (bool): Whether to enable verbose logging

    Returns:
        Logger instance
    """
    global _module_logger
    if _module_logger is None or name:
        _module_logger = Logger(verbose=verbose, name=name)
    return _module_logger


def get_repo(repo_input):
    """
    Get a repository by cloning or using a local path

    Supports both local directory paths and remote git repository URLs

    For remote repositories, clones to an 'input/' subdirectory (named as '<owner>_<repo>'
    when available) with fallback URL handling for common git hosting services

    Args:
        repo_input (str): URL of hosted git repo or local path to git repo

    Returns:
        Local path to the repository

    Raises:
        RepositoryError: If repository cannot be accessed or cloned
    """
    # Lazy import git - only needed when cloning repositories
    import git

    logger = get_logger()
    if os.path.exists(repo_input):
        if os.path.isdir(repo_input):
            if os.path.exists(os.path.join(repo_input, ".git")):
                logger.info(f"Using existing git repository at {repo_input}")
            else:
                logger.info(f"Using local directory at {repo_input} (not a git repository)")
            return repo_input
        else:
            raise RepositoryError(f"{repo_input} exists but is not a directory")

    # If it's not a local path, check if it's a URL
    # Basic URL pattern for git repositories - support any domain that might host git
    url_pattern = r"(https?://)([^\s/]+\.[^\s/]+)\/([^\s/]+\/[^\s/]+)(\.git)?"
    match = re.match(url_pattern, repo_input)
    if match:
        try:
            # Prefer owner_repo naming to avoid collisions across different owners
            owner_repo = match.group(3)  # e.g., 'owner/repo'
            # Sanitize and normalize directory name
            owner_repo = owner_repo.strip("/")
            if owner_repo.endswith(".git"):
                owner_repo = owner_repo[:-4]
            local_dir_name = (
                owner_repo.replace("/", "_") if owner_repo.count("/") == 1 else owner_repo.replace("/", "_")
            )

            # Fallback to repo name only if parsing failed for some reason
            repo_name = repo_input.rstrip("/").split("/")[-1]
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]

            input_dir = os.path.join(os.getcwd(), "input")
            if not os.path.exists(input_dir):
                os.makedirs(input_dir)

            # Use owner_repo when available, else just repo name
            local_path = os.path.join(input_dir, local_dir_name or repo_name)

            # If local path already exists, use it if it's a git repo
            if os.path.exists(local_path):
                if os.path.exists(os.path.join(local_path, ".git")):
                    logger.info(f"Using existing git repository at {local_path}")
                    return local_path
                else:
                    # Rename the existing directory to avoid conflicts
                    timestamp = int(os.path.getmtime(local_path))
                    backup_path = f"{local_path}_{timestamp}"
                    logger.info(f"Renaming existing directory {local_path} to {backup_path}")
                    os.rename(local_path, backup_path)

            # For GitHub repos, ensure the URL ends with .git for public repos
            if "github.com" in repo_input and not repo_input.endswith(".git"):
                clone_url = f"{repo_input}.git"
            else:
                clone_url = repo_input

            # Validate git URL for security
            if SECURITY_AVAILABLE:
                try:
                    clone_url = InputValidator.validate_git_url(clone_url)
                except ValidationError as e:
                    raise RepositoryError(f"Invalid git URL: {clone_url} - {e}")

            # Clone the repository
            logger.info(f"Cloning repository from {clone_url} to {local_path}...")
            try:
                git.Repo.clone_from(clone_url, local_path, no_checkout=False, depth=1)
                return local_path
            except Exception as e:
                if "github.com" in repo_input:
                    logger.debug(f"Initial clone attempt failed, attempting alternative approach: {str(e)}")
                    # If GitHub and initial attempt fails, try without .git
                    if clone_url.endswith(".git"):
                        alt_url = clone_url[:-4]
                    else:
                        alt_url = f"{clone_url}.git"

                    # Validate alternate URL
                    if SECURITY_AVAILABLE:
                        try:
                            alt_url = InputValidator.validate_git_url(alt_url)
                        except ValidationError as e:
                            raise RepositoryError(f"Invalid alternate git URL: {alt_url} - {e}")

                    logger.debug(f"Trying alternate URL: {alt_url}")
                    git.Repo.clone_from(alt_url, local_path, no_checkout=False, depth=1)
                    return local_path
                else:
                    raise  # Re-raise the exception if not GitHub or second attempt fails

        except Exception as e:
            raise RepositoryError(f"Failed to clone repository: {str(e)}")
    else:
        raise RepositoryError(f"'{repo_input}' is neither a valid local path nor a recognized repository URL")
