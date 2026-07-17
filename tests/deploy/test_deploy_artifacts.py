import json
import subprocess
import tomllib
from pathlib import Path

import yaml


def _render_helm(*arguments: str, expect_success: bool = True) -> str:
    result = subprocess.run(
        ["helm", "template", "ecs", "deploy/helm/ecommerce-cs-agent", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if expect_success:
        assert result.returncode == 0, result.stderr
        return result.stdout
    assert result.returncode != 0
    return result.stderr


def test_api_and_admin_dockerfiles_exist() -> None:
    api = Path("Dockerfile.api").read_text(encoding="utf-8")
    admin = Path("admin-web/Dockerfile").read_text(encoding="utf-8")

    assert "ecommerce_cs_agent.api.app:app" in api
    assert "python -m ecommerce_cs_agent.db.cli migrate" not in api
    assert "COPY --chown=app:app migrations ./migrations" in api
    assert "USER 10001:10001" in api
    assert '"anyio>=4,<5"' in api
    assert '"cryptography>=45,<47"' in api
    assert "npm run build" in admin
    assert "nginxinc/nginx-unprivileged" in admin


def test_admin_web_is_vite_react_app() -> None:
    package = yaml.safe_load(Path("admin-web/package.json").read_text(encoding="utf-8"))
    customer_app = Path("admin-web/customer-admin/src/App.tsx").read_text(encoding="utf-8")
    system_app = Path("admin-web/system-admin/src/App.tsx").read_text(encoding="utf-8")
    system_api = Path("admin-web/system-admin/src/system-api.ts").read_text(encoding="utf-8")
    shared_api = Path("admin-web/shared/api.ts").read_text(encoding="utf-8")
    nginx = Path("admin-web/nginx.conf").read_text(encoding="utf-8")

    assert package["scripts"]["build"] == "npm run build:customer && npm run build:system"
    assert package["scripts"]["build:customer"] == "vite build --mode customer"
    assert package["scripts"]["build:system"] == "vite build --mode system"
    assert "客户后台" in customer_app
    assert "系统后台" in system_app
    assert "fetch(" in shared_api
    assert "/v1/admin/auth/login" in customer_app
    assert "/v1/system-admin/message-traces" in system_api
    assert "password: \"admin-password\"" not in customer_app
    assert "password: \"admin-password\"" not in system_app
    assert "proxy_pass http://ecommerce-cs-agent-api:8000" in nginx


def test_admin_web_splits_customer_and_system_sites_by_host() -> None:
    customer_app = Path("admin-web/customer-admin/src/App.tsx").read_text(encoding="utf-8")
    system_app = Path("admin-web/system-admin/src/App.tsx").read_text(encoding="utf-8")
    system_api = Path("admin-web/system-admin/src/system-api.ts").read_text(encoding="utf-8")
    system_workspace = Path("admin-web/system-admin/src/SystemWorkspace.tsx").read_text(encoding="utf-8")
    shared = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            Path("admin-web/shared/api.ts"),
            Path("admin-web/shared/components.tsx"),
            Path("admin-web/shared/data.tsx"),
        ]
    )
    nginx = Path("admin-web/nginx.conf").read_text(encoding="utf-8")
    all_sources = "\n".join([customer_app, system_app, shared])

    assert Path("admin-web/customer-admin/index.html").exists()
    assert Path("admin-web/system-admin/index.html").exists()
    assert Path("admin-web/src/main.tsx").exists() is False
    assert "detectWorkspaceFromLocation" not in all_sources
    assert 'workspace === "system"' not in all_sources
    assert 'workspace === "customer"' not in all_sources
    assert "workspaceSwitch" not in all_sources
    assert "setWorkspace" not in all_sources
    assert "/v1/admin/auth/me" in customer_app
    assert "/v1/system-admin" not in customer_app
    assert "/v1/system-admin/auth/me" in system_api
    assert "/v1/admin/auth/me" not in system_api
    assert "function CustomerAdminShell(" in customer_app
    assert "function SystemWorkspace(" in system_workspace
    assert "system-admin.ecommerce-cs-agent-dev.fcihome.com system;" in nginx
    assert "default customer;" in nginx
    assert "try_files /$admin_site$uri =404;" in nginx


