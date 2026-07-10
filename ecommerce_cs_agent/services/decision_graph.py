from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Callable, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.constants import END, START
from langgraph.graph.state import StateGraph

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.llm import ReplyProvider
from ecommerce_cs_agent.services.repository import DecisionRepository


HIGH_RISK_KEYWORDS = ("退款", "赔偿", "投诉", "平台介入", "处罚", "refund", "complaint")
TENANT_SECURITY_KEYWORDS = ("隔壁店", "别的店", "其他店", "别人店", "其它店", "跨店", "其他租户", "别的租户")
SHIPPING_KEYWORDS = ("发货", "物流", "快递", "什么时候到", "ship", "shipping", "delivery")
PRODUCT_KEYWORDS = ("商品", "产品", "材质", "尺寸", "颜色", "规格", "参数", "material", "size")
ACTION_KEYWORDS = ("改备注", "备注", "改地址", "修改地址", "收货地址", "update note", "change address")
RELEVANCE_ANCHORS = (
    "材质",
    "尺寸",
    "颜色",
    "规格",
    "参数",
    "安全",
    "认证",
    "发货",
    "物流",
    "快递",
    "订单",
    "地址",
    "备注",
    "保修",
    "安装",
    "material",
    "size",
    "color",
    "specification",
    "safe",
    "certif",
    "shipping",
    "delivery",
    "order",
    "address",
    "warranty",
)
BROAD_RELEVANCE_TERMS = {"安全", "认证", "safe", "certif"}
RELEVANCE_PHRASES = (
    "儿童安全认证",
    "安全认证",
    "运输安全",
    "退货政策",
    "收货地址",
    "冷水洗涤",
)
RELEVANCE_THRESHOLD = 0.7
RELEVANCE_STOP_TERMS = {
    "这个",
    "这款",
    "商品",
    "产品",
    "什么",
    "怎么",
    "如何",
    "请问",
    "是否",
    "可以",
    "有没有",
    "关于",
    "客服",
    "the",
    "this",
    "that",
    "what",
    "which",
    "how",
    "can",
    "could",
    "please",
    "product",
    "item",
    "a",
    "an",
    "is",
    "are",
    "do",
    "does",
    "of",
    "it",
    "for",
    "to",
    "with",
    "by",
    "from",
}
RULE_KEYWORDS = ("规则", "退换货", "退货政策", "平台政策", "rule", "policy")

GRAPH_NODE_IDS = [
    "normalize_request",
    "retrieve_context",
    "classify_intent",
    "context_gate",
    "action_gate",
    "generate_candidate",
    "policy_gate",
    "persist_trace",
]

NODE_LABELS = {
    "normalize_request": "归一化请求",
    "retrieve_context": "检索上下文",
    "classify_intent": "识别意图",
    "context_gate": "上下文闸门",
    "action_gate": "动作闸门",
    "generate_candidate": "生成候选",
    "policy_gate": "规则闸门",
    "persist_trace": "记录检查点",
}

GRAPH_EDGE_DEFINITIONS = [
    ("normalize_request", "retrieve_context", "归一化完成", "normalized"),
    ("retrieve_context", "classify_intent", "上下文就绪", "context_loaded"),
    ("classify_intent", "context_gate", "意图已识别", "intent_classified"),
    ("context_gate", "policy_gate", "转人工", "handoff"),
    ("context_gate", "policy_gate", "等待上下文", "context_request"),
    ("context_gate", "action_gate", "上下文完整", "context_complete"),
    ("action_gate", "policy_gate", "外部动作", "action_request"),
    ("action_gate", "generate_candidate", "生成回复", "candidate"),
    ("generate_candidate", "policy_gate", "候选完成", "candidate_ready"),
    ("policy_gate", "persist_trace", "记录检查点", "persist"),
]


