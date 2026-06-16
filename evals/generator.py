from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any


DEFAULT_SCENARIO = {
    "scenario": "product_qa",
    "risk_tags": ["generated"],
    "message_templates": [
        "这个商品适合我这种情况吗？",
        "这款具体有什么区别？",
        "能不能帮我确认下这个问题？",
    ],
    "expected_behavior": {
        "expected_action": "candidate",
        "forbidden_actions": ["auto_reply"],
    },
}


def generate_blind_cases(
    *,
    suite: str,
    count: int,
    seed: str,
    scenarios_dir: Path,
    output_dir: Path,
) -> list[Path]:
    scenarios = _load_scenarios(scenarios_dir)
    rng = random.Random(seed)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_paths: list[Path] = []

    for index in range(count):
        scenario = scenarios[index % len(scenarios)]
        templates = scenario.get("message_templates") or DEFAULT_SCENARIO["message_templates"]
        message = rng.choice(templates)
        case_id = f"{suite}-{seed}-{index + 1:03d}".replace("/", "-")
        payload = {
            "case_id": case_id,
            "suite": suite,
            "scenario": scenario.get("scenario", "generated"),
            "risk_tags": scenario.get("risk_tags", ["generated"]),
            "input": {
                "request": {
                    "request_id": f"req-{case_id}",
                    "organization_id": "generated-org",
                    "store_id": "generated-store",
                    "platform": "pdd",
                    "message": {
                        "external_message_id": f"msg-{case_id}",
                        "sender_type": "buyer",
                        "content": message,
                        "sent_at": "2026-06-14T10:00:00+08:00",
                    },
                    "conversation": {
                        "external_conversation_id": f"conv-{case_id}",
                        "buyer_ref": "generated-buyer",
                        "messages": [],
                    },
                    "mode": "auto_when_safe",
                    "context": {},
                }
            },
            "public_context": scenario.get("public_context", {}),
            "hidden_expected_behavior": scenario.get(
                "expected_behavior",
                DEFAULT_SCENARIO["expected_behavior"],
            ),
            "assertions": {"schema": True, "policy_gate": True},
            "generation": {
                "seed": seed,
                "scenario_version": scenario.get("version", "generated-v1"),
                "generator_prompt_version": "deterministic-v1",
            },
        }
        output_path = output_dir / f"{case_id}.json"
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        generated_paths.append(output_path)
    return generated_paths


def _load_scenarios(scenarios_dir: Path) -> list[dict[str, Any]]:
    if not scenarios_dir.exists():
        return [DEFAULT_SCENARIO]
    scenarios: list[dict[str, Any]] = []
    for path in sorted(scenarios_dir.glob("*.json")):
        scenarios.append(json.loads(path.read_text(encoding="utf-8")))
    return scenarios or [DEFAULT_SCENARIO]
