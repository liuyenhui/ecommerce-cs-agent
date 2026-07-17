from __future__ import annotations

import base64
import os
import uuid

import psycopg

from ecommerce_cs_agent.services.llm_node_configuration import ApiKeyCipher
from ecommerce_cs_agent.services.outbound_http import validate_public_https_url


DEFAULT_IMPORT_ID = "00000000-0000-4000-8000-000000000013"


def import_legacy_llm() -> str:
    database_url = _required("DATABASE_URL")
    api_key = _required("LLM_API_KEY")
    base_url = validate_public_https_url(_required("LLM_BASE_URL"), field="LLM base URL")
    model_id = _required("LLM_MODEL")
    cipher = ApiKeyCipher.from_base64(_required("LLM_CREDENTIAL_ENCRYPTION_KEY"))
    encrypted = cipher.encrypt(api_key)
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        cur.execute("SELECT id::text FROM llm_model_config WHERE id=%s", (DEFAULT_IMPORT_ID,))
        existing = cur.fetchone()
        if not existing:
            cur.execute(
                "INSERT INTO llm_model_config (id,name,provider,base_url,model_id,api_key_ciphertext,api_key_nonce,encryption_version,api_key_last_four,enabled,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,'untested')",
                (DEFAULT_IMPORT_ID, "Migrated runtime LLM", "openai_compatible", base_url, model_id, base64.b64decode(encrypted["ciphertext"]), base64.b64decode(encrypted["nonce"]), encrypted["encryption_version"], api_key[-4:]),
            )
        cur.execute("SELECT count(*) FROM langgraph_node_llm_binding")
        if cur.fetchone()[0] == 0:
            cur.execute("SELECT revision FROM llm_node_binding_revision WHERE singleton=TRUE FOR UPDATE")
            revision = cur.fetchone()[0] + 1
            for node_id in ("classify_service_stage", "generate_candidate"):
                cur.execute("INSERT INTO langgraph_node_llm_binding (node_id,llm_model_config_id,revision) VALUES (%s,%s,%s) ON CONFLICT (node_id) DO NOTHING", (node_id, DEFAULT_IMPORT_ID, revision))
            cur.execute("UPDATE llm_node_binding_revision SET revision=%s,updated_at=now() WHERE singleton=TRUE", (revision,))
    return DEFAULT_IMPORT_ID


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


if __name__ == "__main__":
    imported_id = import_legacy_llm()
    print(f"legacy LLM import complete: {imported_id}")
