import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_local_acs_profile_scripts_are_declared():
    package_path = ROOT / "package.json"
    assert package_path.exists()
    package = json.loads(package_path.read_text())
    scripts = package["scripts"]

    assert scripts["dev:acs:env"] == "node scripts/acs_local_env.mjs"
    assert scripts["dev:acs:port-forward"] == "node scripts/acs_port_forward.mjs"
    assert "127.0.0.1 --port 8000" in scripts["dev:api:acs-local"]
    assert scripts["dev:admin:customer"] == "npm --prefix admin-web run dev:customer"

    admin_package = json.loads((ROOT / "admin-web" / "package.json").read_text())
    assert admin_package["scripts"]["dev:customer"] == "vite --mode customer --host 127.0.0.1 --port 5173"


def test_local_acs_env_script_uses_k3s_secret_without_printing_values():
    script = (ROOT / "scripts" / "acs_local_env.mjs").read_text()

    assert "ACS_DEV_NAMESPACE" in script
    assert "ecommerce-cs-agent-dev" in script
    assert "ecommerce-cs-agent-runtime" in script
    assert "DATABASE_URL" in script
    assert "OBJECT_STORAGE_ENDPOINT" in script
    assert "127.0.0.1" in script
    assert "15432" in script
    assert "19000" in script
    assert "0o600" in script
    assert "console.log(envText" not in script
    assert "console.log(decoded" not in script

    gitignore = (ROOT / ".gitignore").read_text()
    assert ".local/" in gitignore


def test_local_acs_port_forward_script_targets_dev_services():
    script = (ROOT / "scripts" / "acs_port_forward.mjs").read_text()

    assert "ACS_DEV_KUBECONFIG" in script
    assert "ecommerce-cs-agent-dev" in script
    assert "svc/postgres" in script
    assert "15432:5432" in script
    assert "svc/minio" in script
    assert "19000:9000" in script
