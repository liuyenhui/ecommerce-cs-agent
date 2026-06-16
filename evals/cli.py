from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.gate import evaluate_release_gate
from evals.generator import generate_blind_cases
from evals.runner import DEFAULT_REPORTS_DIR, load_cases, run_cases


DEFAULT_REGRESSION_DIR = Path("evals/cases/regression")
DEFAULT_GENERATED_DIR = Path("evals/cases/generated")
DEFAULT_SCENARIOS_DIR = Path("evals/scenarios")
DEFAULT_BASELINE_PATH = Path("evals/baselines/stable.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate-cases")
    validate_parser.add_argument("path", type=Path)

    run_parser = subparsers.add_parser("run-suite")
    run_parser.add_argument("--suite", required=True)
    run_parser.add_argument("--target", choices=["mock", "live"], default="mock")
    run_parser.add_argument("--target-url")
    run_parser.add_argument("--auth-token")
    run_parser.add_argument("--cases-dir", type=Path, default=DEFAULT_REGRESSION_DIR)
    run_parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    run_parser.add_argument("--run-id")

    generate_parser = subparsers.add_parser("generate-blind")
    generate_parser.add_argument("--suite", required=True)
    generate_parser.add_argument("--count", type=int, required=True)
    generate_parser.add_argument("--seed", required=True)
    generate_parser.add_argument("--scenarios-dir", type=Path, default=DEFAULT_SCENARIOS_DIR)
    generate_parser.add_argument("--output-dir", type=Path, default=DEFAULT_GENERATED_DIR)

    judge_parser = subparsers.add_parser("judge-results")
    judge_parser.add_argument("--results", type=Path, required=True)

    gate_parser = subparsers.add_parser("release-gate")
    gate_parser.add_argument("--results", type=Path, required=True)
    gate_parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_PATH)

    args = parser.parse_args(argv)
    if args.command == "validate-cases":
        return _validate_cases(args.path)
    if args.command == "run-suite":
        return _run_suite(args)
    if args.command == "generate-blind":
        return _generate_blind(args)
    if args.command == "judge-results":
        return _judge_results(args.results)
    if args.command == "release-gate":
        return _release_gate(args.results, args.baseline)
    parser.error(f"unknown command: {args.command}")
    return 2


def _validate_cases(path: Path) -> int:
    cases = load_cases(path)
    print(f"validated {len(cases)} case(s)")
    return 0


def _run_suite(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases_dir, suite=args.suite)
    run = run_cases(
        cases=cases,
        suite=args.suite,
        target=args.target,
        target_url=args.target_url,
        auth_token=args.auth_token,
        reports_dir=args.reports_dir,
        run_id=args.run_id,
    )
    print(json.dumps(run.summary, ensure_ascii=False))
    print(str(args.reports_dir / f"{run.run_id}.jsonl"))
    return 0 if run.summary["blocked"] == 0 else 1


def _generate_blind(args: argparse.Namespace) -> int:
    paths = generate_blind_cases(
        suite=args.suite,
        count=args.count,
        seed=args.seed,
        scenarios_dir=args.scenarios_dir,
        output_dir=args.output_dir,
    )
    print(f"generated {len(paths)} case(s)")
    return 0


def _judge_results(results_path: Path) -> int:
    rows = [
        json.loads(line)
        for line in results_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"judged {len(rows)} result(s)")
    return 0


def _release_gate(results_path: Path, baseline_path: Path) -> int:
    report = evaluate_release_gate(results_path, baseline_path=baseline_path)
    print(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
