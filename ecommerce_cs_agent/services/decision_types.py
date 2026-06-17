from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DecisionState:
    request: dict[str, Any]
    response: dict[str, Any]
    context_refills: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    action_results: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    feedback: list[dict[str, Any]] = field(default_factory=list)
