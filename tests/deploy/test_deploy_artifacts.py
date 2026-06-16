from pathlib import Path

import yaml


def test_api_and_admin_dockerfiles_exist() -> None:
    api = Path("Dockerfile.api").read_text(encoding="utf-8")
    admin = Path("admin-web/Dockerfile").read_text(encoding="utf-8")

    assert "ecommerce_cs_agent.api.app:app" in api
    assert "python -m ecommerce_cs_agent.db.cli migrate" in api
    assert "nginx" in admin


def test_helm_values_define_dev_runtime_contract() -> None:
    values = yaml.safe_load(
        Path("deploy/helm/ecommerce-cs-agent/values-dev.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert values["imagePullSecrets"][0]["name"] == "ghcr-auth"
    assert values["api"]["image"]["repository"] == (
        "ghcr.io/liuyenhui/ecommerce-cs-agent-api"
    )
    assert values["api"]["envFromSecret"] == "ecommerce-cs-agent-runtime"
    assert values["api"]["ingress"]["host"] == (
        "api.ecommerce-cs-agent-dev.fcihome.com"
    )
    assert values["admin"]["image"]["repository"] == (
        "ghcr.io/liuyenhui/ecommerce-cs-agent-admin"
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
