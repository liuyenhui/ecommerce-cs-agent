from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .runner import LiveAgentClient, MockAgentClient, QuickLiveSuite, format_result, load_cases, run_cases
from .simulation import SimulationFixture, SimulationRunner, load_simulation_fixture


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_suite = subparsers.add_parser("run-suite", help="Run an evaluation suite.")
    run_suite.add_argument("--suite", choices=["quick", "redline"], required=True)
    run_suite.add_argument("--target", choices=["mock", "live"], required=True)
    run_suite.add_argument("--target-url")
    run_suite.add_argument("--timeout", type=float, default=10.0)

    run_simulation = subparsers.add_parser(
        "run-simulation", help="Run a fixed snapshot-backed ACS multi-turn simulation."
    )
    run_simulation.add_argument("--fixture", type=Path, required=True, help="Fixed conversation definition JSON")
    run_simulation.add_argument("--snapshot", type=Path, help="Fixed redacted store snapshot JSON")
    run_simulation.add_argument("--target", choices=["mock", "live"], required=True)
    run_simulation.add_argument("--target-url")
    run_simulation.add_argument("--reports-dir", type=Path, default=Path("reports/evals"))
    run_simulation.add_argument("--run-id")
    run_simulation.add_argument("--timeout", type=float, default=30.0)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run-suite":
        return run_suite(args)
    if args.command == "run-simulation":
        return run_simulation(args)

    parser.error(f"unsupported command: {args.command}")
    return 2


def run_suite(args: argparse.Namespace) -> int:
    if args.suite == "redline":
        return run_redline_suite(args)

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


def run_redline_suite(args: argparse.Namespace) -> int:
    target_url = args.target_url or os.environ.get("TARGET_BASE_URL")
    if args.target == "live" and not target_url:
        print("live target requires --target-url or TARGET_BASE_URL", file=sys.stderr)
        return 2

    cases = [
        case
        for case in load_cases(Path("evals/cases/regression"), suite="quick")
        if case.is_redline
    ]
    if not cases:
        print("redline suite has no matching cases", file=sys.stderr)
        return 1
    run = run_cases(
        cases=cases,
        suite="redline",
        target=args.target,
        target_url=target_url,
        auth_token=os.environ.get("AGENT_API_TOKEN"),
    )
    for result in run.results:
        prefix = "PASS" if result.passed else "FAIL"
        details = ",".join(result.failure_types) if result.failure_types else "ok"
        print(f"{prefix} {result.case_id} {details}")
    passed = run.summary["total"] > 0 and run.summary["passed"] == run.summary["total"] and run.summary["blocked"] == 0
    summary = f"redline suite {'PASS' if passed else 'FAIL'} target={args.target}"
    if args.target == "live":
        summary = f"{summary} url={(target_url or '').rstrip('/')}"
    print(summary)
    return 0 if passed else 1


def run_simulation(args: argparse.Namespace) -> int:
    try:
        fixture = (
            load_simulation_fixture(args.snapshot, args.fixture)
            if args.snapshot
            else SimulationFixture.model_validate_json(args.fixture.read_text(encoding="utf-8"))
        )
    except (OSError, ValueError) as exc:
        print(f"simulation fixture invalid: {exc}", file=sys.stderr)
        return 2
    if args.target == "mock":
        client = MockAgentClient()
    else:
        target_url = args.target_url or os.environ.get("TARGET_BASE_URL")
        if not target_url:
            print("live target requires --target-url or TARGET_BASE_URL", file=sys.stderr)
            return 2
        client = LiveAgentClient(
            target_url, auth_token=os.environ.get("AGENT_API_TOKEN"), timeout=args.timeout
        )
    run_id = args.run_id or f"acs-simulation-{os.urandom(6).hex()}"
    result = SimulationRunner(client, reports_dir=args.reports_dir).run(fixture, run_id=run_id)
    summary = result.summary
    status = "PASS" if summary["all_messages_passed"] else "FAIL"
    print(
        f"simulation {status} run_id={run_id} total={summary['total_messages']} "
        f"passed={summary['passed']} blocked={summary['blocked']} needs_review={summary['needs_review']}"
    )
    return 0 if summary["all_messages_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
