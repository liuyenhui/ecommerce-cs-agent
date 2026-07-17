import json
import os
from pathlib import Path

from ecommerce_cs_agent.release_gate import (
    CommandResult,
    DevReleaseGateConfig,
    redact_text,
    run_dev_release_gate,
)


def _runtime_secret_payload(*keys: str) -> str:
    return json.dumps({"data": {key: "cmVkYWN0ZWQ=" for key in keys}})


def _complete_runtime_secret_payload() -> str:
    return _runtime_secret_payload(
        "AGENT_API_TOKEN",
        "SESSION_SECRET",
        "JWT_SECRET",
        "ADMIN_INITIAL_EMAIL",
        "ADMIN_INITIAL_PASSWORD_HASH",
        "SYSTEM_ADMIN_INITIAL_EMAIL",
        "SYSTEM_ADMIN_INITIAL_PASSWORD_HASH",
        "DATABASE_URL",
        "OPEN_ERP_INTEGRATION_TOKEN",
        "OPEN_ERP_BILLING_LEASE_SECRET",
    )


def test_release_gate_report_redacts_tokens_and_database_urls(tmp_path: Path) -> None:
    secret = "test-token-should-not-print"
    text = (
        f"Authorization: Bearer {secret}\n"
        f"AGENT_API_TOKEN={secret}\n"
        "DATABASE_URL=postgresql://user:password@example.local:5432/app\n"
    )

    redacted = redact_text(text, secrets=[secret])

    assert secret not in redacted
    assert "password" not in redacted
    assert "Bearer <redacted>" in redacted
    assert "postgresql://<redacted>@example.local:5432/app" in redacted


def test_release_gate_runs_rollout_health_eval_and_writes_redacted_report(
    tmp_path: Path, monkeypatch
) -> None:
    secret = "test-token-should-not-print"
    monkeypatch.setenv("AGENT_API_TOKEN", secret)
    monkeypatch.setenv("KUBECONFIG_CONTENT", "fake-kubeconfig")
    monkeypatch.setenv("GITHUB_TOKEN", "fake-github-token")
    commands: list[list[str]] = []

    def runner(command, *, env=None, timeout=None):
        commands.append(list(command))
        text_command = " ".join(command)
        assert secret not in text_command
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "secret"]:
            return CommandResult(command=list(command), returncode=0, stdout=_complete_runtime_secret_payload())
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "helmrelease"]:
            return CommandResult(
                command=list(command),
                returncode=0,
                stdout=json.dumps({"status": {"conditions": [{"type": "Ready", "status": "True"}]}}),
            )
        if "jsonpath={.spec.template.spec.containers[0].image}" in text_command:
            return CommandResult(command=list(command), returncode=0, stdout="repo:sha-abc123456789")
        if "schema_migration" in text_command:
            payload = {
                "schema_migration": ["001_initial.sql", "007_product_knowledge_storage.sql"],
                "expected_migrations": ["001_initial.sql", "007_product_knowledge_storage.sql"],
                "missing": [],
            }
            return CommandResult(command=list(command), returncode=0, stdout=json.dumps(payload))
        if command[:3] == [os.sys.executable, "-m", "evals.cli"]:
            assert command[-2:] == ["--timeout", "30.0"]
            assert env is not None
            assert env["AGENT_API_TOKEN"] == secret
            assert "KUBECONFIG_CONTENT" not in env
            assert "GITHUB_TOKEN" not in env
            return CommandResult(
                command=list(command),
                returncode=0,
                stdout="PASS health status=200\nquick suite PASS target=live url=https://api.example.test",
            )
        return CommandResult(command=list(command), returncode=0, stdout="ok")

    def http_get(url: str, timeout: float):
        return 200, "ok" if "admin" in url else {"status": "ok"}

    report_path = tmp_path / "release-gate.md"
    report = run_dev_release_gate(
        DevReleaseGateConfig(
            commit_sha="abc1234567890000",
            image_tag="sha-abc123456789",
            gitops_commit="gitops123",
            target_url="https://api.example.test",
            customer_admin_url="https://admin.example.test",
            system_admin_url="https://system-admin.example.test",
            output=report_path,
            reconcile=False,
        ),
        command_runner=runner,
        http_get=http_get,
    )

    report_text = report_path.read_text(encoding="utf-8")
    assert report.passed is True
    assert "sha-abc123456789" in report_text
    assert "gitops123" in report_text
    assert "quick suite PASS" in report_text
    assert "001_initial.sql" in report_text
    assert "- customer_admin_url: `https://admin.example.test`" in report_text
    assert "- system_admin_url: `https://system-admin.example.test`" in report_text
    assert any(check.name == "customer admin health" for check in report.checks)
    assert any(check.name == "system admin health" for check in report.checks)
    assert secret not in report_text
    assert any(command[:4] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "rollout"] for command in commands)


