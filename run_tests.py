#!/usr/bin/env python3
"""
run_tests.py
────────────
HUNGU test runner CLI.

Usage
─────
  # Run ALL tests
  python run_tests.py

  # Run a specific feature
  python run_tests.py --feature auth
  python run_tests.py --feature articles
  python run_tests.py --feature bookmarks
  python run_tests.py --feature subscriptions
  python run_tests.py --feature notifications
  python run_tests.py --feature security
  python run_tests.py --feature worker   # unit tests for worker helper functions

  # Verbose output
  python run_tests.py -v

  # Stop on first failure
  python run_tests.py -x

  # Coverage report
  python run_tests.py --coverage

  # Combine flags
  python run_tests.py --feature auth -v -x
"""

import argparse
import subprocess
import sys
import os

FEATURE_MAP = {
    "auth":          "tests/test_auth.py",
    "articles":      "tests/test_articles.py",
    "bookmarks":     "tests/test_bookmarks.py",
    "subscriptions": "tests/test_subscriptions.py",
    "notifications": "tests/test_notifications.py",
    "security":      "tests/test_security.py",
    "worker":        "tests/test_worker_dedup.py",
}

ALL_TESTS = "tests/"


def main():
    parser = argparse.ArgumentParser(description="HUNGU test runner")
    parser.add_argument(
        "--feature", "-f",
        choices=list(FEATURE_MAP.keys()),
        help="Run tests for a specific feature only",
    )
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose pytest output (-v flag)")
    parser.add_argument("--stop-on-first", "-x", action="store_true",
                        help="Stop after first test failure (-x flag)")
    parser.add_argument("--coverage", "-c", action="store_true",
                        help="Run with pytest-cov coverage report")
    args = parser.parse_args()

    target = FEATURE_MAP[args.feature] if args.feature else ALL_TESTS

    cmd = [sys.executable, "-m", "pytest", target]

    if args.verbose:
        cmd.append("-v")
    if args.stop_on_first:
        cmd.append("-x")
    if args.coverage:
        cmd += [
            "--cov=services/api",
            "--cov=services/worker",
            "--cov-report=term-missing",
        ]

    # Always show short test summary
    cmd += ["-p", "no:warnings", "--tb=short"]

    print(f"\n{'='*60}")
    print(f"  HUNGU Test Runner")
    if args.feature:
        print(f"  Feature: {args.feature}")
    else:
        print(f"  Running: ALL tests")
    print(f"{'='*60}\n")

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
