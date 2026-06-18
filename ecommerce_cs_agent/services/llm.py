from __future__ import annotations

from typing import Any, Protocol


class ReplyProvider(Protocol):
    model_version: str

    def generate_candidate(self, *, message: str, knowledge: list[dict[str, Any]]) -> str:
        raise NotImplementedError


class DeterministicReplyProvider:
    model_version = "deterministic-reply-v1"

    def generate_candidate(self, *, message: str, knowledge: list[dict[str, Any]]) -> str:
        if knowledge:
            content = str(knowledge[0].get("content", "")).strip()
            if content:
                return f"{content} 请以商品详情页和客服最终确认为准。"
        return "我先帮您核对信息，请以订单和商品详情页的最新状态为准。"
