from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CHART_DIR = ROOT / "deploy/helm/ecommerce-cs-agent"
VALUES_DEV = CHART_DIR / "values-dev.yaml"


def main() -> int:
    rendered = render_chart()
    docs = [
        doc
        for doc in yaml.safe_load_all(rendered)
        if isinstance(doc, dict) and doc.get("kind") in {"Deployment", "Job"}
    ]
    errors: list[str] = []

    for doc in docs:
        validate_workload(doc, errors)

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    print(f"K8s security check ok: {len(docs)} workloads")
    return 0


def render_chart() -> str:
    command = [
        "helm",
        "template",
        "ecommerce-cs-agent",
        str(CHART_DIR),
        "-n",
        "ecommerce-cs-agent-dev",
        "-f",
        str(VALUES_DEV),
    ]
    result = subprocess.run(
        command,
        check=True,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout


def validate_workload(doc: dict[str, Any], errors: list[str]) -> None:
    kind = str(doc["kind"])
    name = str(doc.get("metadata", {}).get("name", "<unknown>"))
    prefix = f"{kind}/{name}"
    pod_spec = get_pod_spec(doc)

    security_context = pod_spec.get("securityContext") or {}
    require(
        security_context.get("runAsNonRoot") is True,
        errors,
        f"{prefix}: pod securityContext.runAsNonRoot must be true",
    )
    require(
        security_context.get("seccompProfile", {}).get("type") == "RuntimeDefault",
        errors,
        f"{prefix}: pod securityContext.seccompProfile.type must be RuntimeDefault",
    )

    for container in pod_spec.get("containers") or []:
        validate_container(kind, name, container, errors)


def get_pod_spec(doc: dict[str, Any]) -> dict[str, Any]:
    if doc["kind"] == "Deployment":
        return doc["spec"]["template"]["spec"]
    if doc["kind"] == "Job":
        return doc["spec"]["template"]["spec"]
    raise ValueError(f"unsupported workload kind: {doc['kind']}")


def validate_container(
    kind: str, workload_name: str, container: dict[str, Any], errors: list[str]
) -> None:
    name = str(container.get("name", "<unknown>"))
    prefix = f"{kind}/{workload_name} container/{name}"
    image = str(container.get("image", ""))
    last_image_part = image.rsplit("/", maxsplit=1)[-1]

    require(
        ":" in last_image_part and not image.endswith(":latest"),
        errors,
        f"{prefix}: image must use an explicit non-latest tag",
    )

    security_context = container.get("securityContext") or {}
    require(
        security_context.get("allowPrivilegeEscalation") is False,
        errors,
        f"{prefix}: allowPrivilegeEscalation must be false",
    )
    require(
        security_context.get("readOnlyRootFilesystem") is True,
        errors,
        f"{prefix}: readOnlyRootFilesystem must be true",
    )
    require(
        "ALL" in (security_context.get("capabilities", {}).get("drop") or []),
        errors,
        f"{prefix}: capabilities.drop must include ALL",
    )

    resources = container.get("resources") or {}
    for bucket in ("requests", "limits"):
        for resource_name in ("cpu", "memory"):
            require(
                bool(resources.get(bucket, {}).get(resource_name)),
                errors,
                f"{prefix}: resources.{bucket}.{resource_name} is required",
            )

    if kind == "Deployment":
        require(
            bool(container.get("readinessProbe")),
            errors,
            f"{prefix}: readinessProbe is required",
        )
        require(
            bool(container.get("livenessProbe")),
            errors,
            f"{prefix}: livenessProbe is required",
        )


def require(condition: bool, errors: list[str], message: str) -> None:
    if not condition:
        errors.append(message)


if __name__ == "__main__":
    raise SystemExit(main())
