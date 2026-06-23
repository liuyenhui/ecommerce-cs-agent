import json
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "docs" / "openapi.yaml"

REQUIRED_PATHS = {
    "/v1/reply-decisions",
    "/v1/reply-decisions/{decision_id}/contexts/products",
    "/v1/reply-decisions/{decision_id}/contexts/orders",
    "/v1/reply-decisions/{decision_id}/contexts/logistics",
    "/v1/reply-decisions/{decision_id}/contexts/rules",
    "/v1/reply-decisions/{decision_id}/actions/results",
    "/v1/message-traces/{decision_id}",
    "/v1/feedback/human-replies",
    "/v1/admin/auth/login",
    "/v1/admin/auth/logout",
    "/v1/admin/auth/me",
    "/v1/admin/auth/oidc/start",
    "/v1/admin/auth/oidc/callback",
    "/v1/admin/auth/oidc/link",
    "/v1/admin/audit-logs",
    "/v1/product-content/products",
    "/v1/product-content/product-import-drafts",
    "/v1/product-content/product-import-drafts/{draft_id}/confirm",
    "/v1/product-content/assets",
    "/v1/product-content/price-snapshots",
    "/v1/system-admin/auth/login",
    "/v1/system-admin/auth/logout",
    "/v1/system-admin/auth/me",
    "/v1/system-admin/message-traces",
    "/v1/system-admin/audit-logs",
    "/v1/system-admin/health",
}

CORE_JSON_REQUESTS = {
    ("post", "/v1/reply-decisions"): "#/components/schemas/ReplyDecisionCreateRequest",
    ("post", "/v1/admin/auth/login"): "#/components/schemas/AdminLoginRequest",
    ("post", "/v1/admin/auth/oidc/link"): "#/components/schemas/AdminOidcLinkRequest",
    ("post", "/v1/product-content/products"): "#/components/schemas/ProductUpsertRequest",
    ("post", "/v1/product-content/product-import-drafts"): "#/components/schemas/ProductImportDraftCreateRequest",
    ("post", "/v1/product-content/product-import-drafts/{draft_id}/confirm"): "#/components/schemas/ProductImportDraftConfirmRequest",
    ("post", "/v1/product-content/assets"): "#/components/schemas/ProductAssetCreateRequest",
    ("post", "/v1/product-content/price-snapshots"): "#/components/schemas/ProductPriceSnapshotRequest",
    ("post", "/v1/system-admin/auth/login"): "#/components/schemas/SystemAdminLoginRequest",
    ("post", "/v1/system-admin/tasks/{task_id}/retry"): "#/components/schemas/TaskRetryRequest",
}

CORE_JSON_RESPONSES = {
    ("post", "/v1/reply-decisions", "200"): "#/components/schemas/ReplyDecisionResponse",
    ("post", "/v1/admin/auth/login", "200"): "#/components/schemas/AdminAuthResponse",
    ("get", "/v1/admin/auth/oidc/callback", "307"): "#/components/schemas/AdminOidcRedirectResponse",
    ("post", "/v1/admin/auth/oidc/link", "200"): "#/components/schemas/AdminAuthResponse",
    ("get", "/v1/admin/auth/me", "200"): "#/components/schemas/AdminMeResponse",
    ("get", "/v1/admin/users", "200"): "#/components/schemas/AdminUserListResponse",
    ("get", "/v1/admin/audit-logs", "200"): "#/components/schemas/AuditLogListResponse",
    ("post", "/v1/product-content/products", "201"): "#/components/schemas/ProductUpsertResponse",
    ("get", "/v1/product-content/products", "200"): "#/components/schemas/ProductListResponse",
    ("post", "/v1/product-content/product-import-drafts", "201"): "#/components/schemas/ProductImportDraftResponse",
    ("post", "/v1/product-content/product-import-drafts/{draft_id}/confirm", "201"): "#/components/schemas/ProductImportDraftConfirmResponse",
    ("post", "/v1/product-content/assets", "201"): "#/components/schemas/ProductAssetResponse",
    ("post", "/v1/product-content/price-snapshots", "201"): "#/components/schemas/ProductPriceSnapshotResponse",
    ("get", "/v1/system-admin/auth/me", "200"): "#/components/schemas/SystemAdminMeResponse",
    ("get", "/v1/system-admin/message-traces", "200"): "#/components/schemas/SystemMessageTraceListResponse",
    ("get", "/v1/system-admin/tasks", "200"): "#/components/schemas/TaskListResponse",
    ("post", "/v1/system-admin/tasks/{task_id}/retry", "202"): "#/components/schemas/TaskRetryResponse",
    ("get", "/v1/system-admin/audit-logs", "200"): "#/components/schemas/AuditLogListResponse",
    ("get", "/v1/system-admin/health", "200"): "#/components/schemas/SystemHealthResponse",
}

