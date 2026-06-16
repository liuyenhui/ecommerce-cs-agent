from __future__ import annotations

from evals.models import AgentResponse, AssertionResult, JudgeResult, TestCase


def judge_response(
    case: TestCase,
    response: AgentResponse,
    assertion_results: list[AssertionResult],
) -> JudgeResult:
    """Rule-backed judge used until a real LLM judge is configured."""

    failed_assertions = [result for result in assertion_results if not result.passed]
    if not failed_assertions:
        min_score = case.hidden_expected_behavior.min_judge_score
        return JudgeResult(
            score=5.0,
            passed=min_score is None or 5.0 >= min_score,
            reason="hard rules passed",
        )

    blocked = any(result.blocked for result in failed_assertions)
    score = 0.0 if blocked else 2.0
    failure_type = failed_assertions[0].failure_type
    return JudgeResult(
        score=score,
        passed=False,
        reason=f"hard rules failed: {', '.join(result.name for result in failed_assertions)}",
        failure_type=failure_type,
        needs_review=not blocked,
    )