class ReplyDecisionGraphState(TypedDict, total=False):
    decision_id: str
    payload: dict[str, Any]
    content: str
    lowered: str
    organization_id: str
    store_id: str
    request_id: str
    matched_knowledge: list[dict[str, Any]]
    knowledge_relevance: list[dict[str, Any]]
    knowledge_query: str
    risk_flags: list[str]
    missing_context: list[str]
    action: str
    decision_status: str
    confidence: float
    risk_level: str
    candidates: list[dict[str, Any]]
    auto_reply: dict[str, Any] | None
    context_requests: list[dict[str, Any]]
    action_requests: list[dict[str, Any]]
    handoff_reason: str | None
    auto_reply_gate: dict[str, Any]
    route: str
    resumed_from_checkpoint: bool
    steps: list[dict[str, Any]]
    taken_conditions: list[str]
    response: dict[str, Any]


class ReplyDecisionGraph:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: DecisionRepository,
        reply_provider: ReplyProvider,
        request_key: Callable[[dict[str, Any]], tuple[str, str, str]],
        context_request_factory: Callable[[str, str, dict[str, Any]], dict[str, Any]],
        action_request_factory: Callable[[str, dict[str, Any], str], dict[str, Any]],
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.reply_provider = reply_provider
        self.request_key = request_key
        self.context_request_factory = context_request_factory
        self.action_request_factory = action_request_factory

    def invoke(
        self,
        decision_id: str,
        payload: dict[str, Any],
        content: str,
        *,
        resumed_from_checkpoint: bool = False,
    ) -> dict[str, Any]:
        organization_id, store_id, request_id = self.request_key(payload)
        state: ReplyDecisionGraphState = {
            "decision_id": decision_id,
            "payload": payload,
            "content": content,
            "lowered": content.lower(),
            "organization_id": organization_id,
            "store_id": store_id,
            "request_id": request_id,
            "resumed_from_checkpoint": resumed_from_checkpoint,
            "steps": [],
            "taken_conditions": [],
        }
        config = {"configurable": {"thread_id": decision_id}}
        checkpointer = InMemorySaver()
        compiled_stategraph = self._compile_stategraph(checkpointer)
        state = compiled_stategraph.invoke(state, config=config)
        checkpoint_id = self._checkpoint_id(compiled_stategraph, config)
        if checkpoint_id:
            state["response"]["trace"]["langgraph_checkpoint_id"] = checkpoint_id
        return state["response"]

    def _compile_stategraph(self, checkpointer: InMemorySaver) -> Any:
        graph = StateGraph(ReplyDecisionGraphState)
        graph.add_node("normalize_request", self._normalize_request)
        graph.add_node("retrieve_context", self._retrieve_context)
        graph.add_node("classify_intent", self._classify_intent)
        graph.add_node("context_gate", self._context_gate)
        graph.add_node("action_gate", self._action_gate)
        graph.add_node("generate_candidate", self._generate_candidate)
        graph.add_node("policy_gate", self._policy_gate)
        graph.add_node("persist_trace", self._persist_trace)
        graph.add_edge(START, "normalize_request")
        graph.add_edge("normalize_request", "retrieve_context")
        graph.add_edge("retrieve_context", "classify_intent")
        graph.add_edge("classify_intent", "context_gate")
        graph.add_conditional_edges(
            "context_gate",
            _route_after_context_gate,
            {
                "context_complete": "action_gate",
                "context_request": "policy_gate",
                "handoff": "policy_gate",
            },
        )
        graph.add_conditional_edges(
            "action_gate",
            _route_after_action_gate,
            {
                "candidate": "generate_candidate",
                "action_request": "policy_gate",
            },
        )
        graph.add_edge("generate_candidate", "policy_gate")
        graph.add_edge("policy_gate", "persist_trace")
        graph.add_edge("persist_trace", END)
        return graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _checkpoint_id(compiled_stategraph: Any, config: dict[str, Any]) -> str | None:
        try:
            snapshot = compiled_stategraph.get_state(config=config)
        except Exception:
            return None
        configurable = getattr(snapshot, "config", {}).get("configurable", {})
        checkpoint_id = configurable.get("checkpoint_id")
        return str(checkpoint_id) if checkpoint_id else None

    def _normalize_request(self, state: ReplyDecisionGraphState) -> ReplyDecisionGraphState:
        payload = state["payload"]
        message_id = payload.get("message", {}).get("external_message_id", "")
        return _with_step(
            state,
            "normalize_request",
            inputs_ref=[f"message:{message_id}"],
            outputs_ref=["normalized_request"],
        )

    def _retrieve_context(self, state: ReplyDecisionGraphState) -> ReplyDecisionGraphState:
        query = _knowledge_query(state["content"])
        recalled = self.repository.recall_knowledge(
            state["organization_id"],
            state["store_id"],
            query,
            limit=5,
        )
        relevance = [_knowledge_relevance(state["content"], item) for item in recalled]
        matched = [item for item, signal in zip(recalled, relevance, strict=True) if signal["relevant"]]
        outputs = ["context_candidates", *[f"knowledge:{item.get('knowledge_entry_id')}" for item in matched]]
        return _with_step(
            {
                **state,
                "knowledge_query": query,
                "matched_knowledge": matched,
                "knowledge_relevance": relevance,
            },
            "retrieve_context",
            inputs_ref=["normalized_request"],
            outputs_ref=outputs,
        )

    def _classify_intent(self, state: ReplyDecisionGraphState) -> ReplyDecisionGraphState:
        content = state["content"]
        lowered = state["lowered"]
        risk_flags: list[str] = []
        if any(word in lowered or word in content for word in HIGH_RISK_KEYWORDS):
            risk_flags.append("refund_or_complaint")
        if any(word in lowered or word in content for word in TENANT_SECURITY_KEYWORDS) and (
            "订单" in content or "信息" in content or "数据" in content or "order" in lowered or "data" in lowered
        ):
            risk_flags.append("cross_tenant_data_access")
        missing_context = _missing_context(
            state["payload"],
            lowered,
            content,
            has_product_knowledge=bool(state.get("matched_knowledge")),
        )
        outputs = ["intent", *[f"risk:{flag}" for flag in risk_flags], *[f"missing_context:{item}" for item in missing_context]]
        return _with_step(
            {**state, "risk_flags": risk_flags, "missing_context": missing_context},
            "classify_intent",
            inputs_ref=["normalized_request", "context_candidates"],
            outputs_ref=outputs,
        )

    def _context_gate(self, state: ReplyDecisionGraphState) -> ReplyDecisionGraphState:
        risk_flags = state.get("risk_flags", [])
        missing_context = state.get("missing_context", [])
        if risk_flags:
            route = "handoff"
            outputs = [f"handoff:{'cross_tenant_data_access' if 'cross_tenant_data_access' in risk_flags else 'high_risk_request'}"]
        elif missing_context:
            route = "context_request"
            outputs = [f"context_request:{item}" for item in missing_context]
        else:
            route = "context_complete"
            outputs = ["context_complete"]
        return _with_step(
            _take(state, route),
            "context_gate",
            inputs_ref=["intent"],
            outputs_ref=outputs,
        )

    def _action_gate(self, state: ReplyDecisionGraphState) -> ReplyDecisionGraphState:
        content = state["content"]
        lowered = state["lowered"]
        route = "action_request" if any(word in lowered or word in content for word in ACTION_KEYWORDS) else "candidate"
        outputs = ["action_request"] if route == "action_request" else ["candidate_requested"]
        return _with_step(_take(state, route), "action_gate", inputs_ref=["context_complete"], outputs_ref=outputs)

    def _generate_candidate(self, state: ReplyDecisionGraphState) -> ReplyDecisionGraphState:
        if state.get("route") != "candidate":
            return _with_step(state, "generate_candidate", inputs_ref=["action_gate"], outputs_ref=[state.get("route", "skipped")])
        evidence = [_knowledge_evidence(item) for item in state.get("matched_knowledge", [])]
        candidate = {
            "suggestion_id": f"suggestion-{state['decision_id'][-8:]}",
            "reply_text": self.reply_provider.generate_candidate(
                message=state["content"],
                knowledge=state.get("matched_knowledge", []),
            ),
            "evidence": evidence,
            "confidence": _evidence_confidence(state.get("knowledge_relevance", [])) if evidence else 0.68,
        }
        return _with_step({**state, "candidates": [candidate]}, "generate_candidate", inputs_ref=["candidate_requested"], outputs_ref=[f"candidate:{candidate['suggestion_id']}"])

    def _policy_gate(self, state: ReplyDecisionGraphState) -> ReplyDecisionGraphState:
        route = state.get("route")
        risk_flags = state.get("risk_flags", [])
        missing_context = state.get("missing_context", [])
        action_requests: list[dict[str, Any]] = []
        candidates = state.get("candidates", [])
        auto_reply: dict[str, Any] | None = None
        auto_reply_gate: dict[str, Any] = {"eligible": False, "reasons": ["non_candidate_route"]}
        if route == "handoff":
            action = "handoff"
            status = "handoff"
            confidence = 0.34
            risk_level = "high"
            handoff_reason = "cross_tenant_data_access" if "cross_tenant_data_access" in risk_flags else "high_risk_request"
        elif route == "context_request":
            action = "context_request"
            status = "waiting_context"
            confidence = 0.72
            risk_level = "medium"
            handoff_reason = None
        elif route == "action_request":
            action = "action_request"
            status = "action_request"
            confidence = 0.66
            risk_level = "medium"
            handoff_reason = None
            action_requests = [self.action_request_factory(state["decision_id"], state["payload"], state["content"])]
        else:
            confidence = _candidate_confidence(candidates)
            payload = state["payload"]
            gate_reasons: list[str] = []
            if confidence < 0.85:
                gate_reasons.append("insufficient_relevant_evidence")
            if payload.get("mode") != "auto_when_safe":
                gate_reasons.append("assist_first_mode")
            if payload.get("source") == "simulation":
                gate_reasons.append("simulation_only")
            auto_reply_gate = {"eligible": not gate_reasons, "reasons": gate_reasons}
            if auto_reply_gate["eligible"]:
                action = "auto_reply"
                status = "answer_ready"
                auto_reply = {
                    "reply_text": candidates[0]["reply_text"] if candidates else "",
                    "approved_by_policy_gate": True,
                }
            else:
                action = "candidate"
                status = "candidate"
            risk_level = "low"
            handoff_reason = None
        context_requests = [
            self.context_request_factory(state["decision_id"], context_type, state["payload"])
            for context_type in missing_context
        ]
        updates: ReplyDecisionGraphState = {
            **state,
            "action": action,
            "decision_status": status,
            "confidence": confidence,
            "risk_level": risk_level,
            "handoff_reason": handoff_reason,
            "auto_reply_gate": auto_reply_gate,
            "context_requests": context_requests,
            "action_requests": action_requests,
            "candidates": candidates if action in {"candidate", "auto_reply"} else [],
            "auto_reply": auto_reply,
        }
        return _with_step(updates, "policy_gate", inputs_ref=["intent", route or "route"], outputs_ref=[f"decision:{state['decision_id']}"])

    def _persist_trace(self, state: ReplyDecisionGraphState) -> ReplyDecisionGraphState:
        traced = _with_step(
            _take(state, "persist"),
            "persist_trace",
            inputs_ref=[f"decision:{state['decision_id']}"],
            outputs_ref=[f"checkpoint:{state['decision_id']}:{self.settings.graph_version}"],
        )
        trace = _trace_payload(
            settings=self.settings,
            reply_provider=self.reply_provider,
            state=traced,
        )
        payload = state["payload"]
        trace["tenant_id"] = payload.get("tenant_id") or payload.get("organization_id")
        trace["external_store_id"] = payload.get("external_store_id") or payload.get("store_id")
        trace["platform_account_ref"] = payload.get("platform_account_ref")
        trace["listing_ref"] = payload.get("listing_ref")
        trace["connector_id"] = payload.get("connector_id")
        trace["billing_reservation_id"] = payload.get("billing_reservation_id")
        response = {
            "decision_id": state["decision_id"],
            "decision_status": state["decision_status"],
            "action": state["action"],
            "candidates": state.get("candidates", []),
            "auto_reply": state.get("auto_reply"),
            "context_requests": state.get("context_requests", []),
            "action_requests": state.get("action_requests", []),
            "action_request": state.get("action_requests", [None])[0] if state.get("action_requests") else None,
            "confidence": state["confidence"],
            "risk_level": state["risk_level"],
            "risk_flags": state.get("risk_flags", []),
            "missing_context": state.get("missing_context", []),
            "handoff_reason": state.get("handoff_reason"),
            "trace": trace,
        }
        return {**traced, "response": response}


