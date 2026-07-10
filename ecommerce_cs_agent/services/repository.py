from __future__ import annotations

import json
import re
from threading import RLock
from typing import Any, Callable, Protocol, TypeVar

from psycopg.types.json import Jsonb

from ecommerce_cs_agent.services.decision_types import DecisionState


MutationResult = TypeVar("MutationResult")


class DecisionRepository(Protocol):
    def get_by_request(self, organization_id: str, store_id: str, request_id: str) -> DecisionState | None:
        raise NotImplementedError

    def get_by_decision_id(self, decision_id: str) -> DecisionState | None:
        raise NotImplementedError

    def list_recent(
        self,
        organization_id: str | None = None,
        store_id: str | None = None,
        limit: int = 50,
    ) -> list[DecisionState]:
        raise NotImplementedError

    def recall_knowledge(
        self,
        organization_id: str,
        store_id: str,
        query: str,
        limit: int = 5,
        *,
        external_product_id: str | None = None,
        listing_ref: str | None = None,
    ) -> list[dict[str, Any]]:
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

    def mutate_state(
        self,
        decision_id: str,
        mutation: Callable[[DecisionState | None], MutationResult],
    ) -> MutationResult:
        raise NotImplementedError


class InMemoryDecisionRepository:
    def __init__(self) -> None:
        self._by_request: dict[tuple[str, str, str], DecisionState] = {}
        self._by_decision_id: dict[str, DecisionState] = {}
        self._mutation_lock = RLock()

    def get_by_request(self, organization_id: str, store_id: str, request_id: str) -> DecisionState | None:
        return self._by_request.get((organization_id, store_id, request_id))

    def get_by_decision_id(self, decision_id: str) -> DecisionState | None:
        return self._by_decision_id.get(decision_id)

    def list_recent(
        self,
        organization_id: str | None = None,
        store_id: str | None = None,
        limit: int = 50,
    ) -> list[DecisionState]:
        states = list(self._by_decision_id.values())
        if organization_id:
            states = [item for item in states if str(item.request.get("organization_id")) == organization_id]
        if store_id:
            states = [item for item in states if str(item.request.get("store_id")) == store_id]
        return states[-limit:][::-1]

    def recall_knowledge(
        self,
        organization_id: str,
        store_id: str,
        query: str,
        limit: int = 5,
        *,
        external_product_id: str | None = None,
        listing_ref: str | None = None,
    ) -> list[dict[str, Any]]:
        return []

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

    def mutate_state(
        self,
        decision_id: str,
        mutation: Callable[[DecisionState | None], MutationResult],
    ) -> MutationResult:
        with self._mutation_lock:
            return mutation(self._by_decision_id.get(decision_id))


