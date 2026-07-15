import base64
import json
import os
from pathlib import Path
import stat
import subprocess


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
    assert "ecommerce-cs-agent-llm-cursor" in script
    assert "signing-key" in script
    assert "LLM_CURSOR_SIGNING_KEY" in script
    assert "DATABASE_URL" in script
    assert "OBJECT_STORAGE_ENDPOINT" in script
    assert "127.0.0.1" in script
    assert "15432" in script
    assert "19000" in script
    assert "0o600" in script
    assert "console.log(envText" not in script
    assert "console.log(decoded" not in script
    assert "${namespace}/${secretName}" not in script

    gitignore = (ROOT / ".gitignore").read_text()
    assert ".local/" in gitignore


def test_local_acs_env_script_merges_cursor_secret_without_printing_values(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_kubectl = fake_bin / "kubectl"
    runtime_data = {
        "DATABASE_URL": base64.b64encode(
            b"postgresql://cs_agent:fake-password@postgres:5432/cs_agent"
        ).decode(),
    }
    cursor_value = "fake-local-cursor-signing-key-1234567890"
    cursor_data = {"signing-key": base64.b64encode(cursor_value.encode()).decode()}
    fake_kubectl.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        f"  *ecommerce-cs-agent-runtime*) printf '%s' '{json.dumps({'data': runtime_data})}' ;;\n"
        f"  *ecommerce-cs-agent-llm-cursor*) printf '%s' '{json.dumps({'data': cursor_data})}' ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n"
    )
    fake_kubectl.chmod(fake_kubectl.stat().st_mode | stat.S_IXUSR)
    output_file = tmp_path / "acs-runtime.env"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "ACS_LOCAL_ENV_FILE": str(output_file),
        "ACS_DEV_KUBECONFIG": str(tmp_path / "kubeconfig"),
    }

    completed = subprocess.run(
        ["node", str(ROOT / "scripts" / "acs_local_env.mjs")],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    env_text = output_file.read_text()
    assert "export LLM_CURSOR_SIGNING_KEY='fake-local-cursor-signing-key-1234567890'" in env_text
    assert cursor_value not in completed.stdout
    assert cursor_value not in completed.stderr
    assert stat.S_IMODE(output_file.stat().st_mode) == 0o600


def test_local_acs_port_forward_script_targets_dev_services():
    script = (ROOT / "scripts" / "acs_port_forward.mjs").read_text()

    assert "ACS_DEV_KUBECONFIG" in script
    assert "ecommerce-cs-agent-dev" in script
    assert "svc/postgres" in script
    assert "15432:5432" in script
    assert "svc/minio" in script
    assert "19000:9000" in script