def test_release_gate_fails_when_deployed_image_tag_does_not_match(tmp_path: Path) -> None:
    def runner(command, *, env=None, timeout=None):
        text_command = " ".join(command)
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "secret"]:
            return CommandResult(command=list(command), returncode=0, stdout=_complete_runtime_secret_payload())
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "helmrelease"]:
            return CommandResult(
                command=list(command),
                returncode=0,
                stdout=json.dumps({"status": {"conditions": [{"type": "Ready", "status": "True"}]}}),
            )
        if "jsonpath={.spec.template.spec.containers[0].image}" in text_command:
            return CommandResult(command=list(command), returncode=0, stdout="repo:sha-old")
        return CommandResult(command=list(command), returncode=0, stdout="ok")

    report = run_dev_release_gate(
        DevReleaseGateConfig(
            commit_sha="abc1234567890000",
            image_tag="sha-abc123456789",
            output=tmp_path / "release-gate.md",
            run_live_eval=False,
            image_wait_seconds=0,
        ),
        command_runner=runner,
        http_get=lambda url, timeout: (200, {"status": "ok"}),
    )

    assert report.passed is False
    assert any(
        check.name == "api image tag" and not check.passed
        for check in report.checks
    )
    assert not any(check.name.endswith("health") for check in report.checks)
    assert not any(check.name == "quick live eval" for check in report.checks)
    assert any(check.name == "recent namespace events" for check in report.checks)


def test_release_gate_requires_exact_deployed_image_tag(tmp_path: Path) -> None:
    def runner(command, *, env=None, timeout=None):
        text_command = " ".join(command)
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "secret"]:
            return CommandResult(command=list(command), returncode=0, stdout=_complete_runtime_secret_payload())
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "helmrelease"]:
            return CommandResult(
                command=list(command),
                returncode=0,
                stdout=json.dumps({"status": {"conditions": [{"type": "Ready", "status": "True"}]}}),
            )
        if "jsonpath={.spec.template.spec.containers[0].image}" in text_command:
            return CommandResult(command=list(command), returncode=0, stdout="repo:sha-abc123456789-bad")
        return CommandResult(command=list(command), returncode=0, stdout="ok")

    report = run_dev_release_gate(
        DevReleaseGateConfig(
            commit_sha="abc1234567890000",
            image_tag="sha-abc123456789",
            output=tmp_path / "release-gate.md",
            run_live_eval=False,
            image_wait_seconds=0,
        ),
        command_runner=runner,
        http_get=lambda url, timeout: (200, {"status": "ok"}),
    )

    assert report.passed is False
    assert any(
        check.name == "api image tag" and not check.passed
        for check in report.checks
    )


def test_release_gate_fails_when_schema_migration_is_missing(tmp_path: Path) -> None:
    def runner(command, *, env=None, timeout=None):
        text_command = " ".join(command)
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "secret"]:
            return CommandResult(command=list(command), returncode=0, stdout=_complete_runtime_secret_payload())
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "helmrelease"]:
            return CommandResult(
                command=list(command),
                returncode=0,
                stdout=json.dumps({"status": {"conditions": [{"type": "Ready", "status": "True"}]}}),
            )
        if "jsonpath={.spec.template.spec.containers[0].image}" in text_command:
            return CommandResult(command=list(command), returncode=0, stdout="repo:sha-abc123456789")
        if "schema_migration" in text_command:
            payload = {
                "schema_migration": ["001_initial.sql"],
                "expected_migrations": ["001_initial.sql", "002_next.sql"],
                "missing": ["002_next.sql"],
            }
            return CommandResult(command=list(command), returncode=0, stdout=json.dumps(payload))
        return CommandResult(command=list(command), returncode=0, stdout="ok")

    report = run_dev_release_gate(
        DevReleaseGateConfig(
            commit_sha="abc1234567890000",
            image_tag="sha-abc123456789",
            output=tmp_path / "release-gate.md",
            run_live_eval=False,
        ),
        command_runner=runner,
        http_get=lambda url, timeout: (200, {"status": "ok"}),
    )

    assert report.passed is False
    assert any(
        check.name == "schema_migration"
        and not check.passed
        and "missing=002_next.sql" in check.details
        for check in report.checks
    )


