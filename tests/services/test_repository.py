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
    assert "org.id::text = decision.organization_id::text" in connection.executed[0][0]
    assert "st.id::text = decision.store_id::text" in connection.executed[0][0]
    assert connection.executed[0][1] == ("org-001", "store-001", "req-001")
    compat_insert = [item for item in connection.executed if "INSERT INTO app_decision_state" in item[0]][0]
    insert_params = compat_insert[1]
    assert insert_params[:4] == ("decision-001", "org-001", "store-001", "req-001")


def test_postgres_repository_reads_canonical_decision_record_before_compat_state() -> None:
    canonical_state = DecisionState(
        request={"organization_id": "org-001", "store_id": "store-001", "request_id": "req-001"},
        response={"decision_id": "decision-001", "action": "candidate", "decision_status": "candidate"},
        context_refills={("ctx-orders", "idem-001"): {"accepted": True}},
    )
    connection = _FakeConnection(fetch_rows=[(_state_to_payload(canonical_state),)])
    repository = PostgresDecisionRepository("postgresql://example")
    repository._connect = lambda _url: connection

    restored = repository.get_by_request("org-001", "store-001", "req-001")

    assert restored == canonical_state
    assert "FROM decision_record" in connection.executed[0][0]
    assert "state_payload" not in connection.executed[0][0]


def test_postgres_repository_mutation_locks_decision_before_persisting_in_one_transaction() -> None:
    state = DecisionState(
        request={
            "organization_id": "org-001",
            "store_id": "store-001",
            "request_id": "req-001",
            "platform": "pdd",
        },
        response={"decision_id": "decision-001", "action": "context_request"},
    )
    connection = _FakeConnection(fetch_rows=[(_state_to_payload(state),)])
    repository = PostgresDecisionRepository("postgresql://example")
    connection_count = 0

    def connect(_url: str) -> _FakeConnection:
        nonlocal connection_count
        connection_count += 1
        return connection

    repository._connect = connect

    result = repository.mutate_state(
        "decision-001",
        lambda locked: _record_context_refill(locked),
    )

    assert result == "accepted"
    assert connection_count == 1
    lock_index = next(
        index
        for index, (sql, _params) in enumerate(connection.executed)
        if "FOR UPDATE" in sql
    )
    persist_index = next(
        index
        for index, (sql, _params) in enumerate(connection.executed)
        if "INSERT INTO decision_graph_checkpoint" in sql
    )
    assert "FROM decision_record" in connection.executed[lock_index][0]
    assert lock_index < persist_index
    checkpoint = connection.executed[persist_index][1]
    persisted = checkpoint[-1].obj
    assert "ctx-orders-001\u001fidem-orders" in persisted["context_refills"]


def _record_context_refill(state: DecisionState | None) -> str:
    assert state is not None
    state.context_refills[("ctx-orders-001", "idem-orders")] = {"accepted": True}
    return "accepted"


def test_postgres_repository_falls_back_to_compat_state_when_canonical_missing() -> None:
    compat_state = DecisionState(
        request={"organization_id": "org-001", "store_id": "store-001", "request_id": "req-001"},
        response={"decision_id": "decision-001", "action": "context_request"},
    )
    connection = _FakeConnection(fetch_rows=[None, (_state_to_payload(compat_state),)])
    repository = PostgresDecisionRepository("postgresql://example")
    repository._connect = lambda _url: connection

    restored = repository.get_by_request("org-001", "store-001", "req-001")

    assert restored == compat_state
    assert "FROM decision_record" in connection.executed[0][0]
    assert "FROM app_decision_state" in connection.executed[1][0]