def test_helm_values_define_dev_runtime_contract() -> None:
    values = yaml.safe_load(
        Path("deploy/helm/ecommerce-cs-agent/values-dev.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert values["imagePullSecrets"][0]["name"] == "aliyun-registry-auth"
    assert values["imagePullSecrets"][1]["name"] == "ghcr-auth"
    assert values["api"]["image"]["repository"] == (
        "registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-api"
    )
    assert values["api"]["envFromSecret"] == "ecommerce-cs-agent-runtime"
    assert values["api"]["replicas"] == 2
    assert values["api"]["decisionMaxConcurrency"] == 4
    assert values["api"]["ingress"]["host"] == (
        "api.ecommerce-cs-agent-dev.fcihome.com"
    )
    assert values["admin"]["image"]["repository"] == (
        "registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-admin"
    )
    assert values["admin"]["customer"]["host"] == (
        "admin.ecommerce-cs-agent-dev.fcihome.com"
    )
    assert values["admin"]["system"]["host"] == (
        "system-admin.ecommerce-cs-agent-dev.fcihome.com"
    )
    assert values["admin"]["ingress"]["tlsSecretName"] == "cs-agent-dev-tls"
    assert values["proxy"]["enabled"] is True


def test_helm_renders_bounded_decision_execution_and_resilient_api_probes() -> None:
    chart_dir = Path("deploy/helm/ecommerce-cs-agent")
    values = yaml.safe_load((chart_dir / "values.yaml").read_text(encoding="utf-8"))
    schema = json.loads((chart_dir / "values.schema.json").read_text(encoding="utf-8"))

    assert values["api"]["decisionMaxConcurrency"] == 4
    assert schema["properties"]["api"]["properties"]["decisionMaxConcurrency"] == {
        "type": "integer",
        "minimum": 1,
    }

    rendered = _render_helm("-f", "deploy/helm/ecommerce-cs-agent/values-dev.yaml")
    documents = [document for document in yaml.safe_load_all(rendered) if document]
    deployment = next(
        document
        for document in documents
        if document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-api")
    )
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    env = {item["name"]: item for item in container["env"]}

    assert deployment["spec"]["replicas"] == 2
    assert env["DECISION_MAX_CONCURRENCY"] == {
        "name": "DECISION_MAX_CONCURRENCY",
        "value": "4",
    }
    assert container["startupProbe"] == {
        "httpGet": {"path": "/health", "port": "http"},
        "periodSeconds": 2,
        "failureThreshold": 30,
    }
    assert container["readinessProbe"] == {
        "httpGet": {"path": "/health", "port": "http"},
        "timeoutSeconds": 2,
        "periodSeconds": 5,
        "failureThreshold": 3,
    }
    assert container["livenessProbe"] == {
        "httpGet": {"path": "/health", "port": "http"},
        "timeoutSeconds": 2,
        "periodSeconds": 10,
        "failureThreshold": 6,
    }


def test_helm_api_uses_dedicated_service_account_and_secret_allowlist() -> None:
    chart_dir = Path("deploy/helm/ecommerce-cs-agent")
    values = yaml.safe_load((chart_dir / "values.yaml").read_text(encoding="utf-8"))
    api = values["api"]

    assert api["serviceAccount"] == {"create": True, "name": "", "automount": True}
    assert api["secretAccess"]["enabled"] is True
    assert api["secretAccess"]["allowedSecretRefs"] == [
        {
            "name": "ecommerce-cs-agent-llm-provider",
            "keys": [{"key": "api-key", "allowedOrigins": []}],
        }
    ]
    assert api["runtimeLlmSecretRef"] == {
        "name": "ecommerce-cs-agent-llm-provider",
        "key": "api-key",
    }
    assert api["cursorSigningSecretRef"] == {
        "name": "ecommerce-cs-agent-llm-cursor",
        "key": "signing-key",
    }
    schema = json.loads((chart_dir / "values.schema.json").read_text(encoding="utf-8"))
    cursor_schema = schema["properties"]["api"]["properties"]["cursorSigningSecretRef"]
    assert cursor_schema["required"] == ["name", "key"]
    assert cursor_schema["properties"]["name"]["pattern"] == (
        r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?"
        r"(?:\.[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?)*$"
    )
    assert cursor_schema["properties"]["key"]["pattern"] == r"^[A-Za-z0-9._-]+$"
    runtime_schema = schema["properties"]["api"]["properties"]["runtimeLlmSecretRef"]
    allowed_schema = schema["properties"]["api"]["properties"]["secretAccess"]["properties"]["allowedSecretRefs"]["items"]
    assert runtime_schema["properties"]["name"]["pattern"] == cursor_schema["properties"]["name"]["pattern"]
    assert allowed_schema["properties"]["name"]["pattern"] == cursor_schema["properties"]["name"]["pattern"]
    assert runtime_schema["properties"]["key"]["pattern"] == cursor_schema["properties"]["key"]["pattern"]
    assert allowed_schema["properties"]["keys"]["items"]["properties"]["key"]["pattern"] == cursor_schema["properties"]["key"]["pattern"]
    assert api["secretAccess"]["allowedSecretRefs"][0]["name"] != api["envFromSecret"]

    deployment = (chart_dir / "templates/api-deployment.yaml").read_text(encoding="utf-8")
    service_account = (chart_dir / "templates/api-service-account.yaml").read_text(encoding="utf-8")
    rbac = (chart_dir / "templates/api-secret-rbac.yaml").read_text(encoding="utf-8")
    all_rbac = "\n".join([service_account, rbac])

    assert "serviceAccountName:" in deployment
    assert "automountServiceAccountToken:" in deployment
    assert "LLM_GOVERNANCE_SECRET_NAMESPACE" in deployment
    assert "fieldPath: metadata.namespace" in deployment
    assert "LLM_GOVERNANCE_ALLOWED_SECRET_REFS" in deployment
    assert "LLM_CURSOR_SIGNING_KEY" in deployment
    assert "kind: ServiceAccount" in service_account
    assert "kind: Role" in rbac
    assert "kind: RoleBinding" in rbac
    assert "resources: [\"secrets\"]" in rbac
    assert "verbs: [\"get\"]" in rbac
    assert "resourceNames:" in rbac
    assert "ClusterRole" not in all_rbac
    assert 'verbs: ["list"]' not in all_rbac
    assert 'verbs: ["watch"]' not in all_rbac
    assert "fail \"api.secretAccess.allowedSecretRefs must not be empty\"" in rbac


def test_helm_rendered_secret_access_is_dedicated_and_key_scoped() -> None:
    rendered = _render_helm()
    documents = [document for document in yaml.safe_load_all(rendered) if document]
    role = next(document for document in documents if document.get("kind") == "Role")
    deployment = next(
        document
        for document in documents
        if document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-api")
    )

    assert role["rules"] == [
        {
            "apiGroups": [""],
            "resources": ["secrets"],
            "resourceNames": ["ecommerce-cs-agent-llm-provider"],
            "verbs": ["get"],
        }
    ]
    env = {item["name"]: item for item in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}
    refs = json.loads(env["LLM_GOVERNANCE_ALLOWED_SECRET_REFS"]["value"])
    assert refs == [
        {
            "name": "ecommerce-cs-agent-llm-provider",
            "keys": [{"key": "api-key", "allowedOrigins": []}],
        }
    ]
    assert json.loads(env["LLM_GOVERNANCE_RUNTIME_LLM_SECRET_REF"]["value"]) == {
        "name": "ecommerce-cs-agent-llm-provider",
        "key": "api-key",
    }
    assert env["LLM_API_KEY"] == {
        "name": "LLM_API_KEY",
        "valueFrom": {
            "secretKeyRef": {
                "name": "ecommerce-cs-agent-llm-provider",
                "key": "api-key",
            }
        },
    }
    assert env["LLM_CURSOR_SIGNING_KEY"] == {
        "name": "LLM_CURSOR_SIGNING_KEY",
        "valueFrom": {
            "secretKeyRef": {
                "name": "ecommerce-cs-agent-llm-cursor",
                "key": "signing-key",
            }
        },
    }
    env_from = deployment["spec"]["template"]["spec"]["containers"][0]["envFrom"]
    assert env_from == [{"secretRef": {"name": "ecommerce-cs-agent-runtime"}}]
    serialized = json.dumps(refs)
    assert "ecommerce-cs-agent-runtime" not in serialized
    for forbidden_key in ("DATABASE_URL", "JWT_SECRET", "SESSION_SECRET"):
        assert forbidden_key not in serialized


def test_helm_rejects_empty_or_runtime_secret_access_refs() -> None:
    empty_refs = _render_helm(
        "--set-json", "api.secretAccess.allowedSecretRefs=[]", expect_success=False
    )
    empty_keys = _render_helm(
        "--set-json",
        'api.secretAccess.allowedSecretRefs=[{"name":"ecommerce-cs-agent-llm-provider","keys":[]}]',
        expect_success=False,
    )
    runtime_ref = _render_helm(
        "--set-json",
        'api.secretAccess.allowedSecretRefs=[{"name":"ecommerce-cs-agent-runtime","keys":[{"key":"DATABASE_URL","allowedOrigins":["https://models.example"]}]}]',
        expect_success=False,
    )
    non_list_keys = _render_helm(
        "--set-json",
        'api.secretAccess.allowedSecretRefs=[{"name":"ecommerce-cs-agent-llm-provider","keys":"api-key"}]',
        expect_success=False,
    )
    invalid_name = _render_helm(
        "--set-json",
        'api.secretAccess.allowedSecretRefs=[{"name":"Invalid_Name","keys":["api-key"]}]',
        expect_success=False,
    )
    invalid_key = _render_helm(
        "--set-json",
        'api.secretAccess.allowedSecretRefs=[{"name":"ecommerce-cs-agent-llm-provider","keys":[{"key":"bad/key","allowedOrigins":[]}]}]',
        expect_success=False,
    )

    assert "allowedSecretRefs must not be empty" in empty_refs or "minItems" in empty_refs
    assert "keys must not be empty" in empty_keys or "minItems" in empty_keys
    assert "must not include api.envFromSecret" in runtime_ref
    assert "keys must be a non-empty list" in non_list_keys or "want array" in non_list_keys
    assert ".name is invalid" in invalid_name or "allowedSecretRefs/0/name" in invalid_name
    assert ".keys[0].key is invalid" in invalid_key or "allowedSecretRefs/0/keys/0/key" in invalid_key


def test_helm_rejects_missing_or_invalid_origins_for_non_runtime_secret_keys() -> None:
    empty_extra_origins = _render_helm(
        "--set-json",
        'api.secretAccess.allowedSecretRefs=[{"name":"ecommerce-cs-agent-llm-provider","keys":[{"key":"api-key","allowedOrigins":[]}]},{"name":"other-provider","keys":[{"key":"api-key","allowedOrigins":[]}]}]',
        expect_success=False,
    )
    invalid_origin = _render_helm(
        "--set-json",
        'api.secretAccess.allowedSecretRefs=[{"name":"ecommerce-cs-agent-llm-provider","keys":[{"key":"api-key","allowedOrigins":[]}]},{"name":"other-provider","keys":[{"key":"api-key","allowedOrigins":["http://internal.example"]}]}]',
        expect_success=False,
    )

    assert "non-runtime keys require allowedOrigins" in empty_extra_origins
    assert "allowedOrigins[0] is invalid" in invalid_origin


def test_helm_rejects_runtime_llm_ref_outside_dedicated_allowlist() -> None:
    runtime_secret = _render_helm(
        "--set", "api.runtimeLlmSecretRef.name=ecommerce-cs-agent-runtime", expect_success=False
    )
    missing_tuple = _render_helm(
        "--set", "api.runtimeLlmSecretRef.key=other-key", expect_success=False
    )

    assert "runtimeLlmSecretRef must not use api.envFromSecret" in runtime_secret
    assert "runtimeLlmSecretRef tuple must exactly match one allowedSecretRefs entry" in missing_tuple


def test_helm_uses_strict_dns_subdomain_names_for_runtime_and_every_allowed_secret() -> None:
    invalid_names = ("a..b", "a" * 64, "a." * 127 + "a", ".a", "a.", "-a", "a-", "Upper")
    for name in invalid_names:
        runtime = _render_helm("--set-string", f"api.runtimeLlmSecretRef.name={name}", expect_success=False)
        allowed = _render_helm(
            "--set-json",
            f'api.secretAccess.allowedSecretRefs=[{{"name":"ecommerce-cs-agent-llm-provider","keys":[{{"key":"api-key"}}]}},{{"name":"{name}","keys":[{{"key":"token","allowedOrigins":["https://models.example"]}}]}}]',
            expect_success=False,
        )
        assert "runtimeLlmSecretRef/name" in runtime or "runtimeLlmSecretRef.name is invalid" in runtime
        assert "allowedSecretRefs" in allowed and ("name" in allowed or ".name is invalid" in allowed)

    rendered = _render_helm(
        "--set-string", "api.runtimeLlmSecretRef.name=runtime.provider-secrets",
        "--set-string", "api.runtimeLlmSecretRef.key=api_key.v1",
        "--set-json", 'api.secretAccess.allowedSecretRefs=[{"name":"runtime.provider-secrets","keys":[{"key":"api_key.v1"}]},{"name":"other.provider-secrets","keys":[{"key":"token-1","allowedOrigins":["https://models.example"]}]}]',
    )
    assert "runtime.provider-secrets" in rendered
    assert "other.provider-secrets" in rendered


def test_helm_rejects_duplicate_secret_tuples_and_runtime_attacker_origins() -> None:
    duplicate = _render_helm(
        "--set-json",
        'api.secretAccess.allowedSecretRefs=[{"name":"ecommerce-cs-agent-llm-provider","keys":[{"key":"api-key"},{"key":"api-key"}]}]',
        expect_success=False,
    )
    attacker_origin = _render_helm(
        "--set-json",
        'api.secretAccess.allowedSecretRefs=[{"name":"ecommerce-cs-agent-llm-provider","keys":[{"key":"api-key","allowedOrigins":["https://attacker.example"]}]}]',
        expect_success=False,
    )

    assert "duplicate Secret name/key tuple" in duplicate
    assert "runtime LLM Secret tuple must not declare allowedOrigins" in attacker_origin


def test_helm_rejects_invalid_or_provider_reused_cursor_signing_secret_ref() -> None:
    invalid_names = {
        value: _render_helm(
            "--set-string", f"api.cursorSigningSecretRef.name={value}", expect_success=False
        )
        for value in ("a..b", ".a", "a.", "-a", "a-", "Invalid_Name", "")
    }
    invalid_key = _render_helm("--set-string", "api.cursorSigningSecretRef.key=bad/key", expect_success=False)
    provider_reuse = _render_helm(
        "--set", "api.cursorSigningSecretRef.name=ecommerce-cs-agent-llm-provider",
        "--set", "api.cursorSigningSecretRef.key=api-key",
        expect_success=False,
    )
    second_provider_reuse = _render_helm(
        "--set-json",
        'api.secretAccess.allowedSecretRefs=[{"name":"ecommerce-cs-agent-llm-provider","keys":[{"key":"api-key","allowedOrigins":[]}]},{"name":"second-provider","keys":[{"key":"token","allowedOrigins":["https://models.example"]}]}]',
        "--set", "api.cursorSigningSecretRef.name=second-provider",
        "--set", "api.cursorSigningSecretRef.key=cursor-key",
        expect_success=False,
    )

    for output in invalid_names.values():
        assert "/api/cursorSigningSecretRef/name" in output
    assert "/api/cursorSigningSecretRef/key" in invalid_key
    assert "cursorSigningSecretRef must be separate from runtimeLlmSecretRef" in provider_reuse
    assert "cursorSigningSecretRef must be separate from every allowed provider Secret" in second_provider_reuse


def test_helm_accepts_legal_cursor_signing_secret_subdomain_and_key() -> None:
    rendered = _render_helm(
        "--set", "api.cursorSigningSecretRef.name=cursor-signing.security-agent",
        "--set", "api.cursorSigningSecretRef.key=signing_key.v1",
    )

    assert "cursor-signing.security-agent" in rendered
    assert "signing_key.v1" in rendered


def test_api_deployment_is_stateless_and_uses_shared_external_state() -> None:
    rendered = _render_helm()
    documents = [document for document in yaml.safe_load_all(rendered) if document]
    deployment = next(
        document
        for document in documents
        if document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-api")
    )
    pod_spec = deployment["spec"]["template"]["spec"]
    serialized = json.dumps(deployment)

    assert "hostPath" not in serialized
    assert "PersistentVolumeClaim" not in serialized
    assert not pod_spec.get("volumes")
    assert pod_spec["containers"][0]["envFrom"] == [
        {"secretRef": {"name": "ecommerce-cs-agent-runtime"}}
    ]


def test_helm_external_service_account_keeps_dedicated_llm_secret_injection() -> None:
    rendered = _render_helm(
        "--set", "api.serviceAccount.create=false", "--set", "api.serviceAccount.name=external-api"
    )
    documents = [document for document in yaml.safe_load_all(rendered) if document]
    deployment = next(
        document
        for document in documents
        if document.get("kind") == "Deployment" and document["metadata"]["name"].endswith("-api")
    )
    env = {item["name"]: item for item in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}

    assert deployment["spec"]["template"]["spec"]["serviceAccountName"] == "external-api"
    assert env["LLM_API_KEY"]["valueFrom"]["secretKeyRef"] == {
        "name": "ecommerce-cs-agent-llm-provider",
        "key": "api-key",
    }


def test_deployment_docs_separate_llm_credentials_from_runtime_secret() -> None:
    deployment = Path("docs/deployment.md").read_text(encoding="utf-8")
    runbook = Path("docs/runbook.md").read_text(encoding="utf-8")

    assert "模型凭据 Secret：`ecommerce-cs-agent-llm-provider`" in deployment
    assert "禁止复用 `ecommerce-cs-agent-runtime`" in deployment
    runtime_section = deployment.split("运行时 Secret：`ecommerce-cs-agent-runtime`", 1)[1].split(
        "模型凭据 Secret：", 1
    )[0]
    assert "`LLM_API_KEY`" not in runtime_section
    assert "LLM_API_KEY` 通过 `secretKeyRef`" in deployment
    assert "ecommerce-cs-agent-llm-provider" in runbook
    assert "runtimeLlmSecretRef" in runbook


def test_dev_dependencies_include_draft_2020_json_schema_validator() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "jsonschema[format]>=4.23,<5" in project["project"]["optional-dependencies"]["dev"]


def test_helm_chart_defines_k8s_security_defaults() -> None:
    values = yaml.safe_load(
        Path("deploy/helm/ecommerce-cs-agent/values.yaml").read_text(
            encoding="utf-8"
        )
    )

    for component in ("api", "admin", "migration"):
        assert values[component]["podSecurityContext"]["runAsNonRoot"] is True
        assert (
            values[component]["podSecurityContext"]["seccompProfile"]["type"]
            == "RuntimeDefault"
        )
        assert values[component]["securityContext"]["allowPrivilegeEscalation"] is False
        assert values[component]["securityContext"]["readOnlyRootFilesystem"] is True
        assert "ALL" in values[component]["securityContext"]["capabilities"]["drop"]
        assert values[component]["resources"]["requests"]["cpu"]
        assert values[component]["resources"]["requests"]["memory"]
        assert values[component]["resources"]["limits"]["cpu"]
        assert values[component]["resources"]["limits"]["memory"]

    assert values["api"]["image"]["tag"] != "latest"
    assert values["admin"]["image"]["tag"] != "latest"
    assert values["admin"]["tmpVolume"]["enabled"] is True


def test_helm_templates_include_api_admin_and_migration_job() -> None:
    chart_dir = Path("deploy/helm/ecommerce-cs-agent")
    admin_ingress = (chart_dir / "templates/admin-ingress.yaml").read_text(encoding="utf-8")

    assert (chart_dir / "Chart.yaml").exists()
    assert (chart_dir / "templates/api-deployment.yaml").exists()
    assert (chart_dir / "templates/api-service.yaml").exists()
    assert (chart_dir / "templates/api-ingress.yaml").exists()
    assert (chart_dir / "templates/admin-deployment.yaml").exists()
    assert (chart_dir / "templates/admin-service.yaml").exists()
    assert (chart_dir / "templates/admin-ingress.yaml").exists()
    assert (chart_dir / "templates/migration-job.yaml").exists()
    assert "python\", \"-m\", \"ecommerce_cs_agent.db.cli\", \"migrate" in (
        chart_dir / "templates/migration-job.yaml"
    ).read_text(encoding="utf-8")
    assert 'acme.cert-manager.io/http01-edit-in-place: "true"' in admin_ingress
    assert ".Values.api.ingress.host" in admin_ingress
    assert ".Values.admin.customer.host" in admin_ingress
    assert ".Values.admin.system.host" in admin_ingress
    assert admin_ingress.count("- host:") == 2
    assert admin_ingress.count(".Values.admin.ingress.tlsSecretName") == 1
    assert 'replace "+" "_"' in (chart_dir / "templates/_helpers.tpl").read_text(
        encoding="utf-8"
    )


def test_ci_runs_with_pgvector_postgres_service() -> None:
    pr_checks = Path(".github/workflows/pr-checks.yml").read_text(encoding="utf-8")
    publish = Path(".github/workflows/publish-images.yml").read_text(encoding="utf-8")

    for workflow in (pr_checks, publish):
        assert "pgvector/pgvector:pg16" in workflow
        assert "PG_DSN" in workflow
        assert 'DATABASE_URL="$PG_DSN"' in workflow
        pytest_commands = [
            line.strip()
            for line in workflow.splitlines()
            if line.strip().startswith("run:") and "pytest" in line
        ]
        assert len(pytest_commands) == 1
        assert 'APP_ENV=test' in pytest_commands[0]
        assert 'DATABASE_URL="$PG_DSN"' in pytest_commands[0]
        assert 'TEST_DATABASE_URL="$PG_DSN"' in pytest_commands[0]
        assert "python -m ecommerce_cs_agent.db.cli migrate" in workflow
        assert "python scripts/check_k8s_security.py" in workflow


def test_publish_workflow_generates_sbom_and_scans_images() -> None:
    publish = Path(".github/workflows/publish-images.yml").read_text(encoding="utf-8")

    for snippet in [
        "security-events: write",
        "sbom: true",
        "provenance: mode=max",
        "aquasecurity/trivy-action@v0.36.0",
        "github/codeql-action/upload-sarif@v4",
        "trivy-${{ matrix.component }}.sarif",
        "format: cyclonedx",
        "sbom-${{ matrix.component }}.cdx.json",
        "actions/upload-artifact@v7",
        "Enforce image vulnerability gate",
        "severity: CRITICAL",
        'exit-code: "1"',
    ]:
        assert snippet in publish


def test_ci_validates_built_admin_nginx_image_before_publish() -> None:
    pr_checks = Path(".github/workflows/pr-checks.yml").read_text(encoding="utf-8")
    publish = Path(".github/workflows/publish-images.yml").read_text(encoding="utf-8")

    for workflow in (pr_checks, publish):
        assert "Admin image nginx config check" in workflow
        assert "docker build -f admin-web/Dockerfile" in workflow
        assert "docker run --rm --add-host ecommerce-cs-agent-api:127.0.0.1 ecommerce-cs-agent-admin:nginx-check nginx -t" in workflow


def test_deploy_workflow_archives_dev_release_gate_report() -> None:
    workflow = Path(".github/workflows/deploy-dev.yml").read_text(encoding="utf-8")

    for snippet in [
        "Verify Dev Release Gate",
        "HEAD_SHA_INPUT: ${{ inputs.head_sha }}",
        "WORKFLOW_RUN_HEAD_SHA: ${{ github.event.workflow_run.head_sha }}",
        "head_sha=\"$HEAD_SHA_INPUT\"",
        "Initialize release gate report",
        "python scripts/run_dev_release_gate.py",
        "--image-tag \"${{ needs.update-gitops.outputs.image_tag }}\"",
        "actions/upload-artifact@v7",
        "dev-release-gate-${{ needs.update-gitops.outputs.image_tag }}",
    ]:
        assert snippet in workflow
    assert 'head_sha="${{ inputs.head_sha }}"' not in workflow
    assert workflow.count("KUBECONFIG_CONTENT: ${{ secrets.KUBECONFIG }}") == 1


def test_codeql_gate_counts_security_results_not_quality_findings() -> None:
    workflow = Path(".github/workflows/codeql.yml").read_text(encoding="utf-8")

    assert 'index("security")' in workflow
    assert "security_alert_count" in workflow
    assert "[.runs[].results[]?] | length" not in workflow


def test_api_image_installs_decision_graph_runtime_dependency() -> None:
    dockerfile = Path("Dockerfile.api").read_text(encoding="utf-8")

    assert '"langgraph>=1.2,<2"' in dockerfile


def test_k8s_security_check_script_is_available() -> None:
    script = Path("scripts/check_k8s_security.py").read_text(encoding="utf-8")

    for snippet in [
        "helm",
        "securityContext.runAsNonRoot",
        "readOnlyRootFilesystem",
        "allowPrivilegeEscalation",
        "capabilities.drop",
        "resources.",
        "readinessProbe",
        ":latest",
    ]:
        assert snippet in script