def _with_step(
    state: ReplyDecisionGraphState,
    node_id: str,
    *,
    inputs_ref: list[str],
    outputs_ref: list[str],
) -> ReplyDecisionGraphState:
    now = _now()
    step = {
        "step_id": node_id,
        "name": node_id,
        "status": "completed",
        "started_at": now,
        "ended_at": now,
        "inputs_ref": inputs_ref,
        "outputs_ref": outputs_ref,
        "error": None,
    }
    return {**state, "steps": [*state.get("steps", []), step]}


def _take(state: ReplyDecisionGraphState, condition: str) -> ReplyDecisionGraphState:
    return {**state, "route": condition, "taken_conditions": [*state.get("taken_conditions", []), condition]}


def _trace_payload(*, settings: Settings, reply_provider: ReplyProvider, state: ReplyDecisionGraphState) -> dict[str, Any]:
    matched = state.get("matched_knowledge", [])
    return {
        "matched_knowledge_ids": [str(item.get("knowledge_entry_id")) for item in matched],
        "knowledge_relevance": state.get("knowledge_relevance", []),
        "auto_reply_gate": state.get("auto_reply_gate", {"eligible": False, "reasons": ["not_assessed"]}),
        "rule_hits": state.get("risk_flags", []),
        "graph_version": settings.graph_version,
        "thread_id": state["decision_id"],
        "resumed_from_checkpoint": bool(state.get("resumed_from_checkpoint")),
        "model_version": reply_provider.model_version,
        "steps": state.get("steps", []),
        "graph": _trace_graph(state),
    }


