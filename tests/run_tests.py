"""
Main test runner
"""

import argparse
import subprocess
import sys


def parse_args():
    """
    Parse command line arguments

    Returns:
        Parsed arguments object
    """
    parser = argparse.ArgumentParser(description="Run Gardener tests")
    parser.add_argument("--unit", action="store_true", help="Run unit tests")
    parser.add_argument("--integration", action="store_true", help="Run integration tests")
    parser.add_argument("--fixtures", action="store_true", help="Run tests against micro-repo fixtures")
    parser.add_argument("--system", action="store_true", help="Run system/API tests")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--update-snapshots", action="store_true", help="Update snapshots")
    parser.add_argument("--include-slow", action="store_true", help="Include slow tests (default: skip)")

    return parser.parse_args()


def run_tests(test_type, verbose=False, update_snapshots=False, include_slow=False):
    """
    Run tests of the specified type

    Args:
        test_type: Type of tests to run ('unit', 'integration', or 'fixtures')
        verbose: Whether to enable verbose output
        update_snapshots: Whether to update snapshots
        include_slow: Whether to include slow tests

    Returns:
        Exit code from the test run
    """
    cmd = [sys.executable, "-m", "pytest"]

    # Add verbosity
    if verbose:
        cmd.append("-v")

    # Add snapshot update flag if necessary
    if update_snapshots:
        cmd.append("--snapshot-update")

    # Skip slow tests by default
    if not include_slow:
        cmd.extend(["-m", "not slow"])

    # Add test path based on type
    if test_type == "unit":
        cmd.append("tests/unit/")
    elif test_type == "integration":
        cmd.append("tests/integration/")
    elif test_type == "fixtures":
        cmd.append("tests/fixtures/")
    elif test_type == "system":
        cmd.append("tests/system/")

    # Run the command
    print(f"\nRunning {test_type} tests...")
    print(f"Command: {' '.join(cmd)}")

    try:
        return subprocess.run(cmd).returncode
    except FileNotFoundError:
        print("\nError: Could not run pytest")
        print("Make sure pytest is installed by running: pip install pytest")
        return 1


def main():
    """
    Main entry point for the test runner

    Returns:
        Exit code indicating success (0) or failure (non-zero)
    """
    args = parse_args()

    # If no specific test type is requested, default to all
    if not (args.unit or args.integration or args.fixtures or args.system or args.all):
        args.all = True

    exit_codes = []

    # Run unit tests
    if args.unit or args.all:
        exit_codes.append(run_tests("unit", args.verbose, args.update_snapshots, args.include_slow))

    # Run integration tests
    if args.integration or args.all:
        exit_codes.append(run_tests("integration", args.verbose, args.update_snapshots, args.include_slow))

    # Run fixture tests
    if args.fixtures or args.all:
        exit_codes.append(run_tests("fixtures", args.verbose, args.update_snapshots, args.include_slow))

    # Run system tests
    if args.system or args.all:
        exit_codes.append(run_tests("system", args.verbose, args.update_snapshots, args.include_slow))

    # Return non-zero exit code if any test failed
    if any(code != 0 for code in exit_codes):
        print("\n🔴 Some tests failed")
        return 1
    else:
        print("\n🟢 All tests passed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
