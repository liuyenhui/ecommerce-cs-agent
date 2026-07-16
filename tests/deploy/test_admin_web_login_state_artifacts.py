import json
from pathlib import Path, PurePosixPath
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
ADMIN_CREDENTIAL_TEST_STEP = {
    "name": "Admin credential helper tests",
    "run": "npm run test:admin-credentials",
}
SENSITIVE_ARTIFACT_MARKERS = (
    "admin-test-credentials.env",
    "CUSTOMER_ADMIN_PASSWORD",
    "SYSTEM_ADMIN_PASSWORD",
    ".storageState.json",
    "ecommerce-admin-auth-",
)
SENSITIVE_IGNORE_PATTERNS = {
    "**/admin-test-credentials.env",
    "**/*.storageState.json",
    "**/ecommerce-admin-auth-*/",
}


def load_workflow(path):
    completed = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-rjson",
            "-e",
            "STDOUT.write(JSON.generate(YAML.load_file(ARGV.fetch(0))))",
            str(path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_root_package_declares_deterministic_admin_credential_tests():
    package = json.loads((ROOT / "package.json").read_text())

    assert (
        package["scripts"]["test:admin-credentials"]
        == "node --test scripts/admin_web_credentials.test.mjs"
    )


def test_admin_credential_behavior_suite_passes():
    completed = subprocess.run(
        ["npm", "run", "test:admin-credentials"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_ci_workflows_gate_admin_credentials_before_build_and_publish():
    workflow_jobs = (
        (
            load_workflow(ROOT / ".github" / "workflows" / "pr-checks.yml"),
            "checks",
        ),
        (
            load_workflow(ROOT / ".github" / "workflows" / "publish-images.yml"),
            "verify",
        ),
    )

    for workflow, job_name in workflow_jobs:
        steps = workflow["jobs"][job_name]["steps"]
        assert steps.count(ADMIN_CREDENTIAL_TEST_STEP) == 1

        setup_index = next(
            index
            for index, step in enumerate(steps)
            if str(step.get("uses", "")).startswith("actions/setup-node@")
        )
        helper_index = steps.index(ADMIN_CREDENTIAL_TEST_STEP)
        admin_install_or_build_indexes = {
            step_name: next(
                index
                for index, step in enumerate(steps)
                if step.get("name") == step_name
            )
            for step_name in (
                "Install Admin Web dependencies",
                "Admin Web production build",
            )
        }

        assert setup_index < helper_index
        assert all(
            helper_index < step_index
            for step_index in admin_install_or_build_indexes.values()
        )

    publish_workflow = load_workflow(
        ROOT / ".github" / "workflows" / "publish-images.yml"
    )
    publish_needs = publish_workflow["jobs"]["publish"]["needs"]
    if isinstance(publish_needs, str):
        publish_needs = [publish_needs]
    assert "verify" in publish_needs


@pytest.mark.parametrize(
    "ignore_path",
    (ROOT / ".gitignore", ROOT / ".dockerignore"),
)
def test_local_admin_credentials_and_states_are_ignored_recursively(ignore_path):
    configured_patterns = {
        line.strip()
        for line in ignore_path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert SENSITIVE_IGNORE_PATTERNS <= configured_patterns


def test_local_admin_credential_and_state_artifacts_are_not_tracked():
    credential_file = ROOT / "admin-test-credentials.env"
    tracked_files = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert not credential_file.exists()
    tracked_artifacts = []
    for tracked_file in tracked_files:
        path = PurePosixPath(tracked_file)
        if (
            path.name == "admin-test-credentials.env"
            or path.name.endswith(".storageState.json")
            or any(
                part.startswith("ecommerce-admin-auth-") for part in path.parts
            )
        ):
            tracked_artifacts.append(tracked_file)

    assert tracked_artifacts == []


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
        (str(path.relative_to(ROOT)), marker)
        for path in artifact_paths
        for marker in SENSITIVE_ARTIFACT_MARKERS
        if marker in path.read_text()
    ]
    assert references == []
