from pathlib import Path

import yaml


def test_api_and_admin_dockerfiles_exist() -> None:
    api = Path("Dockerfile.api").read_text(encoding="utf-8")
    admin = Path("admin-web/Dockerfile").read_text(encoding="utf-8")

    assert "ecommerce_cs_agent.api.app:app" in api
    assert "python -m ecommerce_cs_agent.db.cli migrate" not in api
    assert "COPY --chown=app:app migrations ./migrations" in api
    assert "npm run build" in admin
    assert "nginx" in admin


def test_admin_web_is_vite_react_app() -> None:
    package = yaml.safe_load(Path("admin-web/package.json").read_text(encoding="utf-8"))
    app = Path("admin-web/src/main.tsx").read_text(encoding="utf-8")

    assert package["scripts"]["build"] == "vite build"
    assert "客户后台" in app
    assert "系统后台" in app
    assert "fetch(" in app


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


def test_ci_runs_with_pgvector_postgres_service() -> None:
    pr_checks = Path(".github/workflows/pr-checks.yml").read_text(encoding="utf-8")
    publish = Path(".github/workflows/publish-images.yml").read_text(encoding="utf-8")

    for workflow in (pr_checks, publish):
        assert "pgvector/pgvector:pg16" in workflow
        assert "PG_DSN" in workflow
        assert 'DATABASE_URL="$PG_DSN"' in workflow
        assert "python -m ecommerce_cs_agent.db.cli migrate" in workflow


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
