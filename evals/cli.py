from __future__ import annotations

import argparse
import os
import sys

from .runner import LiveAgentClient, MockAgentClient, QuickLiveSuite, format_result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_suite = subparsers.add_parser("run-suite", help="Run an evaluation suite.")
    run_suite.add_argument("--suite", choices=["quick"], required=True)
    run_suite.add_argument("--target", choices=["mock", "live"], required=True)
    run_suite.add_argument("--target-url")
    run_suite.add_argument("--timeout", type=float, default=10.0)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run-suite":
        return run_suite(args)

    parser.error(f"unsupported command: {args.command}")
    return 2


def run_suite(args: argparse.Namespace) -> int:
    if args.target == "mock":
        client = MockAgentClient()
    else:
        target_url = args.target_url or os.environ.get("TARGET_BASE_URL")
        if not target_url:
            print("live target requires --target-url or TARGET_BASE_URL", file=sys.stderr)
            return 2
        token = os.environ.get("AGENT_API_TOKEN")
        client = LiveAgentClient(target_url, token=token, timeout=args.timeout)

    suite = QuickLiveSuite(client)
    results = suite.run()

    for result in results:
        print(format_result(result))
        if not result.passed and result.message:
            print(f"  {result.message}")

    passed = all(result.passed for result in results)
    summary = f"quick suite {'PASS' if passed else 'FAIL'} target={args.target}"
    if args.target == "live":
        summary = f"{summary} url={(args.target_url or os.environ.get('TARGET_BASE_URL', '')).rstrip('/')}"
    print(summary)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
