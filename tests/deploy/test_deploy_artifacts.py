from pathlib import Path

import yaml


def test_api_and_admin_dockerfiles_exist() -> None:
    api = Path("Dockerfile.api").read_text(encoding="utf-8")
    admin = Path("admin-web/Dockerfile").read_text(encoding="utf-8")

    assert "ecommerce_cs_agent.api.app:app" in api
    assert "python -m ecommerce_cs_agent.db.cli migrate" not in api
    assert "COPY --chown=app:app migrations ./migrations" in api
    assert "USER 10001:10001" in api
    assert "npm run build" in admin
    assert "nginxinc/nginx-unprivileged" in admin


def test_admin_web_is_vite_react_app() -> None:
    package = yaml.safe_load(Path("admin-web/package.json").read_text(encoding="utf-8"))
    app = Path("admin-web/src/main.tsx").read_text(encoding="utf-8")
    nginx = Path("admin-web/nginx.conf").read_text(encoding="utf-8")

    assert package["scripts"]["build"] == "vite build"
    assert "客户后台" in app
    assert "系统后台" in app
    assert "fetch(" in app
    assert "/v1/admin/auth/login" in app
    assert "/v1/system-admin/message-traces" in app
    assert "password: \"admin-password\"" not in app
    assert "proxy_pass http://ecommerce-cs-agent-api:8000" in nginx


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
    assert values["api"]["ingress"]["host"] == (
        "api.ecommerce-cs-agent-dev.fcihome.com"
    )
    assert values["admin"]["image"]["repository"] == (
        "registry.cn-beijing.aliyuncs.com/threepeople/ecommerce-cs-agent-admin"
    )
    assert values["admin"]["ingress"]["host"] == (
        "admin.ecommerce-cs-agent-dev.fcihome.com"
    )
    assert values["proxy"]["enabled"] is True


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
        "actions/upload-artifact@v4",
        "Enforce image vulnerability gate",
        "severity: CRITICAL",
        'exit-code: "1"',
    ]:
        assert snippet in publish


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
        "actions/upload-artifact@v4",
        "dev-release-gate-${{ needs.update-gitops.outputs.image_tag }}",
    ]:
        assert snippet in workflow
    assert 'head_sha="${{ inputs.head_sha }}"' not in workflow
    assert workflow.count("KUBECONFIG_CONTENT: ${{ secrets.KUBECONFIG }}") == 1


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
