from __future__ import annotations

from dataclasses import dataclass
import json
import re


@dataclass(frozen=True, slots=True)
class GroundedFactManifest:
    required_terms: tuple[str, ...]
    allowed_numbers: tuple[str, ...]
    allowed_entities: tuple[str, ...]
    prohibited_claims: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GroundedRewriteRequest:
    question: str
    history: tuple[str, ...]
    deterministic_draft: str
    facts: GroundedFactManifest


@dataclass(frozen=True, slots=True)
class GroundedRewriteResult:
    reply_text: str
    validation_status: str


class UnsafeModelReply(ValueError):
    pass


_FORBIDDEN_INPUT_KEYS = (
    "raw_payload", "source_ref", "external_order_id", "external_product_id",
    "secret", "authorization", "api_key",
)
_PROMPT_LEAKAGE = ("系统提示", "system prompt", "忽略前面", "developer message")
_PET_TERMS = {"比熊", "小猫", "猫咪", "狗狗", "幼猫", "幼犬", "金毛", "泰迪"}
_STATUS_TERMS = {"已收货", "已发货", "待发货", "售罄", "已下架", "退款中"}
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_SECRET_RE = re.compile(r"(?:sk-|ghp_|Bearer\s+|BEGIN .*PRIVATE KEY)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])")


def build_rewrite_messages(request: GroundedRewriteRequest) -> list[dict[str, str]]:
    safe_payload = {
        "question": _safe_prompt_text(request.question),
        "minimal_history": [_safe_prompt_text(item) for item in request.history[-2:]],
        "deterministic_draft": _safe_prompt_text(request.deterministic_draft),
        "required_facts": list(request.facts.required_terms),
        "allowed_numbers": list(request.facts.allowed_numbers),
        "allowed_entities": list(request.facts.allowed_entities),
        "prohibited_claims": list(request.facts.prohibited_claims),
    }
    return [
        {
            "role": "system",
            "content": (
                "你只润色已经由确定性规则生成的客服草稿。不得新增、删除或改变事实、数字、"
                "实体、动作和风险结论；不得输出 JSON、解释、承诺或隐私信息。"
                "required_facts 中每个字符串必须逐字保留，不得使用同义词替换。"
                "只返回 JSON 对象：{\"reply_text\":\"客户可读中文回复\"}。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(safe_payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def validate_model_reply(
    *, deterministic: str, model_reply: str, facts: GroundedFactManifest
) -> str:
    reply = str(model_reply or "").strip()
    if not reply or len(reply) > 300 or reply.startswith(("{", "[")):
        raise UnsafeModelReply("invalid_shape")
    if any(key.lower() in reply.lower() for key in _FORBIDDEN_INPUT_KEYS):
        raise UnsafeModelReply("schema_leakage")
    if any(term.lower() in reply.lower() for term in _PROMPT_LEAKAGE):
        raise UnsafeModelReply("prompt_leakage")
    if _PHONE_RE.search(reply) or _SECRET_RE.search(reply):
        raise UnsafeModelReply("privacy_leakage")
    if any(term in reply for term in facts.prohibited_claims):
        raise UnsafeModelReply("prohibited_claim")
    if any(term not in reply for term in facts.required_terms):
        raise UnsafeModelReply("missing_fact")
    allowed_numbers = set(facts.allowed_numbers)
    if any(number not in allowed_numbers for number in _NUMBER_RE.findall(reply)):
        raise UnsafeModelReply("added_number")
    allowed_text = " ".join(facts.allowed_entities + facts.required_terms) + " " + deterministic
    if any(term in reply and term not in allowed_text for term in _PET_TERMS | _STATUS_TERMS):
        raise UnsafeModelReply("added_entity_or_status")
    if re.search(r"(?<!\d)\d{8,}(?!\d)", reply):
        raise UnsafeModelReply("unmasked_identifier")
    return reply


def _safe_prompt_text(value: str) -> str:
    text = str(value or "").strip()
    lowered = text.lower()
    if len(text) > 1000 or any(key in lowered for key in _FORBIDDEN_INPUT_KEYS):
        raise ValueError("unsafe rewrite input")
    if _PHONE_RE.search(text) or _SECRET_RE.search(text):
        raise ValueError("unsafe rewrite input")
    return text
