import json
from pathlib import Path

from evals.models import AgentResponse, ContextRequest, TestCase
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


def test_live_agent_client_uses_typed_context_array_and_simulation_source() -> None:
    case = TestCase.model_validate(
        {
            "case_id": "typed-refill",
            "scenario": "product",
            "input": {"request": {"organization_id": "org-1", "store_id": "store-1", "source": "simulation"}},
            "public_context": {"products": [{"external_product_id": "p-1"}]},
            "hidden_expected_behavior": {},
        }
    )
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"decision_id": "d-1", "decision_status": "candidate", "action": "candidate"}

    class Client:
        def post(self, endpoint, json):
            captured.update({"endpoint": endpoint, "payload": json})
            return Response()

    client = LiveAgentClient("https://api.example.test", auth_token="test-token")
    client._client = Client()
    client.refill_context(
        case,
        AgentResponse.from_payload({"decision_id": "d-1", "decision_status": "waiting_context", "action": "context_request"}),
        ContextRequest(context_request_id="ctx-1", type="products"),
    )

    assert captured["payload"]["products"] == [{"external_product_id": "p-1"}]
    assert "items" not in captured["payload"]
    assert captured["payload"]["source"] == "simulation"
    assert captured["payload"]["captured_at"].endswith("Z")


def test_agent_response_accepts_partial_context_refill_without_action() -> None:
    response = AgentResponse.from_payload(
        {
            "decision_id": "d-1",
            "decision_status": "partial_context",
            "remaining_context_requests": [{"context_request_id": "ctx-logistics", "type": "logistics"}],
            "trace": {"steps": [{"name": "context_gate", "status": "completed"}]},
        }
    )

    assert response.action == "context_request"
