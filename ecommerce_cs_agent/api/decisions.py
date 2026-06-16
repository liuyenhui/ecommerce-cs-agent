from __future__ import annotations

from typing import Any


def create_reply_decision(request: dict[str, Any]) -> dict[str, Any]:
    request_id = str(request.get("request_id") or "unknown-request")
    decision_id = f"decision-{request_id}"
    message = request.get("message") if isinstance(request.get("message"), dict) else {}
    content = str(message.get("content") or "")
    context = request.get("context") if isinstance(request.get("context"), dict) else {}

    if _is_cross_tenant_probe(content):
        return _handoff(decision_id, request_id, "cross_tenant_data")

    if _is_high_risk_complaint(content):
        return _handoff(decision_id, request_id, "high_risk_request")

    if _is_action_request(content):
        return {
            **_base_response(decision_id, request_id, "action_request", "action_request"),
            "action_request": {
                "action_id": f"action-{request_id}",
                "action_type": "change_shipping_address",
                "payload": {"source": "buyer_message"},
                "requires_human_confirm": True,
            },
        }

    required_context = _required_context_types(content, context)
    if required_context:
        return {
            **_base_response(decision_id, request_id, "waiting_context", "context_request"),
            "context_requests": [
                {
                    "context_request_id": f"ctx-{request_id}-{context_type}",
                    "type": context_type,
                    "endpoint": f"/v1/reply-decisions/{decision_id}/contexts/{context_type}",
                    "reason": f"missing {context_type} context",
                }
                for context_type in required_context
            ],
        }

    return {
        **_base_response(decision_id, request_id, "candidate", "candidate"),
        "candidates": [
            {
                "text": "这个问题需要客服结合当前资料确认后回复。",
                "confidence": 0.3,
            }
        ],
    }


def refill_context(
    *,
    decision_id: str,
    context_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        **_base_response(decision_id, "context-refill", "partial_context", "context_request"),
        "remaining_context_requests": [],
        "trace": {
            "steps": [
                {
                    "name": "refill_context",
                    "status": "completed",
                    "context_type": context_type,
                    "context_request_id": payload.get("context_request_id"),
                }
            ]
        },
    }


def _base_response(
    decision_id: str,
    request_id: str,
    decision_status: str,
    action: str,
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "decision_status": decision_status,
        "action": action,
        "candidates": [],
        "auto_reply": None,
        "context_requests": [],
        "action_request": None,
        "trace": {
            "request_id": request_id,
            "steps": [
                {
                    "name": "classify_request",
                    "status": "completed",
                    "action": action,
                }
            ],
        },
    }


def _handoff(decision_id: str, request_id: str, reason: str) -> dict[str, Any]:
    return {
        **_base_response(decision_id, request_id, "handoff", "handoff"),
        "handoff_reason": reason,
    }


def _required_context_types(content: str, context: dict[str, Any]) -> list[str]:
    lowered = content.lower()
    needs_order = any(keyword in lowered for keyword in ("发货", "物流", "这单", "订单"))
    if not needs_order:
        return []

    required = []
    if not context.get("orders"):
        required.append("orders")
    if not context.get("logistics"):
        required.append("logistics")
    return required


def _is_high_risk_complaint(content: str) -> bool:
    return "投诉" in content or "处罚" in content or "赔付" in content


def _is_cross_tenant_probe(content: str) -> bool:
    return "隔壁店" in content or "其他店" in content or "别的店" in content


def _is_action_request(content: str) -> bool:
    return "地址" in content and any(keyword in content for keyword in ("改", "修改", "换"))
