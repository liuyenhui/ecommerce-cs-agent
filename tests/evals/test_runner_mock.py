import json
from pathlib import Path

from evals.models import TestCase
from evals.runner import LiveAgentClient, run_cases


def test_mock_runner_writes_jsonl_report_with_context_refill_evidence(
    tmp_path: Path,
) -> None:
    case = TestCase.model_validate(
        {
            "case_id": "mock-context-001",
            "suite": "quick",
            "scenario": "order_logistics",
            "risk_tags": ["missing_context"],
            "input": {"request": {"request_id": "req-001"}},
            "public_context": {
                "orders": [{"external_order_id": "order-001"}],
                "logistics": [{"status": "pending"}],
            },
            "hidden_expected_behavior": {
                "expected_action": "context_request",
                "required_context_request_types": ["orders", "logistics"],
                "forbidden_actions": ["auto_reply"],
            },
            "assertions": {},
            "generation": {"seed": "seed-001"},
        }
    )

    run = run_cases(
        cases=[case],
        suite="quick",
        target="mock",
        reports_dir=tmp_path,
        run_id="run-001",
    )

    report_path = tmp_path / "run-001.jsonl"
    rows = [json.loads(line) for line in report_path.read_text().splitlines()]
    assert run.summary["total"] == 1
    assert rows[0]["case_id"] == "mock-context-001"
    assert rows[0]["passed"] is True
    assert rows[0]["context_refill_calls"] == ["orders", "logistics"]


def test_live_agent_client_sends_bearer_token_when_configured() -> None:
    client = LiveAgentClient("https://api.example.test", auth_token="test-token")

    assert client._client.headers["Authorization"] == "Bearer test-token"