def test_postgres_repository_dual_writes_canonical_runtime_tables_and_compat_state() -> None:
    state = DecisionState(
        request={
            "organization_id": "org-001",
            "store_id": "store-001",
            "request_id": "req-001",
            "platform": "pdd",
            "message": {"external_message_id": "msg-001", "content": "什么时候发货"},
            "conversation": {"external_conversation_id": "conv-001", "buyer_ref": "buyer-001"},
        },
        response={
            "decision_id": "decision-001",
            "decision_status": "action_request",
            "action": "action_request",
            "risk_level": "medium",
            "risk_flags": [],
            "trace": {
                "graph_version": "reply-decision-graph-v1",
                "steps": [{"step_id": "classify", "name": "classify_request", "status": "completed"}],
            },
            "context_requests": [
                {"context_request_id": "ctx-orders-001", "type": "orders"},
            ],
            "action_requests": [
                {
                    "action_id": "action-001",
                    "action_type": "update-note",
                    "idempotency_key": "idem-action-001",
                    "payload": {"instruction": "备注"},
                },
            ],
        },
        context_refills={
            ("ctx-orders-001", "idem-ctx-001"): {
                "decision_id": "decision-001",
                "context_request_id": "ctx-orders-001",
                "accepted": True,
                "_request_payload": {"source": "external-system", "items": [{"id": "order-001"}]},
            }
        },
        action_results={
            ("action-001", "idem-action-result-001"): {
                "decision_id": "decision-001",
                "action_id": "action-001",
                "accepted": True,
                "_request_payload": {"status": "success"},
            }
        },
        feedback=[
            {
                "human_reply_id": "human-reply-001",
                "decision_id": "decision-001",
                "human_reply": "已回复",
                "resolution_status": "resolved",
            }
        ],
    )
    connection = _FakeConnection(fetch_rows=[])
    repository = PostgresDecisionRepository("postgresql://example")
    repository._connect = lambda _url: connection

    repository.save_state(
        organization_id="org-001",
        store_id="store-001",
        request_id="req-001",
        decision_id="decision-001",
        state=state,
    )

    executed_sql = "\n".join(sql for sql, _params in connection.executed)
    assert "INSERT INTO organization" in executed_sql
    assert "INSERT INTO store" in executed_sql
    assert "INSERT INTO conversation" in executed_sql
    assert "INSERT INTO message" in executed_sql
    assert "INSERT INTO decision_record" in executed_sql
    assert "INSERT INTO decision_trace_step" in executed_sql
    assert "INSERT INTO decision_graph_checkpoint" in executed_sql
    assert "INSERT INTO context_snapshot" in executed_sql
    assert "INSERT INTO action_request" in executed_sql
    assert "INSERT INTO action_result" in executed_sql
    assert "INSERT INTO human_reply" in executed_sql
    assert "INSERT INTO app_decision_state" in executed_sql
    checkpoint = [item for item in connection.executed if "INSERT INTO decision_graph_checkpoint" in item[0]][0]
    assert "thread_id" in checkpoint[0]
    assert "graph_version" in checkpoint[0]
    assert "node_name" in checkpoint[0]
    assert "decision_status" in checkpoint[0]
    assert "state_json" in checkpoint[0]
    assert checkpoint[1][3:7] == (
        "decision-001",
        "decision-001",
        "reply-decision-graph-v1",
        "persist_trace",
    )
    assert checkpoint[1][7] == "action_request"


def test_postgres_repository_scopes_canonical_request_idempotency_and_checkpoints_by_store() -> None:
    connection = _FakeConnection(fetch_rows=[])
    repository = PostgresDecisionRepository("postgresql://example")
    repository._connect = lambda _url: connection

    for store_id, decision_id in (("store-001", "decision-store-001"), ("store-002", "decision-store-002")):
        state = DecisionState(
            request={
                "organization_id": "org-001",
                "store_id": store_id,
                "request_id": "req-shared",
                "platform": "pdd",
                "message": {"external_message_id": f"msg-{store_id}", "content": "商品材质？"},
                "conversation": {"external_conversation_id": f"conv-{store_id}"},
            },
            response={
                "decision_id": decision_id,
                "decision_status": "candidate",
                "action": "candidate",
                "trace": {"graph_version": "reply-decision-graph-v1", "steps": []},
            },
        )
        repository.save_state(
            organization_id="org-001",
            store_id=store_id,
            request_id="req-shared",
            decision_id=decision_id,
            state=state,
        )

    decision_inserts = [item for item in connection.executed if "INSERT INTO decision_record" in item[0]]
    assert len(decision_inserts) == 2
    assert all("ON CONFLICT (organization_id, store_id, request_id)" in sql for sql, _params in decision_inserts)
    checkpoints = [params for sql, params in connection.executed if "INSERT INTO decision_graph_checkpoint" in sql]
    assert [(params[2], params[3]) for params in checkpoints] == [
        ("store-001", "decision-store-001"),
        ("store-002", "decision-store-002"),
    ]


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