def test_release_gate_secret_preflight_fails_before_forcing_reconcile(tmp_path: Path) -> None:
    commands: list[list[str]] = []
    http_calls: list[str] = []

    def runner(command, *, env=None, timeout=None):
        commands.append(list(command))
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "secret"]:
            return CommandResult(
                command=list(command),
                returncode=0,
                stdout=_runtime_secret_payload("AGENT_API_TOKEN", "DATABASE_URL"),
            )
        return CommandResult(command=list(command), returncode=0, stdout="ok")

    def http_get(url: str, timeout: float):
        http_calls.append(url)
        return 200, {"status": "ok"}

    report = run_dev_release_gate(
        DevReleaseGateConfig(
            commit_sha="abc1234567890000",
            image_tag="sha-abc123456789",
            output=tmp_path / "release-gate.md",
            run_live_eval=False,
            image_wait_seconds=0,
        ),
        command_runner=runner,
        http_get=http_get,
    )

    assert report.passed is False
    assert any(
        check.name == "runtime secret contract"
        and not check.passed
        and "OPEN_ERP_INTEGRATION_TOKEN" in check.details
        and "OPEN_ERP_BILLING_LEASE_SECRET" in check.details
        for check in report.checks
    )
    assert not any("annotate" in command for command in commands)
    assert http_calls == []


def test_release_gate_does_not_reset_progressing_helmrelease(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def runner(command, *, env=None, timeout=None):
        commands.append(list(command))
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "secret"]:
            return CommandResult(command=list(command), returncode=0, stdout=_complete_runtime_secret_payload())
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "helmrelease"]:
            return CommandResult(
                command=list(command),
                returncode=0,
                stdout=json.dumps(
                    {
                        "status": {
                            "conditions": [
                                {
                                    "type": "Ready",
                                    "status": "False",
                                    "reason": "Progressing",
                                    "message": "running upgrade",
                                }
                            ]
                        }
                    }
                ),
            )
        if "jsonpath={.spec.template.spec.containers[0].image}" in " ".join(command):
            return CommandResult(command=list(command), returncode=0, stdout="repo:sha-abc123456789")
        if "schema_migration" in " ".join(command):
            return CommandResult(
                command=list(command),
                returncode=0,
                stdout=json.dumps({"schema_migration": ["001_initial.sql"], "expected_migrations": ["001_initial.sql"], "missing": []}),
            )
        return CommandResult(command=list(command), returncode=0, stdout="ok")

    report = run_dev_release_gate(
        DevReleaseGateConfig(
            commit_sha="abc1234567890000",
            image_tag="sha-abc123456789",
            output=tmp_path / "release-gate.md",
            run_live_eval=False,
        ),
        command_runner=runner,
        http_get=lambda url, timeout: (200, {"status": "ok"}),
    )

    assert report.passed is True
    assert not any(
        any(item.startswith("reconcile.fluxcd.io/resetAt=") for item in command)
        for command in commands
    )
    assert any(
        check.name == "helm release reset"
        and check.passed
        and "reset not needed" in check.details
        and "Progressing" in check.details
        for check in report.checks
    )


def test_release_gate_resets_failed_helmrelease_before_reconcile(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def runner(command, *, env=None, timeout=None):
        commands.append(list(command))
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "secret"]:
            return CommandResult(command=list(command), returncode=0, stdout=_complete_runtime_secret_payload())
        if command[:5] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "get", "helmrelease"]:
            return CommandResult(
                command=list(command),
                returncode=0,
                stdout=json.dumps(
                    {
                        "status": {
                            "conditions": [
                                {
                                    "type": "Ready",
                                    "status": "False",
                                    "reason": "UpgradeFailed",
                                    "message": "context deadline exceeded",
                                }
                            ]
                        }
                    }
                ),
            )
        if "jsonpath={.spec.template.spec.containers[0].image}" in " ".join(command):
            return CommandResult(command=list(command), returncode=0, stdout="repo:sha-abc123456789")
        if "schema_migration" in " ".join(command):
            return CommandResult(
                command=list(command),
                returncode=0,
                stdout=json.dumps({"schema_migration": ["001_initial.sql"], "expected_migrations": ["001_initial.sql"], "missing": []}),
            )
        return CommandResult(command=list(command), returncode=0, stdout="ok")

    report = run_dev_release_gate(
        DevReleaseGateConfig(
            commit_sha="abc1234567890000",
            image_tag="sha-abc123456789",
            output=tmp_path / "release-gate.md",
            run_live_eval=False,
        ),
        command_runner=runner,
        http_get=lambda url, timeout: (200, {"status": "ok"}),
    )

    assert report.passed is True
    reset_commands = [
        command
        for command in commands
        if command[:4] == ["kubectl", "-n", "ecommerce-cs-agent-dev", "annotate"]
        and "helmrelease/ecommerce-cs-agent" in command
        and any(item.startswith("reconcile.fluxcd.io/resetAt=") for item in command)
        and any(item.startswith("reconcile.fluxcd.io/requestedAt=") for item in command)
    ]
    assert len(reset_commands) == 1
    assert any(
        check.name == "helm release reset"
        and check.passed
        and "UpgradeFailed" in check.details
        for check in report.checks
    )
