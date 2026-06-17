from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    status: int | None
    message: str
    summary: dict[str, Any]


class LiveAgentClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/") + "/"
        self.token = token
        self.timeout = timeout

    def get_json(self, path: str) -> tuple[int, Any]:
        request = Request(self._url(path), method="GET", headers=self._headers())
        return self._send(request)

    def post_json(self, path: str, payload: dict[str, Any]) -> tuple[int, Any]:
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode()
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        request = Request(self._url(path), data=body, method="POST", headers=headers)
        return self._send(request)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "ecommerce-cs-agent-evals/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def _send(self, request: Request) -> tuple[int, Any]:
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.status, _parse_body(response.read())
        except HTTPError as exc:
            return exc.code, _parse_body(exc.read())
        except URLError as exc:
            raise RuntimeError(f"network failure: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("network failure: request timed out") from exc


class MockAgentClient:
    def get_json(self, path: str) -> tuple[int, Any]:
        if path == "/health":
            return 200, {"status": "ok", "service": "mock-agent"}
        return 404, {"error": "not_found"}

    def post_json(self, path: str, payload: dict[str, Any]) -> tuple[int, Any]:
        if path != "/v1/reply-decisions":
            return 404, {"error": "not_found"}
        decision_id = f"mock-{payload.get('request_id', 'decision')}"
        return 200, {
            "decision_id": decision_id,
            "action": "candidate",
            "decision_status": "candidate",
        }


class QuickLiveSuite:
    def __init__(self, client: LiveAgentClient):
        self.client = client

    def run(self) -> list[CheckResult]:
        results = [self.check_health()]
        if results[-1].passed:
            results.append(self.check_reply_decision())
        else:
            results.append(
                CheckResult(
                    name="reply-decisions",
                    passed=False,
                    status=None,
                    message="skipped because health check failed",
                    summary={},
                )
            )
        return results

    def check_health(self) -> CheckResult:
        try:
            status, body = self.client.get_json("/health")
        except RuntimeError as exc:
            return CheckResult("health", False, None, str(exc), {})
        passed = 200 <= status < 300
        return CheckResult(
            name="health",
            passed=passed,
            status=status,
            message="ok" if passed else "contract/runtime failure: non-2xx response",
            summary=_body_summary(body),
        )

    def check_reply_decision(self) -> CheckResult:
        try:
            status, body = self.client.post_json(
                "/v1/reply-decisions",
                build_minimal_reply_decision_request(),
            )
        except RuntimeError as exc:
            return CheckResult("reply-decisions", False, None, str(exc), {})

        summary = _decision_summary(body)
        passed = 200 <= status < 300 and bool(summary.get("decision_id"))
        if passed:
            message = "ok"
        elif 200 <= status < 300:
            message = "contract/runtime failure: response missing decision_id"
        else:
            message = "contract/runtime failure: non-2xx response"
        return CheckResult("reply-decisions", passed, status, message, summary)


def build_minimal_reply_decision_request() -> dict[str, Any]:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    request_id = f"eval-quick-{uuid.uuid4().hex}"
    return {
        "request_id": request_id,
        "organization_id": "org-eval",
        "platform": "pdd",
        "store_id": "store-eval",
        "message": {
            "external_message_id": f"msg-{request_id}",
            "sender_type": "buyer",
            "content": "When will this order ship?",
            "sent_at": now,
        },
        "conversation": {
            "external_conversation_id": f"conv-{request_id}",
            "buyer_ref": "buyer-eval",
            "messages": [],
        },
        "mode": "assist_first",
        "context": {
            "products": [],
            "orders": [],
            "logistics": [],
            "rules": [],
        },
    }


def format_result(result: CheckResult) -> str:
    status = f" status={result.status}" if result.status is not None else " status=unavailable"
    prefix = "PASS" if result.passed else "FAIL"
    details = _format_summary(result.summary)
    if details:
        return f"{prefix} {result.name}{status} {details}"
    return f"{prefix} {result.name}{status} {result.message}"


def _format_summary(summary: dict[str, Any]) -> str:
    fields = []
    for key in ("decision_id", "action", "decision_status"):
        value = summary.get(key)
        if value is not None:
            fields.append(f"{key}={value}")
    return " ".join(fields)


def _decision_summary(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {}
    return {
        "decision_id": body.get("decision_id"),
        "action": body.get("action"),
        "decision_status": body.get("decision_status"),
    }


def _body_summary(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        return {key: body.get(key) for key in ("status", "service", "environment") if key in body}
    return {}


def _parse_body(raw: bytes) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return raw[:200].decode("utf-8", errors="replace")
