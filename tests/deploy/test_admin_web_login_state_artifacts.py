import json
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATHS = (
    ROOT / ".github" / "workflows" / "pr-checks.yml",
    ROOT / ".github" / "workflows" / "publish-images.yml",
)


def test_root_package_declares_deterministic_admin_credential_tests():
    package = json.loads((ROOT / "package.json").read_text())

    assert (
        package["scripts"]["test:admin-credentials"]
        == "node --test scripts/admin_web_credentials.test.mjs"
    )


def test_admin_credential_sources_keep_the_local_security_boundary():
    helper_source = (ROOT / "scripts" / "admin_web_credentials.mjs").read_text()
    login_source = (ROOT / "scripts" / "admin_web_login_state.mjs").read_text()

    assert '".config"' in helper_source
    assert '"ecommerce-cs-agent"' in helper_source
    assert '"admin-test-credentials.env"' in helper_source
    assert "0o700" in helper_source
    assert "0o600" in helper_source
    assert "symbolic link" in helper_source
    assert "outside the repository" in helper_source
    assert "O_NOFOLLOW" in helper_source
    assert "fstatSync" in helper_source

    main_source = login_source.split("async function main()", maxsplit=1)[1]
    for variable in (
        "credentials",
        "fileCredentials",
        "customerPassword",
        "systemPassword",
    ):
        assert (
            re.search(
                rf"console\.log\s*\([^;]*\b{variable}\b",
                main_source,
                re.DOTALL,
            )
            is None
        )
    for response_body_pattern in (
        r"console\.log\s*\(\s*(?:response|body|me)\b",
        r"response(?:Body|Summary)",
        r"bodySummary",
        r"response\.text\s*\(",
    ):
        assert re.search(response_body_pattern, login_source) is None

    assert "/v1/admin/auth/me" in login_source
    assert "/v1/system-admin/auth/me" in login_source
    assert "agent_admin_session" in login_source
    assert "agent_system_admin_session" in login_source


def test_root_admin_credential_file_is_neither_present_nor_tracked():
    credential_file = ROOT / "admin-test-credentials.env"
    tracked_files = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert not credential_file.exists()
    assert "admin-test-credentials.env" not in tracked_files


def test_admin_credentials_are_excluded_from_image_and_helm_artifacts():
    artifact_paths = [
        ROOT / "Dockerfile.api",
        ROOT / "admin-web" / "Dockerfile",
        *(
            path
            for path in (ROOT / "deploy" / "helm" / "ecommerce-cs-agent").rglob("*")
            if path.is_file()
        ),
    ]

    references = [
        str(path.relative_to(ROOT))
        for path in artifact_paths
        if "admin-test-credentials.env" in path.read_text()
    ]
    assert references == []


@pytest.mark.parametrize("workflow_path", WORKFLOW_PATHS)
def test_ci_workflows_run_deterministic_admin_credential_tests(workflow_path):
    workflow = workflow_path.read_text()

    assert "Admin credential helper tests" in workflow, workflow_path
    assert "npm run test:admin-credentials" in workflow, workflow_path