def _trace_graph(state: ReplyDecisionGraphState) -> dict[str, Any]:
    steps_by_id = {step["step_id"]: step for step in state.get("steps", [])}
    nodes = []
    for node_id in GRAPH_NODE_IDS:
        step = steps_by_id.get(node_id, {})
        nodes.append(
            {
                "id": node_id,
                "label": NODE_LABELS[node_id],
                "kind": "langgraph_node",
                "status": step.get("status", "skipped"),
                "started_at": step.get("started_at"),
                "ended_at": step.get("ended_at"),
                "inputs_ref": step.get("inputs_ref", []),
                "outputs_ref": step.get("outputs_ref", []),
                "error": step.get("error"),
            }
        )
    taken = set(state.get("taken_conditions", []))
    edges = [
        {
            "source": source,
            "target": target,
            "label": label,
            "condition": condition,
            "taken": condition in taken or condition in {"normalized", "context_loaded", "intent_classified"},
        }
        for source, target, label, condition in GRAPH_EDGE_DEFINITIONS
    ]
    return {"nodes": nodes, "edges": edges}


def _route_after_context_gate(state: ReplyDecisionGraphState) -> str:
    route = state.get("route")
    if route in {"context_request", "handoff"}:
        return route
    return "context_complete"


def _route_after_action_gate(state: ReplyDecisionGraphState) -> str:
    return "action_request" if state.get("route") == "action_request" else "candidate"


