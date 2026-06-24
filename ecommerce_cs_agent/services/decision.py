from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
import uuid
from typing import Any

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.decision_types import DecisionState
from ecommerce_cs_agent.services.llm import DeterministicReplyProvider, ReplyProvider
from ecommerce_cs_agent.services.repository import (
    DecisionRepository,
    InMemoryDecisionRepository,
    PostgresDecisionRepository,
)


HIGH_RISK_KEYWORDS = ("退款", "赔偿", "投诉", "平台介入", "处罚", "refund", "complaint")
TENANT_SECURITY_KEYWORDS = ("隔壁店", "别的店", "其他店", "别人店", "其它店", "跨店", "其他租户", "别的租户")
SHIPPING_KEYWORDS = ("发货", "物流", "快递", "什么时候到", "ship", "shipping", "delivery")
PRODUCT_KEYWORDS = ("商品", "产品", "材质", "尺寸", "颜色", "规格", "参数", "material", "size")
ACTION_KEYWORDS = ("改备注", "备注", "改地址", "修改地址", "收货地址", "update note", "change address")


class DecisionService:
    def __init__(
        self,
        settings: Settings,
        repository: DecisionRepository | None = None,
        reply_provider: ReplyProvider | None = None,
    ):
        self.settings = settings
        self.repository = repository or _repository_for(settings)
        self.reply_provider = reply_provider or DeterministicReplyProvider()

    def create_reply_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        organization_id, store_id, request_id = _request_key(payload)
        existing = self.repository.get_by_request(organization_id, store_id, request_id)
        if existing:
            return existing.response

        decision_id = self._decision_id((organization_id, store_id, request_id))
        content = str(payload.get("message", {}).get("content", ""))
        response = self._build_response(decision_id, payload, content)
        state = DecisionState(request=payload, response=response)
        self._save_state(organization_id, store_id, request_id, decision_id, state)
        return response

    def refill_context(self, decision_id: str, context_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        state = self.repository.get_by_decision_id(decision_id)
        if not state:
            return {
                "decision_id": decision_id,
                "context_request_id": payload.get("context_request_id"),
                "decision_status": "partial_context",
                "action": "context_request",
                "accepted": True,
                "remaining_context_requests": [],
                "next_action": "wait_context",
                "trace": self._trace(
                    "context_refill",
                    "上下文回填",
                    outputs_ref=[f"context:{context_type}:{payload.get('context_request_id')}"],
                    thread_id=decision_id,
                ),
            }
        organization_id, store_id, request_id = _request_key(state.request)
        if ("organization_id" in payload or "store_id" in payload) and not self._same_tenant_store(state, payload):
            raise PermissionError("context refill does not belong to the decision tenant/store")
        known_request_ids = {item["context_request_id"] for item in state.response.get("context_requests", [])}
        context_request_id = str(payload.get("context_request_id", ""))
        if context_request_id not in known_request_ids:
            raise ValueError("context_request_id does not belong to this decision")
        idempotency_key = str(payload.get("idempotency_key", context_request_id))
        key = (context_request_id, idempotency_key)
        existing = state.context_refills.get(key)
        comparable = {k: v for k, v in payload.items() if k != "source"}
        if existing and existing.get("_request_payload") != comparable:
            raise FileExistsError("idempotency conflict")
        if not existing:
            remaining = [
                item
                for item in state.response.get("context_requests", [])
                if item.get("context_request_id") != context_request_id
            ]
            accepted = {
                "decision_id": decision_id,
                "context_request_id": context_request_id,
                "decision_status": "partial_context" if remaining else "ready_to_decide",
                "accepted": True,
                "remaining_context_requests": [
                    {"context_request_id": item["context_request_id"], "type": item["type"], "status": "pending"}
                    for item in remaining
                ],
                "next_action": "wait_context" if remaining else "decide",
                "trace": self._trace(
                    "context_refill",
                    "上下文回填",
                    outputs_ref=[f"context:{context_type}:{context_request_id}"],
                    thread_id=decision_id,
                ),
            }
            state.context_refills[key] = {**accepted, "_request_payload": comparable}
            if not remaining:
                updated_request = _request_with_refill_context(state.request, context_type, payload)
                final_response = self._build_response(decision_id, updated_request, str(updated_request.get("message", {}).get("content", "")))
                state.request = updated_request
                state.response = final_response
                state.context_refills[key] = {**final_response, "_request_payload": comparable}
            self._save_state(organization_id, store_id, request_id, decision_id, state)
        return _public(state.context_refills[key])

    def submit_action_result(self, decision_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        state = self.repository.get_by_decision_id(decision_id)
        if not state:
            return None
        organization_id, store_id, request_id = _request_key(state.request)
        if payload.get("organization_id") and not self._same_tenant_store(state, payload):
            raise PermissionError("action result does not belong to the decision tenant/store")
        action_id = str(payload.get("action_id", ""))
        known_action_ids = {item["action_id"] for item in state.response.get("action_requests", [])}
        if known_action_ids and action_id not in known_action_ids:
            raise ValueError("action_id does not belong to this decision")
        idempotency_key = str(payload.get("idempotency_key", action_id))
        key = (action_id, idempotency_key)
        existing = state.action_results.get(key)
        comparable = dict(payload)
        if existing and existing.get("_request_payload") != comparable:
            raise FileExistsError("idempotency conflict")
        if not existing:
            status = payload.get("status")
            state.action_results[key] = {
                "decision_id": decision_id,
                "action_id": action_id,
                "accepted": True,
                "decision_status": "answer_ready" if status == "success" else "handoff",
                "next_action": "decide" if status == "success" else "handoff",
                "_request_payload": comparable,
                "trace": self._trace(
                    "action_result",
                    "动作结果回传",
                    outputs_ref=[f"action_result:{action_id}"],
                    thread_id=decision_id,
                ),
            }
            self._save_state(organization_id, store_id, request_id, decision_id, state)
        return _public(state.action_results[key])

    def submit_feedback(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        decision_id = str(payload.get("decision_id", ""))
        state = self.repository.get_by_decision_id(decision_id)
        if not state:
            return None
        organization_id, store_id, request_id = _request_key(state.request)
        human_reply_id = f"human-reply-{uuid.uuid4().hex[:12]}"
        state.feedback.append({"human_reply_id": human_reply_id, **payload})
        self._save_state(organization_id, store_id, request_id, decision_id, state)
        return {
            "human_reply_id": human_reply_id,
            "decision_id": decision_id,
            "accepted": True,
            "knowledge_candidate_id": None,
        }

    def get_trace(self, decision_id: str) -> dict[str, Any] | None:
        state = self.repository.get_by_decision_id(decision_id)
        if not state:
            return None
        return self._trace_from_state(decision_id, state)

    def list_traces(
        self,
        organization_id: str | None = None,
        store_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        states = self.repository.list_recent(organization_id, store_id, limit)
        traces: list[dict[str, Any]] = []
        for state in states:
            decision_id = str(state.response.get("decision_id", ""))
            traces.append(self._trace_from_state(decision_id, state))
        return traces

    def _trace_from_state(self, decision_id: str, state: DecisionState) -> dict[str, Any]:
        request = state.request
        response = state.response
        message = request.get("message", {})
        conversation = request.get("conversation", {})
        return {
            "decision_id": decision_id,
            "message_id": message.get("external_message_id"),
            "external_message_id": message.get("external_message_id"),
            "request_id": request.get("request_id"),
            "tenant_id": request.get("tenant_id") or request.get("organization_id"),
            "platform": request.get("platform"),
            "store_id": request.get("store_id"),
            "external_store_id": request.get("external_store_id") or request.get("store_id"),
            "platform_account_ref": request.get("platform_account_ref"),
            "listing_ref": request.get("listing_ref"),
            "connector_id": request.get("connector_id"),
            "billing_reservation_id": request.get("billing_reservation_id"),
            "conversation_id": conversation.get("external_conversation_id"),
            "action": response.get("action"),
            "confidence": response.get("confidence"),
            "risk_level": response.get("risk_level"),
            "sections": {
                "ingest": {"status": "completed"},
                "normalization": {"status": "completed"},
                "retrieval": {"status": "completed"},
                "generation": {"status": "completed"},
                "risk_and_policy": {"status": "completed"},
                "persistence": {"status": "completed"},
                "feedback": {"status": "completed" if state.feedback else "pending"},
            },
            "trace": response.get("trace"),
        }

    def _build_response(self, decision_id: str, payload: dict[str, Any], content: str) -> dict[str, Any]:
        lowered = content.lower()
        organization_id, store_id, _request_id = _request_key(payload)
        matched_knowledge = self.repository.recall_knowledge(organization_id, store_id, _knowledge_query(content), limit=5)
        risk_flags: list[str] = []
        if any(word in lowered or word in content for word in HIGH_RISK_KEYWORDS):
            risk_flags.append("refund_or_complaint")
        if any(word in lowered or word in content for word in TENANT_SECURITY_KEYWORDS) and (
            "订单" in content or "信息" in content or "数据" in content or "order" in lowered or "data" in lowered
        ):
            risk_flags.append("cross_tenant_data_access")
        missing_context = self._missing_context(payload, lowered, content, has_product_knowledge=bool(matched_knowledge))
        action_requests: list[dict[str, Any]] = []
        evidence = [_knowledge_evidence(item) for item in matched_knowledge]

        if risk_flags:
            action = "handoff"
            status = "handoff"
            confidence = 0.34
            risk_level = "high"
            candidates: list[dict[str, Any]] = []
            handoff_reason = "cross_tenant_data_access" if "cross_tenant_data_access" in risk_flags else "high_risk_request"
        elif any(word in lowered or word in content for word in ACTION_KEYWORDS):
            action = "action_request"
            status = "action_request"
            confidence = 0.66
            risk_level = "medium"
            candidates = []
            handoff_reason = None
            action_requests = [self._action_request(decision_id, payload, content)]
        elif missing_context:
            action = "context_request"
            status = "waiting_context"
            confidence = 0.72
            risk_level = "medium"
            candidates = []
            handoff_reason = None
        else:
            action = "candidate"
            status = "candidate"
            confidence = 0.68
            risk_level = "low"
            candidates = [
                {
                    "suggestion_id": f"suggestion-{decision_id[-8:]}",
                    "reply_text": self.reply_provider.generate_candidate(message=content, knowledge=matched_knowledge),
                    "evidence": evidence,
                    "confidence": 0.68,
                }
            ]
            handoff_reason = None

        context_requests = [
            self._context_request(decision_id, context_type, payload)
            for context_type in missing_context
        ]
        trace = self._trace(
            "classify_intent",
            "classify_intent",
            inputs_ref=[f"message:{payload.get('message', {}).get('external_message_id', '')}"],
            outputs_ref=[f"decision:{decision_id}"],
            rule_hits=risk_flags,
            matched_knowledge=matched_knowledge,
            graph=True,
        )
        trace["tenant_id"] = payload.get("tenant_id") or payload.get("organization_id")
        trace["external_store_id"] = payload.get("external_store_id") or payload.get("store_id")
        trace["platform_account_ref"] = payload.get("platform_account_ref")
        trace["listing_ref"] = payload.get("listing_ref")
        trace["connector_id"] = payload.get("connector_id")
        trace["billing_reservation_id"] = payload.get("billing_reservation_id")
        return {
            "decision_id": decision_id,
            "decision_status": status,
            "action": action,
            "candidates": candidates,
            "auto_reply": None,
            "context_requests": context_requests,
            "action_requests": action_requests,
            "action_request": action_requests[0] if action_requests else None,
            "confidence": confidence,
            "risk_level": risk_level,
            "risk_flags": risk_flags,
            "missing_context": missing_context,
            "handoff_reason": handoff_reason,
            "trace": trace,
        }

    def _missing_context(self, payload: dict[str, Any], lowered: str, content: str, *, has_product_knowledge: bool = False) -> list[str]:
        context = payload.get("context") or {}
        missing: list[str] = []
        asks_shipping = any(word in lowered or word in content for word in SHIPPING_KEYWORDS)
        if asks_shipping:
            if not context.get("orders"):
                missing.append("orders")
            if not context.get("logistics"):
                missing.append("logistics")
        asks_product = any(word in lowered or word in content for word in PRODUCT_KEYWORDS)
        if asks_product and not context.get("products") and not has_product_knowledge:
            missing.append("products")
        return missing

    def _context_request(self, decision_id: str, context_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        context_request_id = f"ctx-{context_type}-{decision_id[-8:]}"
        conversation = payload.get("conversation", {})
        query = {
            "platform": payload.get("platform"),
            "external_store_id": payload.get("external_store_id") or payload.get("store_id"),
            "platform_account_ref": payload.get("platform_account_ref"),
            "listing_ref": payload.get("listing_ref"),
            "external_product_id": payload.get("external_product_id"),
            "external_sku_id": payload.get("external_sku_id"),
            "buyer_ref": conversation.get("buyer_ref"),
            "conversation_id": conversation.get("external_conversation_id"),
        }
        query = {key: value for key, value in query.items() if value is not None}
        return {
            "context_request_id": context_request_id,
            "type": context_type,
            "endpoint": f"/v1/reply-decisions/{decision_id}/contexts/{context_type}",
            "reason": f"回答当前问题需要补充 {context_type} 上下文。",
            "query": query,
            "deadline_ms": 5000,
            "fallback_action": "candidate" if context_type != "logistics" else "handoff",
        }

    def _action_request(self, decision_id: str, payload: dict[str, Any], content: str) -> dict[str, Any]:
        action_type = "change_shipping_address" if "地址" in content else "update-note"
        tenant_id = payload.get("tenant_id") or payload.get("organization_id")
        store_id = payload.get("external_store_id") or payload.get("store_id")
        return {
            "type": "action_request",
            "action_id": f"action-{decision_id[-8:]}",
            "action_type": action_type,
            "idempotency_key": f"{tenant_id}:{store_id}:{payload.get('request_id')}:{action_type}",
            "payload": {"instruction": content},
            "target": {
                "platform": payload.get("platform"),
                "external_store_id": store_id,
                "platform_account_ref": payload.get("platform_account_ref"),
            },
            "confidence": 0.66,
            "risk_level": "medium",
            "requires_human_confirm": True,
            "reason": "用户请求执行外部业务动作，需外部系统确认并回传结果。",
        }

    def _same_tenant_store(self, state: DecisionState, payload: dict[str, Any]) -> bool:
        request = state.request
        payload_tenant = payload.get("tenant_id") or payload.get("organization_id")
        payload_store = payload.get("external_store_id") or payload.get("store_id")
        if payload_tenant and str(payload_tenant) not in {str(request.get("tenant_id")), str(request.get("organization_id"))}:
            return False
        if payload_store and str(payload_store) not in {str(request.get("external_store_id")), str(request.get("store_id"))}:
            return False
        return True

    def _trace(
        self,
        step_id: str,
        name: str,
        inputs_ref: list[str] | None = None,
        outputs_ref: list[str] | None = None,
        rule_hits: list[str] | None = None,
        matched_knowledge: list[dict[str, Any]] | None = None,
        graph: bool = False,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        inferred_thread_id = thread_id or _thread_id_from_refs(outputs_ref)
        if graph:
            steps = []
            knowledge_outputs = [f"knowledge:{item.get('knowledge_entry_id')}" for item in matched_knowledge or []]
            graph_steps = [
                ("normalize", inputs_ref or [], ["normalized_request"]),
                ("retrieve_context", ["normalized_request"], ["context_candidates", *knowledge_outputs]),
                ("classify_intent", ["normalized_request", "context_candidates", *knowledge_outputs], outputs_ref or ["intent"]),
                ("risk_policy", ["intent"], ["risk_policy_result"]),
                ("generate_candidate", ["risk_policy_result"], outputs_ref or ["candidate"]),
                (
                    "persist_trace",
                    outputs_ref or ["decision"],
                    [f"checkpoint:{inferred_thread_id or 'unknown'}:{self.settings.graph_version}"],
                ),
            ]
            for item_step_id, item_inputs, item_outputs in graph_steps:
                steps.append(
                    {
                        "step_id": item_step_id,
                        "name": item_step_id,
                        "status": "completed",
                        "started_at": now,
                        "ended_at": now,
                        "inputs_ref": item_inputs,
                        "outputs_ref": item_outputs,
                        "error": None,
                    }
                )
            return {
                "matched_knowledge_ids": [str(item.get("knowledge_entry_id")) for item in matched_knowledge or []],
                "rule_hits": rule_hits or [],
                "graph_version": self.settings.graph_version,
                "thread_id": inferred_thread_id,
                "model_version": self.reply_provider.model_version,
                "steps": steps,
            }
        return {
            "matched_knowledge_ids": [],
            "rule_hits": rule_hits or [],
            "graph_version": self.settings.graph_version,
            "thread_id": inferred_thread_id,
            "model_version": self.reply_provider.model_version,
            "steps": [
                {
                    "step_id": step_id,
                    "name": name,
                    "status": "completed",
                    "started_at": now,
                    "ended_at": now,
                    "inputs_ref": inputs_ref or [],
                    "outputs_ref": outputs_ref or [],
                    "error": None,
                }
            ],
        }

    def _decision_id(self, key: tuple[str, str, str]) -> str:
        digest = hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()[:24]
        return f"decision-{digest}"

    def _save_state(
        self,
        organization_id: str,
        store_id: str,
        request_id: str,
        decision_id: str,
        state: DecisionState,
    ) -> None:
        self.repository.save_state(
            organization_id=organization_id,
            store_id=store_id,
            request_id=request_id,
            decision_id=decision_id,
            state=state,
        )


def _public(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if not key.startswith("_")}


def _request_key(payload: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(payload.get("tenant_id") or payload.get("organization_id", "")),
        str(payload.get("external_store_id") or payload.get("store_id", "")),
        str(payload.get("request_id", "")),
    )


def _request_with_refill_context(request: dict[str, Any], context_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(request)
    context = dict(updated.get("context") or {})
    existing = context.get(context_type)
    if isinstance(existing, list):
        context[context_type] = [*existing, *list(payload.get("items") or [])]
    else:
        context[context_type] = list(payload.get("items") or [])
    updated["context"] = context
    return updated


def _knowledge_evidence(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "knowledge_entry_id": item.get("knowledge_entry_id"),
        "product_id": item.get("product_id"),
        "scope": item.get("scope"),
        "source_type": "approved_knowledge",
        "chunk_index": item.get("chunk_index", 0),
    }


def _knowledge_query(content: str) -> str:
    normalized = content.lower()
    terms: list[str] = []
    for keyword in (*PRODUCT_KEYWORDS, *SHIPPING_KEYWORDS, *ACTION_KEYWORDS):
        if keyword in normalized or keyword in content:
            terms.append(keyword)
    terms.extend(re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,31}", normalized))
    seen: set[str] = set()
    unique_terms = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique_terms.append(term)
    return " ".join(unique_terms)


def _thread_id_from_refs(outputs_ref: list[str] | None) -> str | None:
    for item in outputs_ref or []:
        if item.startswith("decision:"):
            return item.split(":", 1)[1]
    return None


def _repository_for(settings: Settings) -> DecisionRepository:
    if settings.database_url and settings.environment.lower() not in {"test"}:
        return PostgresDecisionRepository(settings.database_url)
    return InMemoryDecisionRepository()