PAGINATED_SCHEMAS = {
    "AdminUserListResponse",
    "AuditLogListResponse",
    "ProductListResponse",
    "SystemMessageTraceListResponse",
    "TaskListResponse",
}

ERROR_RESPONSE_REFS = {
    "#/components/responses/BadRequest",
    "#/components/responses/Unauthorized",
    "#/components/responses/Forbidden",
    "#/components/responses/NotFound",
    "#/components/responses/IdempotencyConflict",
    "#/components/responses/Conflict",
    "#/components/responses/ValidationError",
    "#/components/responses/ObjectStorageUnavailable",
    "#/components/responses/TooManyRequests",
    "#/components/responses/InternalError",
}


def load_openapi():
    result = subprocess.run(
        [
            "ruby",
            "-rjson",
            "-ryaml",
            "-e",
            "puts JSON.generate(YAML.load_file(ARGV.fetch(0)))",
            str(OPENAPI_PATH),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return json.loads(result.stdout)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def resolve_pointer(document, ref):
    if not ref.startswith("#/"):
        raise AssertionError(f"non-local $ref is not allowed: {ref}")

    current = document
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            raise AssertionError(f"missing $ref target: {ref}")
    return current


def json_schema_ref(operation, status_code):
    response = operation["responses"][status_code]
    if "$ref" in response:
        return response["$ref"]
    return response["content"]["application/json"]["schema"]["$ref"]


class OpenApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_openapi()

    def test_openapi_yaml_is_parseable(self):
        self.assertEqual(self.document["openapi"], "3.1.0")
        self.assertIsInstance(self.document["paths"], dict)
        self.assertIsInstance(self.document["components"], dict)

    def test_local_refs_are_all_resolvable(self):
        refs = [node["$ref"] for node in walk(self.document) if "$ref" in node]
        self.assertGreater(refs, [])
        missing = []
        for ref in refs:
            try:
                resolve_pointer(self.document, ref)
            except AssertionError as exc:
                missing.append(str(exc))

        self.assertEqual(missing, [], "\n".join(missing))

    def test_operation_ids_are_unique(self):
        operation_ids = []
        for path_item in self.document["paths"].values():
            for method, operation in path_item.items():
                if method.lower() in {"get", "post", "put", "patch", "delete"}:
                    operation_ids.append(operation.get("operationId"))

        missing = [operation for operation in operation_ids if not operation]
        duplicates = sorted(
            operation_id
            for operation_id in set(operation_ids)
            if operation_ids.count(operation_id) > 1
        )
        self.assertEqual(missing, [])
        self.assertEqual(duplicates, [])

    def test_first_version_required_paths_exist(self):
        paths = self.document["paths"]
        failures = []
        for path in sorted(REQUIRED_PATHS):
            if path not in paths:
                failures.append(f"missing path {path}")
                continue
            operations = [
                (method, operation)
                for method, operation in paths[path].items()
                if method.lower() in {"get", "post", "put", "patch", "delete"}
            ]
            if not operations:
                failures.append(f"missing operation {path}")
                continue
            for method, operation in operations:
                if not operation.get("operationId"):
                    failures.append(f"missing operationId {method.upper()} {path}")
                if "security" not in operation:
                    failures.append(f"missing security {method.upper()} {path}")
                if "responses" not in operation or not operation["responses"]:
                    failures.append(f"missing responses {method.upper()} {path}")

        self.assertEqual(failures, [], "\n".join(failures))

    def test_product_asset_declares_object_storage_unavailable_response(self):
        responses = self.document["paths"]["/v1/product-content/assets"]["post"]["responses"]

        self.assertEqual(
            responses["503"]["$ref"],
            "#/components/responses/ObjectStorageUnavailable",
        )

    def test_core_json_request_schemas_are_explicit(self):
        failures = []
        for (method, path), expected_ref in sorted(CORE_JSON_REQUESTS.items()):
            operation = self.document["paths"][path][method]
            request_body = operation.get("requestBody")
            if not request_body:
                failures.append(f"missing requestBody {method.upper()} {path}")
                continue
            actual_ref = request_body["content"]["application/json"]["schema"].get("$ref")
            if actual_ref != expected_ref:
                failures.append(f"{method.upper()} {path} request schema {actual_ref} != {expected_ref}")

        self.assertEqual(failures, [], "\n".join(failures))

    def test_core_json_response_schemas_and_status_codes_are_explicit(self):
        failures = []
        for (method, path, status_code), expected_ref in sorted(CORE_JSON_RESPONSES.items()):
            operation = self.document["paths"][path][method]
            responses = operation.get("responses", {})
            if status_code not in responses:
                failures.append(f"missing {status_code} response {method.upper()} {path}")
                continue
            actual_ref = json_schema_ref(operation, status_code)
            if actual_ref != expected_ref:
                failures.append(f"{method.upper()} {path} {status_code} schema {actual_ref} != {expected_ref}")

        self.assertEqual(failures, [], "\n".join(failures))

    def test_standard_error_responses_use_error_response_schema(self):
        responses = self.document["components"]["responses"]
        failures = []
        for response_ref in sorted(ERROR_RESPONSE_REFS):
            response_name = response_ref.rsplit("/", 1)[-1]
            schema_ref = responses[response_name]["content"]["application/json"]["schema"]["$ref"]
            if schema_ref != "#/components/schemas/ErrorResponse":
                failures.append(f"{response_name} uses {schema_ref}")

        for path, path_item in self.document["paths"].items():
            for method, operation in path_item.items():
                if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                    continue
                for status_code, response in operation.get("responses", {}).items():
                    if not status_code.startswith(("4", "5")):
                        continue
                    if response.get("$ref") not in ERROR_RESPONSE_REFS:
                        failures.append(f"{method.upper()} {path} {status_code} must reference a standard error response")

        self.assertEqual(failures, [], "\n".join(failures))

    def test_paginated_response_schemas_have_items_and_page_info(self):
        schemas = self.document["components"]["schemas"]
        failures = []
        for schema_name in sorted(PAGINATED_SCHEMAS):
            schema = schemas[schema_name]
            required = set(schema.get("required", []))
            properties = schema.get("properties", {})
            if {"items", "page_info"} - required:
                failures.append(f"{schema_name} must require items and page_info")
            if properties.get("items", {}).get("type") != "array":
                failures.append(f"{schema_name}.items must be array")
            if properties.get("page_info", {}).get("$ref") != "#/components/schemas/PageInfo":
                failures.append(f"{schema_name}.page_info must reference PageInfo")

        self.assertEqual(failures, [], "\n".join(failures))

    def test_external_reply_decision_contract_uses_platform_store_listing_context(self):
        schema = self.document["components"]["schemas"]["ReplyDecisionCreateRequest"]
        required = set(schema["required"])
        properties = schema["properties"]

        self.assertNotIn("organization_id", required)
        self.assertIn("platform", required)
        self.assertIn("external_store_id", required)
        self.assertIn("platform_account_ref", properties)
        self.assertIn("listing_ref", properties)
        self.assertIn("external_product_id", properties)
        self.assertIn("external_sku_id", properties)

        example = self.document["paths"]["/v1/reply-decisions"]["post"]["requestBody"]["content"]["application/json"]["examples"]["waitingContext"]["value"]
        self.assertNotIn("organization_id", example)
        self.assertEqual(example["external_store_id"], "pdd-store-001")
        self.assertEqual(example["platform_account_ref"], "pdd-account-main")

    def test_customer_admin_login_contract_does_not_use_organization_id(self):
        schema = self.document["components"]["schemas"]["AdminLoginRequest"]

        self.assertEqual(set(schema["required"]), {"email", "password"})
        self.assertNotIn("organization_id", schema["properties"])

    def test_product_snapshot_contract_separates_master_product_and_listing_context(self):
        schema = self.document["components"]["schemas"]["ProductSnapshot"]
        properties = schema["properties"]

        self.assertIn("product_master_ref", properties)
        self.assertIn("listing_ref", properties)
        self.assertIn("external_store_id", properties)
        self.assertIn("platform_account_ref", properties)
        self.assertIn("external_sku_id", properties)


if __name__ == "__main__":
    unittest.main()
