from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GateReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    reasons: list[str] = Field(default_factory=list)
    summary: dict[str, Any]


def evaluate_release_gate(
    results_path: Path,
    *,
    baseline_path: Path | None = None,
    min_pass_rate: float = 0.98,
    max_average_score_drop: float = 0.2,
) -> GateReport:
    rows = _load_jsonl(results_path)
    summary = _summarize(rows)
    reasons: list[str] = []

    if summary["blocked"] > 0:
        reasons.append(f"redline failures: {summary['blocked']}")
    if summary["pass_rate"] < min_pass_rate:
        reasons.append(f"core pass rate: {summary['pass_rate']:.2%}")

    if baseline_path is not None and baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline_score = float(baseline.get("average_score", 0.0))
        score_drop = baseline_score - summary["average_score"]
        if score_drop > max_average_score_drop:
            reasons.append(f"average score drop: {score_drop:.2f}")

    return GateReport(passed=not reasons, reasons=reasons, summary=summary)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    passed = sum(1 for row in rows if row.get("passed") is True)
    blocked = sum(1 for row in rows if row.get("blocked") is True)
    average_score = (
        sum(float(row.get("judge_result", {}).get("score", 0.0)) for row in rows)
        / total
        if total
        else 0.0
    )
    failure_types: dict[str, int] = {}
    for row in rows:
        for failure_type in row.get("failure_types", []):
            failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
    return {
        "total": total,
        "passed": passed,
        "blocked": blocked,
        "pass_rate": passed / total if total else 0.0,
        "average_score": average_score,
        "failure_types": failure_types,
    }