def _candidate_confidence(candidates: list[dict[str, Any]]) -> float:
    if not candidates:
        return 0.0
    return max(float(candidate.get("confidence", 0.0)) for candidate in candidates)


def _evidence_confidence(signals: list[dict[str, Any]]) -> float:
    relevant_scores = [float(signal.get("score", 0.0)) for signal in signals if signal.get("relevant")]
    if not relevant_scores:
        return 0.68
    return round(0.68 + min(max(relevant_scores), 1.0) * 0.25, 4)


def _missing_context(payload: dict[str, Any], lowered: str, content: str, *, has_product_knowledge: bool = False) -> list[str]:
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
    asks_rules = any(word in lowered or word in content for word in RULE_KEYWORDS)
    if asks_rules and not context.get("rules"):
        missing.append("rules")
    return missing


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
    for anchor in RELEVANCE_ANCHORS:
        if anchor in normalized or anchor in content:
            terms.append(anchor)
    terms.extend(re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]{1,31}", normalized))
    seen: set[str] = set()
    unique_terms = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            unique_terms.append(term)
    return " ".join(unique_terms)


def _knowledge_relevance(query: str, item: dict[str, Any]) -> dict[str, Any]:
    knowledge = str(item.get("content", ""))
    query_terms = _relevance_terms(query)
    knowledge_terms = _relevance_terms(knowledge)
    shared_terms = sorted(query_terms & knowledge_terms)
    query_core_terms = _core_relevance_terms(query)
    knowledge_core_terms = _core_relevance_terms(knowledge)
    matched_core_terms = sorted(query_core_terms & knowledge_core_terms)
    matched_phrases = [phrase for phrase in RELEVANCE_PHRASES if phrase in query.lower() and phrase in knowledge.lower()]
    distinctive_core_terms = [term for term in matched_core_terms if term not in BROAD_RELEVANCE_TERMS]
    if query_core_terms:
        score = len(matched_core_terms) / len(query_core_terms)
    else:
        score = len(shared_terms) / max(len(query_terms), 1)
    sufficient_signal = bool(matched_phrases) or len(matched_core_terms) >= 2 or bool(distinctive_core_terms)
    if not query_core_terms:
        sufficient_signal = len(shared_terms) >= 2
    relevant = sufficient_signal and score >= RELEVANCE_THRESHOLD
    return {
        "knowledge_entry_id": str(item.get("knowledge_entry_id", "")),
        "relevant": relevant,
        "matched_terms": shared_terms,
        "matched_core_terms": matched_core_terms,
        "matched_phrases": matched_phrases,
        "query_core_terms": sorted(query_core_terms),
        "score": round(score, 4),
        "threshold": RELEVANCE_THRESHOLD,
        "method": "deterministic_intent_overlap_v2",
    }


def _core_relevance_terms(text: str) -> set[str]:
    normalized = text.lower()
    lexical_terms = _relevance_terms(normalized)
    return {
        anchor
        for anchor in RELEVANCE_ANCHORS
        if anchor in lexical_terms or (not anchor.isascii() and anchor in normalized)
    }


def _relevance_terms(text: str) -> set[str]:
    normalized = text.lower()
    terms = {_canonical_english_term(term) for term in re.findall(r"[a-z0-9]+", normalized) if len(term) >= 2}
    for sequence in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", normalized):
        terms.update(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return {term for term in terms if term and term not in RELEVANCE_STOP_TERMS}


def _canonical_english_term(term: str) -> str:
    if term.startswith("certif"):
        return "certif"
    if term in {"safe", "safety"}:
        return "safe"
    if term.endswith("ies") and len(term) > 4:
        return f"{term[:-3]}y"
    if term.endswith("s") and len(term) > 3:
        return term[:-1]
    return term


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