class PostgresDecisionRepository:
    def __init__(self, database_url: str) -> None:
        import psycopg

        self._connect = psycopg.connect
        self._database_url = database_url

    def get_by_request(self, organization_id: str, store_id: str, request_id: str) -> DecisionState | None:
        row = self._fetch_one(
            """
            SELECT checkpoint.state
            FROM decision_record decision
            JOIN organization org ON org.id::text = decision.organization_id::text
            JOIN store st
              ON st.id::text = decision.store_id::text
             AND st.organization_id = org.id
            JOIN decision_graph_checkpoint checkpoint
              ON checkpoint.decision_id = decision.decision_id
             AND checkpoint.checkpoint_key = 'latest'
            WHERE org.external_organization_id = %s
              AND st.external_store_id = %s
              AND decision.request_id = %s
            """,
            (organization_id, store_id, request_id),
        )
        if row:
            return _state_from_payload(row[0])
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
            """
            SELECT checkpoint.state
            FROM decision_record decision
            JOIN decision_graph_checkpoint checkpoint
              ON checkpoint.decision_id = decision.decision_id
             AND checkpoint.checkpoint_key = 'latest'
            WHERE decision.decision_id = %s
            """,
            (decision_id,),
        )
        if row:
            return _state_from_payload(row[0])
        row = self._fetch_one(
            "SELECT state_payload FROM app_decision_state WHERE decision_id = %s",
            (decision_id,),
        )
        return _state_from_payload(row[0]) if row else None

    def list_recent(
        self,
        organization_id: str | None = None,
        store_id: str | None = None,
        limit: int = 50,
    ) -> list[DecisionState]:
        conditions = ["checkpoint.checkpoint_key = 'latest'"]
        params: list[Any] = []
        if organization_id:
            conditions.append("org.external_organization_id = %s")
            params.append(organization_id)
        if store_id:
            conditions.append("st.external_store_id = %s")
            params.append(store_id)
        params.append(limit)
        rows = self._fetch_all(
            f"""
            SELECT checkpoint.state
            FROM decision_record decision
            JOIN organization org ON org.id::text = decision.organization_id::text
            JOIN store st ON st.id::text = decision.store_id::text
            JOIN decision_graph_checkpoint checkpoint
              ON checkpoint.decision_id = decision.decision_id
            WHERE {' AND '.join(conditions)}
            ORDER BY decision.created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        return [_state_from_payload(row[0]) for row in rows]

    def recall_knowledge(
        self,
        organization_id: str,
        store_id: str,
        query: str,
        limit: int = 5,
        *,
        external_product_id: str | None = None,
        listing_ref: str | None = None,
    ) -> list[dict[str, Any]]:
        terms = _search_terms(query)
        requested_product_id = str(external_product_id or "")
        rows = self._fetch_all(
            """
            SELECT entry.id::text, product.public_product_id, product.external_product_id,
                   entry.scope, entry.content,
                   embedding.embedding_model, embedding.chunk_index
            FROM knowledge_entry entry
            JOIN organization org ON org.id = entry.organization_id
            JOIN store st ON st.id::text = entry.store_id::text AND st.organization_id = org.id
            LEFT JOIN product product
              ON product.id = entry.product_id
             AND product.organization_id = entry.organization_id
             AND product.store_id::text = entry.store_id::text
            JOIN product_knowledge_candidate candidate
              ON candidate.id = entry.source_product_candidate_id
             AND candidate.organization_id = entry.organization_id
             AND candidate.store_id::text = entry.store_id::text
            LEFT JOIN knowledge_embedding embedding
              ON embedding.knowledge_entry_id = entry.id
             AND embedding.organization_id = entry.organization_id
             AND embedding.store_id::text = entry.store_id::text
             AND embedding.chunk_index = 0
            WHERE org.external_organization_id = %s
              AND st.external_store_id = %s
              AND entry.status = 'approved'
              AND candidate.review_status = 'accepted'
              AND (
                (entry.scope IN ('store', 'tenant') AND entry.product_id IS NULL)
                OR (
                  %s <> ''
                  AND entry.scope = 'product'
                  AND (product.external_product_id = %s OR product.public_product_id = %s)
                )
              )
              AND (
                %s::text[] = ARRAY[]::text[]
                OR EXISTS (
                  SELECT 1
                  FROM unnest(%s::text[]) AS term
                  WHERE entry.content ILIKE '%%' || term || '%%'
                )
              )
            ORDER BY entry.updated_at DESC
            LIMIT %s
            """,
            (
                organization_id,
                store_id,
                requested_product_id,
                requested_product_id,
                requested_product_id,
                terms,
                terms,
                limit,
            ),
        )
        return [
            {
                "knowledge_entry_id": str(row[0]),
                "product_id": row[1],
                "external_product_id": row[2],
                "scope": row[3],
                "content": row[4],
                "embedding_model": row[5],
                "chunk_index": row[6],
            }
            for row in rows
        ]

    def save_state(
        self,
        *,
        organization_id: str,
        store_id: str,
        request_id: str,
        decision_id: str,
        state: DecisionState,
    ) -> None:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                self._save_state_with_cursor(
                    cur,
                    organization_id=organization_id,
                    store_id=store_id,
                    request_id=request_id,
                    decision_id=decision_id,
                    state=state,
                )

    def mutate_state(
        self,
        decision_id: str,
        mutation: Callable[[DecisionState | None], MutationResult],
    ) -> MutationResult:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT checkpoint.state
                    FROM decision_record decision
                    JOIN decision_graph_checkpoint checkpoint
                      ON checkpoint.decision_id = decision.decision_id
                     AND checkpoint.checkpoint_key = 'latest'
                    WHERE decision.decision_id = %s
                    FOR UPDATE OF decision, checkpoint
                    """,
                    (decision_id,),
                )
                row = cur.fetchone()
                if not row:
                    cur.execute(
                        """
                        SELECT state_payload
                        FROM app_decision_state
                        WHERE decision_id = %s
                        FOR UPDATE
                        """,
                        (decision_id,),
                    )
                    row = cur.fetchone()
                state = _state_from_payload(row[0]) if row else None
                result = mutation(state)
                if state is not None:
                    organization_id, store_id, request_id = _request_key(state.request)
                    self._save_state_with_cursor(
                        cur,
                        organization_id=organization_id,
                        store_id=store_id,
                        request_id=request_id,
                        decision_id=decision_id,
                        state=state,
                    )
                return result

    def _save_state_with_cursor(
        self,
        cur: Any,
        *,
        organization_id: str,
        store_id: str,
        request_id: str,
        decision_id: str,
        state: DecisionState,
    ) -> None:
        state_payload = _state_to_payload(state)
        platform = str(state.request.get("platform", "unknown"))
        conversation = state.request.get("conversation") or {}
        message = state.request.get("message") or {}
        response = state.response
        self._upsert_tenant_store(cur, organization_id, store_id, platform)
        self._upsert_conversation(cur, organization_id, store_id, platform, conversation)
        self._upsert_message(cur, organization_id, store_id, platform, conversation, message)
        self._upsert_decision_record(
            cur,
            organization_id=organization_id,
            store_id=store_id,
            request_id=request_id,
            decision_id=decision_id,
            platform=platform,
            state=state,
        )
        self._replace_trace_steps(cur, organization_id, store_id, decision_id, response)
        self._upsert_checkpoint(cur, organization_id, store_id, decision_id, state_payload)
        self._upsert_context_snapshots(cur, organization_id, store_id, decision_id, state)
        self._upsert_action_requests(cur, organization_id, store_id, decision_id, response)
        self._upsert_action_results(cur, organization_id, store_id, decision_id, state)
        self._upsert_human_reply(cur, organization_id, store_id, decision_id, state)
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
                Jsonb(state_payload),
            ),
        )

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchone()

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with self._connect(self._database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()

    def _upsert_tenant_store(self, cur: Any, organization_id: str, store_id: str, platform: str) -> None:
        cur.execute(
            """
            INSERT INTO organization (external_organization_id, name, settings)
            VALUES (%s, %s, %s)
            ON CONFLICT (external_organization_id) WHERE external_organization_id IS NOT NULL
            DO UPDATE SET updated_at = now()
            """,
            (organization_id, organization_id, Jsonb({"external_organization_id": organization_id})),
        )
        cur.execute(
            """
            INSERT INTO store (organization_id, name, platform, external_store_id, settings)
            VALUES (
                (SELECT id FROM organization WHERE external_organization_id = %s),
                %s,
                %s,
                %s,
                %s
            )
            ON CONFLICT (organization_id, platform, external_store_id)
            DO UPDATE SET updated_at = now()
            """,
            (organization_id, store_id, platform, store_id, Jsonb({"external_store_id": store_id})),
        )

    def _upsert_conversation(
        self,
        cur: Any,
        organization_id: str,
        store_id: str,
        platform: str,
        conversation: dict[str, Any],
    ) -> None:
        external_conversation_id = str(conversation.get("external_conversation_id") or "conversation-unknown")
        cur.execute(
            """
            INSERT INTO conversation (
                organization_id, store_id, platform, external_conversation_id, buyer_ref, summary
            )
            VALUES (
                (SELECT id FROM organization WHERE external_organization_id = %s),
                (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                  WHERE org.external_organization_id = %s AND st.platform = %s AND st.external_store_id = %s),
                %s,
                %s,
                %s,
                %s
            )
            ON CONFLICT (organization_id, store_id, platform, external_conversation_id)
            DO UPDATE SET buyer_ref = EXCLUDED.buyer_ref, summary = EXCLUDED.summary, updated_at = now()
            """,
            (
                organization_id,
                organization_id,
                platform,
                store_id,
                platform,
                external_conversation_id,
                conversation.get("buyer_ref"),
                Jsonb({"messages": conversation.get("messages", [])}),
            ),
        )

    def _upsert_message(
        self,
        cur: Any,
        organization_id: str,
        store_id: str,
        platform: str,
        conversation: dict[str, Any],
        message: dict[str, Any],
    ) -> None:
        external_conversation_id = str(conversation.get("external_conversation_id") or "conversation-unknown")
        external_message_id = str(message.get("external_message_id") or f"message-{external_conversation_id}")
        cur.execute(
            """
            INSERT INTO message (
                organization_id, store_id, conversation_id, platform, external_message_id,
                direction, message_type, content_redacted, raw_payload
            )
            VALUES (
                (SELECT id FROM organization WHERE external_organization_id = %s),
                (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                  WHERE org.external_organization_id = %s AND st.platform = %s AND st.external_store_id = %s),
                (SELECT conv.id FROM conversation conv
                  JOIN organization org ON org.id::text = conv.organization_id::text
                  JOIN store st ON st.id::text = conv.store_id::text
                  WHERE org.external_organization_id = %s
                    AND st.platform = %s
                    AND st.external_store_id = %s
                    AND conv.external_conversation_id = %s),
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            ON CONFLICT (organization_id, store_id, platform, external_message_id)
            DO UPDATE SET content_redacted = EXCLUDED.content_redacted, raw_payload = EXCLUDED.raw_payload
            """,
            (
                organization_id,
                organization_id,
                platform,
                store_id,
                organization_id,
                platform,
                store_id,
                external_conversation_id,
                platform,
                external_message_id,
                str(message.get("sender_type", "buyer")),
                str(message.get("type", "text")),
                message.get("content"),
                Jsonb(message),
            ),
        )

    def _upsert_decision_record(
        self,
        cur: Any,
        *,
        organization_id: str,
        store_id: str,
        request_id: str,
        decision_id: str,
        platform: str,
        state: DecisionState,
    ) -> None:
        conversation = state.request.get("conversation") or {}
        message = state.request.get("message") or {}
        response = state.response
        cur.execute(
            """
            INSERT INTO decision_record (
                decision_id, organization_id, store_id, conversation_id, message_id,
                request_id, status, decision_type, risk_level, reasons, response_payload
            )
            VALUES (
                %s,
                (SELECT id FROM organization WHERE external_organization_id = %s),
                (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                  WHERE org.external_organization_id = %s AND st.platform = %s AND st.external_store_id = %s),
                (SELECT conv.id FROM conversation conv
                  JOIN organization org ON org.id::text = conv.organization_id::text
                  JOIN store st ON st.id::text = conv.store_id::text
                  WHERE org.external_organization_id = %s
                    AND st.platform = %s
                    AND st.external_store_id = %s
                    AND conv.external_conversation_id = %s),
                (SELECT msg.id FROM message msg
                  JOIN organization org ON org.id::text = msg.organization_id::text
                  JOIN store st ON st.id::text = msg.store_id::text
                  WHERE org.external_organization_id = %s
                    AND st.platform = %s
                    AND st.external_store_id = %s
                    AND msg.external_message_id = %s),
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            ON CONFLICT (organization_id, store_id, request_id)
            DO UPDATE SET
                status = EXCLUDED.status,
                decision_type = EXCLUDED.decision_type,
                risk_level = EXCLUDED.risk_level,
                reasons = EXCLUDED.reasons,
                response_payload = EXCLUDED.response_payload,
                updated_at = now()
            """,
            (
                decision_id,
                organization_id,
                organization_id,
                platform,
                store_id,
                organization_id,
                platform,
                store_id,
                str(conversation.get("external_conversation_id") or "conversation-unknown"),
                organization_id,
                platform,
                store_id,
                str(message.get("external_message_id") or f"message-{conversation.get('external_conversation_id', 'unknown')}"),
                request_id,
                str(response.get("decision_status", response.get("action", "unknown"))),
                str(response.get("action", "unknown")),
                str(response.get("risk_level", "unknown")),
                Jsonb(response.get("risk_flags", [])),
                Jsonb(response),
            ),
        )

    def _replace_trace_steps(
        self,
        cur: Any,
        organization_id: str,
        store_id: str,
        decision_id: str,
        response: dict[str, Any],
    ) -> None:
        trace = response.get("trace") or {}
        steps = trace.get("steps") or []
        for index, step in enumerate(steps, start=1):
            cur.execute(
                """
                INSERT INTO decision_trace_step (
                    organization_id, store_id, decision_id, step_name, step_order, status, summary
                )
                VALUES (
                    (SELECT id FROM organization WHERE external_organization_id = %s),
                    (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                      WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                ON CONFLICT (decision_id, step_order)
                DO UPDATE SET step_name = EXCLUDED.step_name, status = EXCLUDED.status, summary = EXCLUDED.summary
                """,
                (
                    organization_id,
                    organization_id,
                    store_id,
                    decision_id,
                    str(step.get("name", step.get("step_id", "step"))),
                    index,
                    str(step.get("status", "completed")),
                    Jsonb(step),
                ),
            )

    def _upsert_checkpoint(
        self,
        cur: Any,
        organization_id: str,
        store_id: str,
        decision_id: str,
        state_payload: dict[str, Any],
    ) -> None:
        trace = state_payload.get("response", {}).get("trace") or {}
        graph_version = str(trace.get("graph_version") or "reply-decision-graph-v1")
        node_name = "persist_trace"
        decision_status = str(state_payload.get("response", {}).get("decision_status") or "completed")
        cur.execute(
            """
            INSERT INTO decision_graph_checkpoint (
                organization_id, store_id, decision_id, thread_id, graph_version, node_name,
                decision_status, checkpoint_key, state, state_json
            )
            VALUES (
                (SELECT id FROM organization WHERE external_organization_id = %s),
                (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                  WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                %s,
                %s,
                %s,
                %s,
                %s,
                'latest',
                %s,
                %s
            )
            ON CONFLICT (decision_id, checkpoint_key)
            DO UPDATE SET
                thread_id = EXCLUDED.thread_id,
                graph_version = EXCLUDED.graph_version,
                node_name = EXCLUDED.node_name,
                decision_status = EXCLUDED.decision_status,
                state = EXCLUDED.state,
                state_json = EXCLUDED.state_json,
                created_at = now()
            """,
            (
                organization_id,
                organization_id,
                store_id,
                decision_id,
                decision_id,
                graph_version,
                node_name,
                decision_status,
                Jsonb(state_payload),
                Jsonb(state_payload),
            ),
        )

    def _upsert_context_snapshots(
        self,
        cur: Any,
        organization_id: str,
        store_id: str,
        decision_id: str,
        state: DecisionState,
    ) -> None:
        response_contexts = {
            item.get("context_request_id"): item.get("type", "unknown")
            for item in state.response.get("context_requests", [])
        }
        for (context_request_id, _idempotency_key), result in state.context_refills.items():
            request_payload = result.get("_request_payload", {})
            cur.execute(
                """
                INSERT INTO context_snapshot (
                    organization_id, store_id, decision_id, context_request_id,
                    context_type, source, payload
                )
                VALUES (
                    (SELECT id FROM organization WHERE external_organization_id = %s),
                    (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                      WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                ON CONFLICT (decision_id, context_request_id)
                DO UPDATE SET source = EXCLUDED.source, payload = EXCLUDED.payload, captured_at = now()
                """,
                (
                    organization_id,
                    organization_id,
                    store_id,
                    decision_id,
                    context_request_id,
                    str(response_contexts.get(context_request_id, "unknown")),
                    str(request_payload.get("source", "api")),
                    Jsonb(request_payload),
                ),
            )

    def _upsert_action_requests(
        self,
        cur: Any,
        organization_id: str,
        store_id: str,
        decision_id: str,
        response: dict[str, Any],
    ) -> None:
        for action in response.get("action_requests", []):
            cur.execute(
                """
                INSERT INTO action_request (
                    organization_id, store_id, decision_id, action_id, action_type,
                    status, idempotency_key, request_payload
                )
                VALUES (
                    (SELECT id FROM organization WHERE external_organization_id = %s),
                    (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                      WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                ON CONFLICT (decision_id, action_id)
                DO UPDATE SET status = EXCLUDED.status, request_payload = EXCLUDED.request_payload, updated_at = now()
                """,
                (
                    organization_id,
                    organization_id,
                    store_id,
                    decision_id,
                    str(action.get("action_id", "")),
                    str(action.get("action_type", "unknown")),
                    str(action.get("status", "requested")),
                    str(action.get("idempotency_key", action.get("action_id", ""))),
                    Jsonb(action),
                ),
            )

    def _upsert_action_results(
        self,
        cur: Any,
        organization_id: str,
        store_id: str,
        decision_id: str,
        state: DecisionState,
    ) -> None:
        for (action_id, idempotency_key), result in state.action_results.items():
            request_payload = result.get("_request_payload", {})
            cur.execute(
                """
                INSERT INTO action_result (
                    organization_id, store_id, action_request_id, decision_id,
                    action_id, idempotency_key, status, result_payload
                )
                VALUES (
                    (SELECT id FROM organization WHERE external_organization_id = %s),
                    (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                      WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                    (SELECT id FROM action_request WHERE decision_id = %s AND action_id = %s),
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                ON CONFLICT (decision_id, action_id, idempotency_key)
                DO UPDATE SET status = EXCLUDED.status, result_payload = EXCLUDED.result_payload, received_at = now()
                """,
                (
                    organization_id,
                    organization_id,
                    store_id,
                    decision_id,
                    action_id,
                    decision_id,
                    action_id,
                    idempotency_key,
                    str(request_payload.get("status", result.get("decision_status", "received"))),
                    Jsonb(result),
                ),
            )

    def _upsert_human_reply(
        self,
        cur: Any,
        organization_id: str,
        store_id: str,
        decision_id: str,
        state: DecisionState,
    ) -> None:
        if not state.feedback:
            return
        latest = state.feedback[-1]
        cur.execute(
            """
            INSERT INTO human_reply (
                organization_id, store_id, decision_id, replied_by_ref,
                final_reply_redacted, adopted_suggestion, outcome, feedback_payload
            )
            VALUES (
                (SELECT id FROM organization WHERE external_organization_id = %s),
                (SELECT st.id FROM store st JOIN organization org ON org.id = st.organization_id
                  WHERE org.external_organization_id = %s AND st.external_store_id = %s),
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            ON CONFLICT (decision_id)
            DO UPDATE SET
                final_reply_redacted = EXCLUDED.final_reply_redacted,
                adopted_suggestion = EXCLUDED.adopted_suggestion,
                outcome = EXCLUDED.outcome,
                feedback_payload = EXCLUDED.feedback_payload,
                created_at = now()
            """,
            (
                organization_id,
                organization_id,
                store_id,
                decision_id,
                str(latest.get("replied_by_ref", latest.get("actor_id", "external"))),
                latest.get("human_reply"),
                latest.get("used_candidate"),
                str(latest.get("resolution_status", "submitted")),
                Jsonb(latest),
            ),
        )


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


def _request_key(payload: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(payload.get("tenant_id") or payload.get("organization_id", "")),
        str(payload.get("external_store_id") or payload.get("store_id", "")),
        str(payload.get("request_id", "")),
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


def _search_terms(query: str) -> list[str]:
    terms = [term for term in re.split(r"\s+", query.strip()) if term]
    seen: set[str] = set()
    unique_terms: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique_terms.append(term)
    return unique_terms[:12]
