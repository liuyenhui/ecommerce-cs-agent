from __future__ import annotations

import json
import re
from typing import Any, Protocol
from urllib import request as urllib_request
from urllib.error import URLError

from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.outbound_http import validate_public_https_url


class ProductDocumentAnalyzer(Protocol):
    model_version: str

    def analyze(self, *, text: str, file_name: str, mime_type: str) -> dict[str, Any]:
        raise NotImplementedError


class DeterministicProductDocumentAnalyzer:
    model_version = "deterministic-product-document-v1"

    def analyze(self, *, text: str, file_name: str, mime_type: str) -> dict[str, Any]:
        fields = _extract_labeled_fields(text)
        title = fields.get("标题") or fields.get("商品名称") or _first_content_line(text) or file_name
        external_product_id = (
            fields.get("外部商品ID")
            or fields.get("外部商品 ID")
            or fields.get("商品ID")
            or fields.get("商品 ID")
            or fields.get("SKU")
            or _slug_from_file_name(file_name)
        )
        attributes = {
            key: value
            for key, value in fields.items()
            if key not in {"标题", "商品名称", "外部商品ID", "外部商品 ID", "商品ID", "商品 ID", "SKU"}
        }
        return {
            "analysis_status": "fallback",
            "analysis_model": self.model_version,
            "draft_product": {
                "external_product_id": external_product_id,
                "title": title,
                "status": "active",
                "attributes": attributes,
            },
            "markdown_text": text.strip(),
            "source_map": {"file_name": file_name, "mime_type": mime_type, "mode": "deterministic"},
        }


class OpenAICompatibleProductDocumentAnalyzer:
    model_version = "openai-compatible-product-document-v1"

    def __init__(self, *, base_url: str, api_key: str, model: str, fallback: ProductDocumentAnalyzer | None = None) -> None:
        self.base_url = validate_public_https_url(base_url, field="LLM base URL")
        self.api_key = api_key
        self.model = model
        self.fallback = fallback or DeterministicProductDocumentAnalyzer()

    def analyze(self, *, text: str, file_name: str, mime_type: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract ecommerce product fields from the uploaded document. "
                        "Return strict JSON with keys draft_product, markdown_text, source_map. "
                        "draft_product must include external_product_id, title, status, attributes."
                    ),
                },
                {"role": "user", "content": f"file_name={file_name}\nmime_type={mime_type}\n\n{text[:12000]}"},
            ],
        }
        request = urllib_request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
            content = str(data["choices"][0]["message"]["content"])
            parsed = json.loads(_strip_json_fence(content))
            draft_product = parsed.get("draft_product") if isinstance(parsed, dict) else None
            if not isinstance(draft_product, dict):
                raise ValueError("missing draft_product")
            return {
                "analysis_status": "completed",
                "analysis_model": self.model,
                "draft_product": _normalize_draft_product(draft_product, file_name),
                "markdown_text": str(parsed.get("markdown_text") or text.strip()),
                "source_map": parsed.get("source_map") if isinstance(parsed.get("source_map"), dict) else {"file_name": file_name, "mime_type": mime_type},
            }
        except (KeyError, ValueError, json.JSONDecodeError, URLError) as exc:
            fallback = self.fallback.analyze(text=text, file_name=file_name, mime_type=mime_type)
            fallback["analysis_error"] = type(exc).__name__
            return fallback


def product_document_analyzer_for(settings: Settings) -> ProductDocumentAnalyzer:
    if (
        settings.environment.lower() not in {"test"}
        and settings.llm_base_url
        and settings.llm_api_key
        and settings.llm_model
    ):
        return OpenAICompatibleProductDocumentAnalyzer(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )
    return DeterministicProductDocumentAnalyzer()


def _extract_labeled_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        parsed = _split_labeled_line(line)
        if parsed is not None:
            key, value = parsed
            fields[key] = value
    return fields


def _first_content_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip().strip("#").strip()
        if cleaned and _split_labeled_line(cleaned) is None:
            return cleaned[:80]
    return ""


def _split_labeled_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    ascii_separator = stripped.find(":")
    full_width_separator = stripped.find("：")
    separator_positions = [position for position in (ascii_separator, full_width_separator) if position >= 0]
    if not separator_positions:
        return None

    separator_index = min(separator_positions)
    key = stripped[:separator_index].strip()
    value = stripped[separator_index + 1 :].strip()
    if not key or not value or len(key) > 24:
        return None
    return key, value


def _slug_from_file_name(file_name: str) -> str:
    stem = file_name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-").lower()
    return normalized or "uploaded-product"


def _strip_json_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped


def _normalize_draft_product(product: dict[str, Any], file_name: str) -> dict[str, Any]:
    return {
        "external_product_id": str(product.get("external_product_id") or _slug_from_file_name(file_name)),
        "title": str(product.get("title") or file_name),
        "status": str(product.get("status") or "active"),
        "attributes": product.get("attributes") if isinstance(product.get("attributes"), dict) else {},
    }
