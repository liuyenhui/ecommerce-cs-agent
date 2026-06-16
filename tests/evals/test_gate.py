import json
from pathlib import Path

from evals.gate import evaluate_release_gate


def write_results(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")


def passed_row(case_id: str = "case-001", score: float = 5.0) -> dict:
    return {
        "case_id": case_id,
        "suite": "quick",
        "passed": True,
        "blocked": False,
        "failure_types": [],
        "judge_result": {"score": score, "passed": True, "reason": "ok"},
        "assertion_results": [],
    }


def test_release_gate_fails_when_any_result_is_blocked(tmp_path: Path) -> None:
    results_path = tmp_path / "results.jsonl"
    row = passed_row()
    row.update({"passed": False, "blocked": True, "failure_types": ["policy_gate_failure"]})
    write_results(results_path, [row])

    report = evaluate_release_gate(results_path)

    assert report.passed is False
    assert "redline failures: 1" in report.reasons


def test_release_gate_passes_all_current_thresholds_without_baseline(tmp_path: Path) -> None:
    results_path = tmp_path / "results.jsonl"
    write_results(results_path, [passed_row("case-001"), passed_row("case-002")])

    report = evaluate_release_gate(results_path)

    assert report.passed is True
    assert report.summary["pass_rate"] == 1.0


def test_release_gate_fails_when_average_score_drops_against_baseline(
    tmp_path: Path,
) -> None:
    results_path = tmp_path / "results.jsonl"
    baseline_path = tmp_path / "stable.json"
    write_results(results_path, [passed_row(score=4.0)])
    baseline_path.write_text(json.dumps({"average_score": 4.5}), encoding="utf-8")

    report = evaluate_release_gate(results_path, baseline_path=baseline_path)

    assert report.passed is False
    assert "average score drop: 0.50" in report.reasons
