from __future__ import annotations

from typing import Any

from ecommerce_cs_agent.services.decision_types import DecisionState
from ecommerce_cs_agent.services.repository import (
    InMemoryDecisionRepository,
    PostgresDecisionRepository,
    _state_from_payload,
    _state_to_payload,
)


def test_in_memory_repository_round_trips_decision_state_by_request_and_decision_id() -> None:
    repository = InMemoryDecisionRepository()
    state = DecisionState(
        request={"organization_id": "org-001", "store_id": "store-001", "request_id": "req-001"},
        response={"decision_id": "decision-001", "action": "candidate"},
    )

    repository.save_state(
        organization_id="org-001",
        store_id="store-001",
        request_id="req-001",
        decision_id="decision-001",
        state=state,
    )

    assert repository.get_by_request("org-001", "store-001", "req-001") == state
    assert repository.get_by_decision_id("decision-001") == state


def test_state_payload_serializes_tuple_idempotency_keys_for_jsonb() -> None:
    state = DecisionState(
        request={"request_id": "req-001"},
        response={"decision_id": "decision-001"},
        context_refills={
            ("ctx-orders", "idem-001"): {"accepted": True},
        },
        action_results={
            ("action-001", "idem-002"): {"accepted": True},
        },
        feedback=[{"human_reply_id": "human-reply-001"}],
    )

    payload = _state_to_payload(state)
    restored = _state_from_payload(payload)

    assert list(payload["context_refills"]) == ["ctx-orders\u001fidem-001"]
    assert restored.context_refills[("ctx-orders", "idem-001")] == {"accepted": True}
    assert restored.action_results[("action-001", "idem-002")] == {"accepted": True}
    assert restored.feedback == [{"human_reply_id": "human-reply-001"}]


def test_postgres_repository_uses_tenant_request_lookup_and_jsonb_state() -> None:
    saved_state = DecisionState(
        request={"organization_id": "org-001", "store_id": "store-001", "request_id": "req-001"},
        response={"decision_id": "decision-001", "action": "candidate"},
        context_refills={("ctx-001", "idem-001"): {"accepted": True}},
    )
    connection = _FakeConnection(fetch_rows=[(_state_to_payload(saved_state),)])
    repository = PostgresDecisionRepository("postgresql://example")
    repository._connect = lambda _url: connection

    restored = repository.get_by_request("org-001", "store-001", "req-001")
    repository.save_state(
        organization_id="org-001",
        store_id="store-001",
        request_id="req-001",
        decision_id="decision-001",
        state=saved_state,
    )

    assert restored is not None
    assert restored.context_refills[("ctx-001", "idem-001")] == {"accepted": True}
    assert connection.executed[0][1] == ("org-001", "store-001", "req-001")
    insert_params = connection.executed[1][1]
    assert insert_params[:4] == ("decision-001", "org-001", "store-001", "req-001")


class _FakeConnection:
    def __init__(self, fetch_rows: list[tuple[Any, ...]]) -> None:
        self.fetch_rows = fetch_rows
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def cursor(self) -> "_FakeCursor":
        return _FakeCursor(self)


class _FakeCursor:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        self.connection.executed.append((sql, params))

    def fetchone(self) -> tuple[Any, ...] | None:
        if self.connection.fetch_rows:
            return self.connection.fetch_rows.pop(0)
        return None
