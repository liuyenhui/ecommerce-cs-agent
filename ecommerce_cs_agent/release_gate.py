from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


DEFAULT_NAMESPACE = "ecommerce-cs-agent-dev"
DEFAULT_API_URL = "https://api.ecommerce-cs-agent-dev.fcihome.com"
DEFAULT_CUSTOMER_ADMIN_URL = "https://admin.ecommerce-cs-agent-dev.fcihome.com"
DEFAULT_SYSTEM_ADMIN_URL = "https://system-admin.ecommerce-cs-agent-dev.fcihome.com"
DEFAULT_RUNTIME_SECRET_GROUPS = (
    ("AGENT_API_TOKEN",),
    ("SESSION_SECRET", "ADMIN_SESSION_SECRET"),
    ("JWT_SECRET", "SYSTEM_ADMIN_SESSION_SECRET"),
    ("ADMIN_INITIAL_EMAIL",),
    ("ADMIN_INITIAL_PASSWORD_HASH",),
    ("SYSTEM_ADMIN_INITIAL_EMAIL", "ADMIN_INITIAL_EMAIL"),
    ("SYSTEM_ADMIN_INITIAL_PASSWORD_HASH", "ADMIN_INITIAL_PASSWORD_HASH"),
    ("DATABASE_URL",),
    ("OPEN_ERP_INTEGRATION_TOKEN",),
    ("OPEN_ERP_BILLING_LEASE_SECRET",),
)
HELM_RESET_REASON_MARKERS = (
    "failed",
    "failure",
    "rollback",
    "remediation",
    "retriesexceeded",
    "timeout",
    "timed out",
    "deadline",
)


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def passed(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    details: str
    command: list[str] | None = None


@dataclass(frozen=True)
class ReleaseGateReport:
    generated_at: str
    config: "DevReleaseGateConfig"
    checks: list[GateCheck]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


@dataclass(frozen=True)
class DevReleaseGateConfig:
    commit_sha: str
    image_tag: str
    gitops_commit: str | None = None
    target_url: str = DEFAULT_API_URL
    customer_admin_url: str = DEFAULT_CUSTOMER_ADMIN_URL
    system_admin_url: str = DEFAULT_SYSTEM_ADMIN_URL
    namespace: str = DEFAULT_NAMESPACE
    flux_namespace: str = "flux-system"
    flux_root_source: str = "flux-system"
    flux_kustomization: str = "ecommerce-cs-agent-dev"
    app_source: str = "ecommerce-cs-agent-app"
    helm_release: str = "ecommerce-cs-agent"
    api_deployment: str = "ecommerce-cs-agent-api"
    admin_deployment: str = "ecommerce-cs-agent-admin"
    runtime_secret: str = "ecommerce-cs-agent-runtime"
    output: Path = Path("reports/release-gate/dev-release-gate.md")
    reconcile: bool = True
    run_kubectl: bool = True
    run_live_eval: bool = True
    image_wait_seconds: int = 300
    poll_interval_seconds: float = 5.0
    timeout_seconds: int = 900
    health_timeout_seconds: float = 10.0
    extra_secrets: tuple[str, ...] = field(default_factory=tuple)
    required_runtime_secret_groups: tuple[tuple[str, ...], ...] = DEFAULT_RUNTIME_SECRET_GROUPS


CommandRunner = Callable[[Sequence[str]], CommandResult]
HttpGetter = Callable[[str, float], tuple[int, Any]]


def redact_text(text: str, *, secrets: Iterable[str] = ()) -> str:
    redacted = text
    for secret in secrets:
        if secret and len(secret) >= 4:
            redacted = redacted.replace(secret, "<redacted>")
    redacted = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", redacted)
    redacted = re.sub(
        r"(AGENT_API_TOKEN|SESSION_SECRET|JWT_SECRET|LLM_API_KEY)=([^\s]+)",
        r"\1=<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"postgresql://[^:\s/@]+:[^@\s]+@([^\s]+)",
        r"postgresql://<redacted>@\1",
        redacted,
    )
    redacted = re.sub(r"\bsk-[A-Za-z0-9_-]{20,}\b", "sk-<redacted>", redacted)
    redacted = re.sub(r"\bgh[opsu]_[A-Za-z0-9_]{20,}\b", "gh_<redacted>", redacted)
    return redacted


def run_dev_release_gate(
    config: DevReleaseGateConfig,
    *,
    command_runner: Callable[..., CommandResult] | None = None,
    http_get: HttpGetter | None = None,
) -> ReleaseGateReport:
    runner = command_runner or _run_command
    getter = http_get or _http_get
    secrets = _known_secrets(config)
    checks: list[GateCheck] = []

    if config.run_kubectl:
        checks.append(_check_runtime_secret_contract(config, runner, secrets))
        if _has_failed(checks):
            return _write_report(config, checks, secrets)

        if config.reconcile:
            reset_checks, helm_reconcile_requested = _reset_failed_helm_release_if_needed(config, runner, secrets)
            checks.extend(reset_checks)
            if _has_failed(reset_checks):
                checks.extend(_collect_failure_diagnostics(config, runner, secrets))
                return _write_report(config, checks, secrets)
            checks.extend(_trigger_reconcile(config, runner, secrets, include_helm_release=not helm_reconcile_requested))
        checks.extend(_wait_for_flux(config, runner, secrets))
        if _has_failed(checks):
            checks.extend(_collect_failure_diagnostics(config, runner, secrets))
            return _write_report(config, checks, secrets)

        checks.extend(_verify_deployed_images(config, runner, secrets))
        if _has_failed(checks):
            checks.extend(_collect_failure_diagnostics(config, runner, secrets))
            return _write_report(config, checks, secrets)

        checks.extend(_wait_for_rollouts(config, runner, secrets))
        if _has_failed(checks):
            checks.extend(_collect_failure_diagnostics(config, runner, secrets))
            return _write_report(config, checks, secrets)

        checks.append(_check_schema_migrations(config, runner, secrets))
        if _has_failed(checks):
            checks.extend(_collect_failure_diagnostics(config, runner, secrets))
            return _write_report(config, checks, secrets)

    checks.extend(
        [
            _check_http_health("api health", config.target_url, getter, config, secrets),
            _check_http_health("customer admin health", config.customer_admin_url, getter, config, secrets),
            _check_http_health("system admin health", config.system_admin_url, getter, config, secrets),
        ]
    )

    if config.run_live_eval:
        checks.append(_run_live_eval(config, runner, secrets))

    return _write_report(config, checks, secrets)


def _write_report(
    config: DevReleaseGateConfig,
    checks: list[GateCheck],
    secrets: tuple[str, ...],
) -> ReleaseGateReport:
    report = ReleaseGateReport(
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        config=config,
        checks=checks,
    )
    config.output.parent.mkdir(parents=True, exist_ok=True)
    config.output.write_text(_format_report(report, secrets), encoding="utf-8")
    return report


def _has_failed(checks: list[GateCheck]) -> bool:
    return any(not check.passed for check in checks)


def _check_runtime_secret_contract(
    config: DevReleaseGateConfig,
    runner: Callable[..., CommandResult],
    secrets: tuple[str, ...],
) -> GateCheck:
    command = [
        "kubectl",
        "-n",
        config.namespace,
        "get",
        "secret",
        config.runtime_secret,
        "-o",
        "json",
    ]
    result = runner(command, timeout=60)
    if not result.passed:
        return GateCheck(
            name="runtime secret contract",
            passed=False,
            details=_summarize_command_failure(result, secrets),
            command=command,
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return GateCheck(
            name="runtime secret contract",
            passed=False,
            details="runtime Secret JSON could not be parsed",
            command=command,
        )
    keys = set((payload.get("data") or {}).keys())
    missing = [
        "|".join(group)
        for group in config.required_runtime_secret_groups
        if not any(key in keys for key in group)
    ]
    if missing:
        return GateCheck(
            name="runtime secret contract",
            passed=False,
            details=f"missing key groups: {', '.join(missing)}",
            command=command,
        )
    present = ", ".join("|".join(group) for group in config.required_runtime_secret_groups)
    return GateCheck(
        name="runtime secret contract",
        passed=True,
        details=f"required key groups present: {present}",
        command=command,
    )


def _reset_failed_helm_release_if_needed(
    config: DevReleaseGateConfig,
    runner: Callable[..., CommandResult],
    secrets: tuple[str, ...],
) -> tuple[list[GateCheck], bool]:
    status_command = [
        "kubectl",
        "-n",
        config.namespace,
        "get",
        "helmrelease",
        config.helm_release,
        "-o",
        "json",
    ]
    status_result = runner(status_command, timeout=60)
    if not status_result.passed:
        return (
            [
                GateCheck(
                    name="helm release reset",
                    passed=False,
                    details=_summarize_command_failure(status_result, secrets),
                    command=status_command,
                )
            ],
            False,
        )

    ready, should_reset, summary = _helm_release_status_summary(status_result.stdout)
    if ready:
        return (
            [
                GateCheck(
                    name="helm release reset",
                    passed=True,
                    details=f"ready; reset not needed; {summary}",
                    command=status_command,
                )
            ],
            False,
        )

    if not should_reset:
        return (
            [
                GateCheck(
                    name="helm release reset",
                    passed=True,
                    details=f"not ready, but reset not needed; {summary}",
                    command=status_command,
                )
            ],
            False,
        )

    requested_at = str(int(time.time()))
    reset_command = [
        "kubectl",
        "-n",
        config.namespace,
        "annotate",
        f"helmrelease/{config.helm_release}",
        f"reconcile.fluxcd.io/resetAt={requested_at}",
        f"reconcile.fluxcd.io/requestedAt={requested_at}",
        "--overwrite",
    ]
    reset_result = runner(reset_command, timeout=60)
    details = f"reset requested after failed HelmRelease: {summary}"
    if reset_result.stdout.strip() or reset_result.stderr.strip():
        details = f"{details}; {_summarize_command_failure(reset_result, secrets)}"
    return (
        [
            GateCheck(
                name="helm release reset",
                passed=reset_result.passed,
                details=redact_text(details, secrets=secrets),
                command=reset_command,
            )
        ],
        reset_result.passed,
    )


def _helm_release_ready_summary(text: str) -> tuple[bool, str]:
    ready, _, summary = _helm_release_status_summary(text)
    return ready, summary


def _helm_release_status_summary(text: str) -> tuple[bool, bool, str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False, False, "HelmRelease JSON could not be parsed"
    conditions = payload.get("status", {}).get("conditions", [])
    parts = []
    ready = False
    should_reset = False
    for condition in conditions:
        condition_type = str(condition.get("type") or "")
        status = str(condition.get("status") or "")
        reason = str(condition.get("reason") or "")
        message = str(condition.get("message") or "")
        if condition_type == "Ready" and status == "True":
            ready = True
        if status == "False" and _helm_release_condition_needs_reset(reason, message):
            should_reset = True
        detail = f"{condition_type}={status}"
        if reason:
            detail = f"{detail} reason={reason}"
        if message:
            detail = f"{detail} message={message[:240]}"
        parts.append(detail)
    return ready, should_reset and not ready, "; ".join(parts) or "no status conditions"


def _helm_release_condition_needs_reset(reason: str, message: str) -> bool:
    text = f"{reason} {message}".lower()
    return any(marker in text for marker in HELM_RESET_REASON_MARKERS)


def _trigger_reconcile(
    config: DevReleaseGateConfig,
    runner: Callable[..., CommandResult],
    secrets: tuple[str, ...],
    *,
    include_helm_release: bool = True,
) -> list[GateCheck]:
    requested_at = str(int(time.time()))
    targets = [
        (config.flux_namespace, f"gitrepository/{config.flux_root_source}"),
        (config.flux_namespace, f"kustomization/{config.flux_kustomization}"),
        (config.namespace, f"gitrepository/{config.app_source}"),
    ]
    if include_helm_release:
        targets.append((config.namespace, f"helmrelease/{config.helm_release}"))
    checks: list[GateCheck] = []
    for namespace, target in targets:
        command = [
            "kubectl",
            "-n",
            namespace,
            "annotate",
            target,
            f"reconcile.fluxcd.io/requestedAt={requested_at}",
            "--overwrite",
        ]
        checks.append(_command_check(f"reconcile {target}", command, runner, secrets, timeout=60))
    return checks


def _collect_failure_diagnostics(
    config: DevReleaseGateConfig,
    runner: Callable[..., CommandResult],
    secrets: tuple[str, ...],
) -> list[GateCheck]:
    diagnostics = [
        (
            "helmrelease diagnostics",
            [
                "kubectl",
                "-n",
                config.namespace,
                "get",
                "helmrelease",
                config.helm_release,
                "-o",
                "json",
            ],
        ),
        (
            "recent namespace events",
            [
                "kubectl",
                "-n",
                config.namespace,
                "get",
                "events",
                "--sort-by=.lastTimestamp",
            ],
        ),
        (
            "api pod logs",
            [
                "kubectl",
                "-n",
                config.namespace,
                "logs",
                "-l",
                "app.kubernetes.io/component=api",
                "--all-containers=true",
                "--tail=80",
                "--prefix=true",
            ],
        ),
        (
            "admin pod logs",
            [
                "kubectl",
                "-n",
                config.namespace,
                "logs",
                "-l",
                "app.kubernetes.io/component=admin",
                "--all-containers=true",
                "--tail=80",
                "--prefix=true",
            ],
        ),
    ]
    checks: list[GateCheck] = []
    for name, command in diagnostics:
        result = runner(command, timeout=120)
        details = _diagnostic_details(name, result, secrets)
        checks.append(GateCheck(name=name, passed=result.passed, details=details, command=command))
    return checks


def _diagnostic_details(name: str, result: CommandResult, secrets: tuple[str, ...]) -> str:
    if name == "helmrelease diagnostics" and result.passed:
        _, summary = _helm_release_ready_summary(result.stdout)
        return redact_text(summary, secrets=secrets)
    return _summarize_command_failure(result, secrets)


def _wait_for_flux(
    config: DevReleaseGateConfig,
    runner: Callable[..., CommandResult],
    secrets: tuple[str, ...],
) -> list[GateCheck]:
    timeout = f"{config.timeout_seconds}s"
    commands = [
        (
            "flux kustomization ready",
            [
                "kubectl",
                "-n",
                config.flux_namespace,
                "wait",
                f"kustomization/{config.flux_kustomization}",
                "--for=condition=Ready",
                f"--timeout={timeout}",
            ],
        ),
        (
            "app source ready",
            [
                "kubectl",
                "-n",
                config.namespace,
                "wait",
                f"gitrepository/{config.app_source}",
                "--for=condition=Ready",
                f"--timeout={timeout}",
            ],
        ),
        (
            "helm release ready",
            [
                "kubectl",
                "-n",
                config.namespace,
                "wait",
                f"helmrelease/{config.helm_release}",
                "--for=condition=Ready",
                f"--timeout={timeout}",
            ],
        ),
    ]
    return [
        _command_check(name, command, runner, secrets, timeout=config.timeout_seconds + 30)
        for name, command in commands
    ]


def _wait_for_rollouts(
    config: DevReleaseGateConfig,
    runner: Callable[..., CommandResult],
    secrets: tuple[str, ...],
) -> list[GateCheck]:
    timeout = f"{config.timeout_seconds}s"
    return [
        _command_check(
            "api rollout",
            [
                "kubectl",
                "-n",
                config.namespace,
                "rollout",
                "status",
                f"deploy/{config.api_deployment}",
                f"--timeout={timeout}",
            ],
            runner,
            secrets,
            timeout=config.timeout_seconds + 30,
        ),
        _command_check(
            "admin rollout",
            [
                "kubectl",
                "-n",
                config.namespace,
                "rollout",
                "status",
                f"deploy/{config.admin_deployment}",
                f"--timeout={timeout}",
            ],
            runner,
            secrets,
            timeout=config.timeout_seconds + 30,
        ),
    ]


def _verify_deployed_images(
    config: DevReleaseGateConfig,
    runner: Callable[..., CommandResult],
    secrets: tuple[str, ...],
) -> list[GateCheck]:
    checks = []
    for name, deployment in (
        ("api image tag", config.api_deployment),
        ("admin image tag", config.admin_deployment),
    ):
        command = [
            "kubectl",
            "-n",
            config.namespace,
            "get",
            "deploy",
            deployment,
            "-o",
            "jsonpath={.spec.template.spec.containers[0].image}",
        ]
        result = _poll_command(
            command,
            runner,
            timeout_seconds=config.image_wait_seconds,
            poll_interval_seconds=config.poll_interval_seconds,
            success=lambda item: item.passed
            and _image_ref_has_exact_tag((item.stdout or "").strip(), config.image_tag),
        )
        image = redact_text((result.stdout or "").strip(), secrets=secrets)
        checks.append(
            GateCheck(
                name=name,
                passed=result.passed and _image_ref_has_exact_tag(image, config.image_tag),
                details=image or _summarize_command_failure(result, secrets),
                command=command,
            )
        )
    return checks


def _check_schema_migrations(
    config: DevReleaseGateConfig,
    runner: Callable[..., CommandResult],
    secrets: tuple[str, ...],
) -> GateCheck:
    python_code = (
        "import json, os, psycopg; "
        "from pathlib import Path; "
        "conn=psycopg.connect(os.environ['DATABASE_URL']); "
        "cur=conn.cursor(); "
        "cur.execute(\"select version from schema_migration order by version\"); "
        "applied=[row[0] for row in cur.fetchall()]; "
        "expected=sorted(path.name for path in Path('migrations').glob('[0-9][0-9][0-9]_*.sql')); "
        "print(json.dumps({'schema_migration': applied, 'expected_migrations': expected, 'missing': [item for item in expected if item not in applied]}))"
    )
    command = [
        "kubectl",
        "-n",
        config.namespace,
        "exec",
        f"deploy/{config.api_deployment}",
        "--",
        "python",
        "-c",
        python_code,
    ]
    result = runner(command, timeout=120)
    missing = _safe_json_list(result.stdout, "missing")
    migrations = _safe_json_list(result.stdout, "schema_migration")
    if result.passed and missing:
        details = f"applied={', '.join(migrations)}; missing={', '.join(missing)}"
    elif result.passed:
        details = ", ".join(migrations)
    else:
        details = _summarize_command_failure(result, secrets)
    return GateCheck(
        name="schema_migration",
        passed=result.passed and bool(migrations) and not missing,
        details=redact_text(details, secrets=secrets),
        command=command,
    )


def _check_http_health(
    name: str,
    url: str,
    getter: HttpGetter,
    config: DevReleaseGateConfig,
    secrets: tuple[str, ...],
) -> GateCheck:
    try:
        status, body = getter(url.rstrip("/") + "/health", config.health_timeout_seconds)
    except Exception as exc:
        return GateCheck(name=name, passed=False, details=redact_text(str(exc), secrets=secrets))
    details = f"status={status} body={_compact_json(body)}"
    return GateCheck(name=name, passed=200 <= status < 300, details=redact_text(details, secrets=secrets))


def _run_live_eval(
    config: DevReleaseGateConfig,
    runner: Callable[..., CommandResult],
    secrets: tuple[str, ...],
) -> GateCheck:
    token = os.environ.get("AGENT_API_TOKEN")
    if not token and config.run_kubectl:
        token = _read_agent_token_from_k8s(config, runner, secrets)
        secrets = tuple(item for item in (*secrets, token) if item)
    if not token:
        return GateCheck(
            name="quick live eval",
            passed=False,
            details="AGENT_API_TOKEN is required from environment or Kubernetes Secret",
        )

    command = [
        sys.executable,
        "-m",
        "evals.cli",
        "run-suite",
        "--suite",
        "quick",
        "--target",
        "live",
        "--target-url",
        config.target_url,
    ]
    env = _minimal_eval_env(token)
    result = runner(command, env=env, timeout=config.timeout_seconds)
    details = redact_text("\n".join(part for part in [result.stdout, result.stderr] if part).strip(), secrets=secrets)
    return GateCheck(
        name="quick live eval",
        passed=result.passed and "quick suite PASS" in result.stdout,
        details=details or _summarize_command_failure(result, secrets),
        command=command,
    )


def _read_agent_token_from_k8s(
    config: DevReleaseGateConfig,
    runner: Callable[..., CommandResult],
    secrets: tuple[str, ...],
) -> str | None:
    command = [
        "kubectl",
        "-n",
        config.namespace,
        "get",
        "secret",
        config.runtime_secret,
        "-o",
        "json",
    ]
    result = runner(command, timeout=60)
    if not result.passed:
        return None
    try:
        payload = json.loads(result.stdout)
        encoded = payload.get("data", {}).get("AGENT_API_TOKEN")
        if not encoded:
            return None
        return base64.b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None


def _command_check(
    name: str,
    command: list[str],
    runner: Callable[..., CommandResult],
    secrets: tuple[str, ...],
    *,
    timeout: int,
) -> GateCheck:
    result = runner(command, timeout=timeout)
    details = result.stdout.strip() or result.stderr.strip() or ("ok" if result.passed else "failed")
    return GateCheck(
        name=name,
        passed=result.passed,
        details=redact_text(details, secrets=secrets),
        command=command,
    )


def _poll_command(
    command: list[str],
    runner: Callable[..., CommandResult],
    *,
    timeout_seconds: int | float,
    poll_interval_seconds: float,
    success: Callable[[CommandResult], bool],
) -> CommandResult:
    deadline = time.monotonic() + max(timeout_seconds, 0)
    last_result: CommandResult | None = None
    while True:
        last_result = runner(command, timeout=min(60, max(timeout_seconds, 1)))
        if success(last_result):
            return last_result
        if time.monotonic() >= deadline:
            return last_result
        time.sleep(min(poll_interval_seconds, max(deadline - time.monotonic(), 0)))


def _image_ref_has_exact_tag(image_ref: str, expected_tag: str) -> bool:
    if "@" in image_ref:
        return False
    last_segment = image_ref.rsplit("/", 1)[-1]
    if ":" not in last_segment:
        return False
    return last_segment.rsplit(":", 1)[-1] == expected_tag


def _minimal_eval_env(token: str) -> dict[str, str]:
    allowed_keys = {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "PYTHONPATH",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed_keys}
    env["AGENT_API_TOKEN"] = token
    return env


def _run_command(
    command: Sequence[str],
    *,
    env: Mapping[str, str] | None = None,
    timeout: int | float | None = None,
) -> CommandResult:
    try:
        completed = subprocess.run(
            list(command),
            env=dict(env) if env is not None else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(
            command=list(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            command=list(command),
            returncode=124,
            stdout=exc.stdout or "",
            stderr=f"command timed out after {timeout}s",
        )
    except FileNotFoundError as exc:
        return CommandResult(
            command=list(command),
            returncode=127,
            stderr=str(exc),
        )


def _http_get(url: str, timeout: float) -> tuple[int, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, _parse_body(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, _parse_body(body)


def _parse_body(body: str) -> Any:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return body.strip()


def _compact_json(value: Any) -> str:
    if isinstance(value, str):
        return value[:500]
    return json.dumps(value, ensure_ascii=False, sort_keys=True)[:500]


def _safe_json_list(text: str, key: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    value = payload.get(key)
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _summarize_command_failure(result: CommandResult, secrets: tuple[str, ...]) -> str:
    output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()
    if not output:
        output = f"exit={result.returncode}"
    return redact_text(output[:1200], secrets=secrets)


def _known_secrets(config: DevReleaseGateConfig) -> tuple[str, ...]:
    env_secrets = [
        os.environ.get("AGENT_API_TOKEN"),
        os.environ.get("SESSION_SECRET"),
        os.environ.get("JWT_SECRET"),
        os.environ.get("LLM_API_KEY"),
        os.environ.get("DATABASE_URL"),
    ]
    return tuple(item for item in (*config.extra_secrets, *env_secrets) if item)


def _format_report(report: ReleaseGateReport, secrets: tuple[str, ...]) -> str:
    status = "PASS" if report.passed else "FAIL"
    config = report.config
    lines = [
        f"# Dev Release Gate Report: {status}",
        "",
        f"- generated_at: `{report.generated_at}`",
        f"- commit_sha: `{config.commit_sha}`",
        f"- image_tag: `{config.image_tag}`",
        f"- gitops_commit: `{config.gitops_commit or 'unknown'}`",
        f"- namespace: `{config.namespace}`",
        f"- api_url: `{config.target_url}`",
        f"- customer_admin_url: `{config.customer_admin_url}`",
        f"- system_admin_url: `{config.system_admin_url}`",
        "",
        "## Checks",
        "",
        "| Check | Result | Details |",
        "| --- | --- | --- |",
    ]
    for check in report.checks:
        result = "PASS" if check.passed else "FAIL"
        details = redact_text(check.details.replace("\n", "<br>"), secrets=secrets)
        lines.append(f"| {check.name} | {result} | {details} |")
    lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run dev deployment release gate checks.")
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--image-tag", required=True)
    parser.add_argument("--gitops-commit")
    parser.add_argument("--target-url", default=DEFAULT_API_URL)
    parser.add_argument("--customer-admin-url", "--admin-url", dest="customer_admin_url", default=DEFAULT_CUSTOMER_ADMIN_URL)
    parser.add_argument("--system-admin-url", default=DEFAULT_SYSTEM_ADMIN_URL)
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--output", default="reports/release-gate/dev-release-gate.md")
    parser.add_argument("--skip-reconcile", action="store_true")
    parser.add_argument("--skip-kubectl", action="store_true")
    parser.add_argument("--skip-live-eval", action="store_true")
    parser.add_argument("--image-wait", type=int, default=300)
    parser.add_argument("--timeout", type=int, default=900)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_dev_release_gate(
        DevReleaseGateConfig(
            commit_sha=args.commit_sha,
            image_tag=args.image_tag,
            gitops_commit=args.gitops_commit,
            target_url=args.target_url,
            customer_admin_url=args.customer_admin_url,
            system_admin_url=args.system_admin_url,
            namespace=args.namespace,
            output=Path(args.output),
            reconcile=not args.skip_reconcile,
            run_kubectl=not args.skip_kubectl,
            run_live_eval=not args.skip_live_eval,
            image_wait_seconds=args.image_wait,
            timeout_seconds=args.timeout,
        )
    )
    print(f"release gate report: {args.output}")
    print(f"release gate {'PASS' if report.passed else 'FAIL'}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
