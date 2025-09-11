"""
CLI entry point

This module provides the command-line interface for Gardener, supporting
both local repository analysis and remote git repository cloning. It handles
argument parsing, configuration overrides, and error handling for the analysis workflow
"""

import argparse
import json
import sys

from gardener.analysis.main import run_analysis
from gardener.common.utils import Logger, RepositoryError


def main():
    """
    Main entry point for the Gardener CLI application

    Parses command-line arguments, validates configuration overrides, and
    orchestrates the dependency analysis on the specified repository. Handles
    both local paths and remote git repository URLs

    Exits with status 1 on errors (repository access failures or unexpected exceptions)
    """
    logger = Logger(verbose=True)  # CLI should show all messages
    parser = argparse.ArgumentParser()
    parser.add_argument("repo_path", help="Path to repo directory, or URL of hosted git repo")
    parser.add_argument("-o", "--output", help="Output file prefix")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")
    # Default behavior: minimal outputs (skip visualizations)
    parser.add_argument(
        "-m",
        "--minimal-outputs",
        action="store_true",
        help="Skip producing visualizations (default behavior). Use --visualize to enable",
    )
    parser.add_argument(
        "--visualize", action="store_true", help="Generate an HTML graph visualization in addition to JSON outputs"
    )
    parser.add_argument(
        "-l", "--languages", help="Comma-separated list of languages to focus on (e.g., python,javascript)"
    )
    parser.add_argument("-c", "--config", help="JSON string with configuration overrides")
    args = parser.parse_args()

    config_overrides = None
    if args.config:
        try:
            config_overrides = json.loads(args.config)
            logger.info(f"Applying {len(config_overrides)} configuration overrides")
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing configuration overrides: {e}")
            logger.error(
                "Configuration must be a valid JSON string, e.g., '{\"PAGERANK_ALPHA\": 0.85}' . "
                "See gardener/common/defaults.py for overrideable parameter names"
            )
            sys.exit(1)

    try:
        # Resolve minimal_outputs default: visualizations are opt-in
        minimal_outputs = True
        if args.visualize:
            minimal_outputs = False
        elif args.minimal_outputs:
            minimal_outputs = True

        run_analysis(args.repo_path, args.output, args.verbose, minimal_outputs, args.languages, config_overrides)
    except RepositoryError as e:
        logger.error(str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
