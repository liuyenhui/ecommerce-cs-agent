from __future__ import annotations

import json
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from ecommerce_cs_agent.services.decision_types import DecisionState


class DecisionRepository(Protocol):
    def get_by_request(self, organization_id: str, store_id: str, request_id: str) -> DecisionState | None:
        raise NotImplementedError

    def get_by_decision_id(self, decision_id: str) -> DecisionState | None:
        raise NotImplementedError

    def save_state(
        self,
        *,
        organization_id: str,
        store_id: str,
        request_id: str,
        decision_id: str,
        state: DecisionState,
    ) -> None:
        raise NotImplementedError


class InMemoryDecisionRepository:
    def __init__(self) -> None:
        self._by_request: dict[tuple[str, str, str], DecisionState] = {}
        self._by_decision_id: dict[str, DecisionState] = {}

    def get_by_request(self, organization_id: str, store_id: str, request_id: str) -> DecisionState | None:
        return self._by_request.get((organization_id, store_id, request_id))

    def get_by_decision_id(self, decision_id: str) -> DecisionState | None:
        return self._by_decision_id.get(decision_id)

    def save_state(
        self,
        *,
        organization_id: str,
        store_id: str,
        request_id: str,
        decision_id: str,
        state: DecisionState,
    ) -> None:
        self._by_request[(organization_id, store_id, request_id)] = state
        self._by_decision_id[decision_id] = state


class PostgresDecisionRepository:
    def __init__(self, database_url: str) -> None:
        import psycopg

        self._connect = psycopg.connect
        self._database_url = database_url

    def get_by_request(self, organization_id: str, store_id: str, request_id: str) -> DecisionState | None:
        row = self._fetch_one(
            """
            SELECT state_payload
            FROM app_decision_state
            WHERE organization_id = %s AND store_id = %s AND request_id = %s
            """,
            (organization_id, store_id, request_id),
        )
        return _state_from_payload(row[0]) if row else None

    def get_by_decision_id(self, decision_id: str) -> DecisionState | None:
        row = self._fetch_one(
            "SELECT state_payload FROM app_decision_state WHERE decision_id = %s",
            (decision_id,),
        )
        return _state_from_payload(row[0]) if row else None

    def save_state(
        self,
        *,
        organization_id: str,
        store_id: str,
        request_id: str,
        decision_id: str,
        state: DecisionState,
    ) -> None:
        payload = Jsonb(_state_to_payload(state))
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO app_decision_state (
                        decision_id,
                        organization_id,
                        store_id,
                        request_id,
                        request_payload,
                        response_payload,
                        state_payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (organization_id, store_id, request_id)
                    DO UPDATE SET
                        response_payload = EXCLUDED.response_payload,
                        state_payload = EXCLUDED.state_payload,
                        updated_at = now()
                    """,
                    (
                        decision_id,
                        organization_id,
                        store_id,
                        request_id,
                        Jsonb(state.request),
                        Jsonb(state.response),
                        payload,
                    ),
                )

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()


def _state_from_payload(payload: Any) -> DecisionState:
    if isinstance(payload, str):
        payload = json.loads(payload)
    return DecisionState(
        request=payload["request"],
        response=payload["response"],
        context_refills=_tuple_keyed(payload.get("context_refills", {})),
        action_results=_tuple_keyed(payload.get("action_results", {})),
        feedback=payload.get("feedback", []),
    )


def _state_to_payload(state: DecisionState) -> dict[str, Any]:
    return {
        "request": state.request,
        "response": state.response,
        "context_refills": _string_keyed(state.context_refills),
        "action_results": _string_keyed(state.action_results),
        "feedback": state.feedback,
    }


def _tuple_keyed(payload: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    converted: dict[tuple[str, str], dict[str, Any]] = {}
    for key, value in payload.items():
        if "\u001f" in key:
            left, right = key.split("\u001f", 1)
        elif "|" in key:
            left, right = key.split("|", 1)
        else:
            left, right = key, ""
        converted[(left, right)] = value
    return converted


def _string_keyed(payload: dict[tuple[str, str], dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {f"{left}\u001f{right}": value for (left, right), value in payload.items()}
