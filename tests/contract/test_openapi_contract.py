import json
import subprocess
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from ecommerce_cs_agent.api.app import create_app
from ecommerce_cs_agent.core.config import Settings
from ecommerce_cs_agent.services.system_admin import _message_trace_summary_from_row
from tests.admin_fixtures import create_test_app


ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "docs" / "openapi.yaml"
SYSTEM_ADMIN_DESIGN_PATH = ROOT / "docs" / "system-admin-design.md"

REQUIRED_PATHS = {
    "/v1/reply-decisions",
    "/v1/reply-decisions/{decision_id}/contexts/products",
    "/v1/reply-decisions/{decision_id}/contexts/orders",
    "/v1/reply-decisions/{decision_id}/contexts/logistics",
    "/v1/reply-decisions/{decision_id}/contexts/rules",
    "/v1/reply-decisions/{decision_id}/actions/results",
    "/v1/message-traces/{decision_id}",
    "/v1/feedback/human-replies",
    "/v1/integrations/open-erp/admin-launch-tickets",
    "/v1/admin/auth/launch/exchange",
    "/v1/admin/message-traces",
    "/v1/admin/message-simulations",
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
    "/v1/system-admin/dashboard-summary",
    "/v1/system-admin/organizations",
    "/v1/system-admin/stores",
    "/v1/system-admin/readiness/stores",
    "/v1/system-admin/message-traces",
    "/v1/system-admin/tasks",
    "/v1/system-admin/tasks/{task_id}/retry",
    "/v1/system-admin/audit-logs",
    "/v1/system-admin/health",
    "/v1/system-admin/llm/providers",
    "/v1/system-admin/llm/providers/{provider_id}",
    "/v1/system-admin/llm/providers/{provider_id}/connection-tests",
    "/v1/system-admin/llm/config-versions",
    "/v1/system-admin/llm/config-versions/drafts",
    "/v1/system-admin/llm/config-versions/{version_id}",
    "/v1/system-admin/llm/config-versions/{version_id}/routes",
    "/v1/system-admin/llm/config-versions/{version_id}/validate",
    "/v1/system-admin/llm/config-versions/{version_id}/submit-publish",
    "/v1/system-admin/llm/config-versions/{version_id}/publish",
    "/v1/system-admin/llm/config-versions/{version_id}/rollback",
    "/v1/system-admin/llm/usage/summary",
    "/v1/system-admin/llm/usage/timeseries",
    "/v1/system-admin/llm/usage/breakdown",
    "/v1/system-admin/llm/usage/invocations",
}

CORE_JSON_REQUESTS = {
    ("post", "/v1/reply-decisions"): "#/components/schemas/ReplyDecisionCreateRequest",
    ("post", "/v1/reply-decisions/{decision_id}/contexts/products"): "#/components/schemas/ProductContextRefillRequest",
    ("post", "/v1/reply-decisions/{decision_id}/contexts/orders"): "#/components/schemas/OrderContextRefillRequest",
    ("post", "/v1/reply-decisions/{decision_id}/contexts/logistics"): "#/components/schemas/LogisticsContextRefillRequest",
    ("post", "/v1/reply-decisions/{decision_id}/contexts/rules"): "#/components/schemas/RuleContextRefillRequest",
    ("post", "/v1/reply-decisions/{decision_id}/actions/results"): "#/components/schemas/ActionResultRequest",
    ("post", "/v1/admin/auth/login"): "#/components/schemas/AdminLoginRequest",
    ("post", "/v1/admin/auth/launch/exchange"): "#/components/schemas/AdminLaunchExchangeRequest",
    ("post", "/v1/admin/message-simulations"): "#/components/schemas/AdminMessageSimulationRequest",
    ("post", "/v1/admin/auth/oidc/link"): "#/components/schemas/AdminOidcLinkRequest",
    ("post", "/v1/product-content/products"): "#/components/schemas/ProductUpsertRequest",
    ("post", "/v1/product-content/product-import-drafts"): "#/components/schemas/ProductImportDraftCreateRequest",
    ("post", "/v1/product-content/product-import-drafts/{draft_id}/confirm"): "#/components/schemas/ProductImportDraftConfirmRequest",
    ("post", "/v1/product-content/assets"): "#/components/schemas/ProductAssetCreateRequest",
    ("post", "/v1/product-content/price-snapshots"): "#/components/schemas/ProductPriceSnapshotRequest",
    ("post", "/v1/system-admin/auth/login"): "#/components/schemas/SystemAdminLoginRequest",
    ("post", "/v1/system-admin/organizations"): "#/components/schemas/SystemOrganizationCreateRequest",
    ("post", "/v1/system-admin/stores"): "#/components/schemas/SystemStoreCreateRequest",
    ("post", "/v1/system-admin/tasks/{task_id}/retry"): "#/components/schemas/TaskRetryRequest",
    ("post", "/v1/system-admin/llm/providers"): "#/components/schemas/LlmProviderCreateRequest",
    ("patch", "/v1/system-admin/llm/providers/{provider_id}"): "#/components/schemas/LlmProviderUpdateRequest",
    ("post", "/v1/system-admin/llm/providers/{provider_id}/connection-tests"): "#/components/schemas/LlmConnectionTestRequest",
    ("post", "/v1/system-admin/llm/config-versions/drafts"): "#/components/schemas/LlmConfigDraftCreateRequest",
    ("put", "/v1/system-admin/llm/config-versions/{version_id}/routes"): "#/components/schemas/LlmRoutesReplaceRequest",
    ("patch", "/v1/system-admin/llm/config-versions/{version_id}/routes"): "#/components/schemas/LlmRoutesReplaceRequest",
    ("post", "/v1/system-admin/llm/config-versions/{version_id}/validate"): "#/components/schemas/LlmRevisionWriteRequest",
    ("post", "/v1/system-admin/llm/config-versions/{version_id}/submit-publish"): "#/components/schemas/LlmSubmitPublishRequest",
    ("post", "/v1/system-admin/llm/config-versions/{version_id}/publish"): "#/components/schemas/LlmRevisionWriteRequest",
    ("post", "/v1/system-admin/llm/config-versions/{version_id}/rollback"): "#/components/schemas/LlmRollbackRequest",
}

CORE_JSON_RESPONSES = {
    ("post", "/v1/reply-decisions", "200"): "#/components/schemas/ReplyDecisionResponse",
    ("post", "/v1/reply-decisions/{decision_id}/contexts/products", "200"): "#/components/responses/ContextRefillAccepted",
    ("post", "/v1/reply-decisions/{decision_id}/contexts/orders", "200"): "#/components/responses/ContextRefillAccepted",
    ("post", "/v1/reply-decisions/{decision_id}/contexts/logistics", "200"): "#/components/responses/ContextRefillAccepted",
    ("post", "/v1/reply-decisions/{decision_id}/contexts/rules", "200"): "#/components/responses/ContextRefillAccepted",
    ("post", "/v1/reply-decisions/{decision_id}/actions/results", "200"): "#/components/schemas/ActionResultResponse",
    ("post", "/v1/admin/auth/login", "200"): "#/components/schemas/AdminAuthResponse",
    ("post", "/v1/admin/auth/launch/exchange", "200"): "#/components/schemas/AdminAuthResponse",
    ("get", "/v1/admin/message-traces", "200"): "#/components/schemas/CustomerMessageTraceListResponse",
    ("post", "/v1/admin/message-simulations", "201"): "#/components/schemas/AdminMessageSimulationResponse",
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
    ("get", "/v1/system-admin/dashboard-summary", "200"): "#/components/schemas/SystemDashboardSummary",
    ("get", "/v1/system-admin/organizations", "200"): "#/components/schemas/SystemOrganizationListResponse",
    ("post", "/v1/system-admin/organizations", "201"): "#/components/schemas/SystemOrganizationResponse",
    ("get", "/v1/system-admin/stores", "200"): "#/components/schemas/SystemStoreListResponse",
    ("post", "/v1/system-admin/stores", "201"): "#/components/schemas/SystemStoreResponse",
    ("get", "/v1/system-admin/readiness/stores", "200"): "#/components/schemas/ReadinessListResponse",
    ("get", "/v1/system-admin/message-traces", "200"): "#/components/schemas/SystemMessageTraceListResponse",
    ("get", "/v1/system-admin/tasks", "200"): "#/components/schemas/TaskListResponse",
    ("post", "/v1/system-admin/tasks/{task_id}/retry", "202"): "#/components/schemas/TaskRetryResponse",
    ("get", "/v1/system-admin/audit-logs", "200"): "#/components/schemas/AuditLogListResponse",
    ("get", "/v1/system-admin/health", "200"): "#/components/schemas/SystemHealthResponse",
    ("get", "/v1/system-admin/llm/providers", "200"): "#/components/schemas/LlmProviderListResponse",
    ("post", "/v1/system-admin/llm/providers", "201"): "#/components/schemas/LlmProvider",
    ("patch", "/v1/system-admin/llm/providers/{provider_id}", "200"): "#/components/schemas/LlmProvider",
    ("post", "/v1/system-admin/llm/providers/{provider_id}/connection-tests", "202"): "#/components/schemas/LlmConnectionTest",
    ("get", "/v1/system-admin/llm/config-versions", "200"): "#/components/schemas/LlmConfigVersionListResponse",
    ("get", "/v1/system-admin/llm/releases", "200"): "#/components/schemas/LlmReleaseRecordListResponse",
    ("post", "/v1/system-admin/llm/config-versions/drafts", "201"): "#/components/schemas/LlmConfigVersion",
    ("get", "/v1/system-admin/llm/config-versions/{version_id}", "200"): "#/components/schemas/LlmConfigVersion",
    ("put", "/v1/system-admin/llm/config-versions/{version_id}/routes", "200"): "#/components/schemas/LlmConfigVersion",
    ("patch", "/v1/system-admin/llm/config-versions/{version_id}/routes", "200"): "#/components/schemas/LlmConfigVersion",
    ("post", "/v1/system-admin/llm/config-versions/{version_id}/validate", "200"): "#/components/schemas/LlmConfigVersion",
    ("post", "/v1/system-admin/llm/config-versions/{version_id}/submit-publish", "200"): "#/components/schemas/LlmConfigVersion",
    ("post", "/v1/system-admin/llm/config-versions/{version_id}/publish", "200"): "#/components/schemas/LlmConfigVersion",
    ("post", "/v1/system-admin/llm/config-versions/{version_id}/rollback", "200"): "#/components/schemas/LlmConfigVersion",
    ("get", "/v1/system-admin/llm/usage/summary", "200"): "#/components/schemas/LlmUsageSummary",
    ("get", "/v1/system-admin/llm/usage/timeseries", "200"): "#/components/schemas/LlmUsageTimeseriesResponse",
    ("get", "/v1/system-admin/llm/usage/breakdown", "200"): "#/components/schemas/LlmUsageBreakdownResponse",
    ("get", "/v1/system-admin/llm/usage/invocations", "200"): "#/components/schemas/LlmInvocationListResponse",
}

PAGINATED_SCHEMAS = {
    "AdminUserListResponse",
    "AuditLogListResponse",
    "ProductListResponse",
    "CustomerMessageTraceListResponse",
    "SystemMessageTraceListResponse",
    "SystemOrganizationListResponse",
    "SystemStoreListResponse",
    "ReadinessListResponse",
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
    "#/components/responses/ServiceUnavailable",
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


def assert_schema_valid(instance, schema, document):
    schemas = document["components"]["schemas"]
    schema_name = next((name for name, candidate in schemas.items() if candidate is schema), None)
    if schema_name is None:
        raise AssertionError("schema must be a component from the loaded OpenAPI document")

    document_uri = "urn:ecommerce-cs-agent:openapi"
    registry = Registry().with_resource(
        document_uri,
        Resource.from_contents(document, default_specification=DRAFT202012),
    )
    validator = Draft202012Validator(
        {"$ref": f"{document_uri}#/components/schemas/{schema_name}"},
        registry=registry,
        format_checker=FormatChecker(),
    )
    validator.validate(instance)


def presents_customer_admin_provisioning_as_current_capability(line: str) -> bool:
    customer_admin_terms = (
        "客户后台初始管理员",
        "客户管理员邀请",
        "客户管理员开通",
    )
    if not any(term in line for term in customer_admin_terms):
        return False
    non_current_markers = ("后续", "当前不可用", "当前不", "不提供", "不得", "经批准部署")
    if any(marker in line for marker in non_current_markers):
        return False
    current_action_markers = ("能", "可以", "支持", "创建", "开通", "邀请", "重发", "禁用", "恢复", "可用")
    return any(marker in line for marker in current_action_markers)


class OpenApiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = load_openapi()

    def test_openapi_yaml_is_parseable(self):
        self.assertEqual(self.document["openapi"], "3.1.0")
        self.assertIsInstance(self.document["paths"], dict)
        self.assertIsInstance(self.document["components"], dict)

    def test_system_admin_operational_contract_exposes_real_retry_and_audit_filters(self):
        task = self.document["components"]["schemas"]["BackgroundTask"]
        self.assertIn("retryable", task["required"])
        self.assertIn("organization_id", task["required"])
        self.assertNotIn("tenant_id", task["properties"])
        self.assertEqual(task["properties"]["retryable"]["type"], "boolean")
        retry_request = self.document["components"]["schemas"]["TaskRetryRequest"]
        self.assertEqual(retry_request["properties"]["idempotency_key"]["maxLength"], 128)
        self.assertEqual(retry_request["properties"]["reason"]["maxLength"], 512)
        assert_schema_valid(
            {
                "task_id": "task-example",
                "task_type": "embedding",
                "status": "failed",
                "retryable": True,
                "organization_id": "org-example",
                "store_id": "store-example",
                "input_ref": "asset-example",
                "output_ref": None,
                "error_summary": "provider timeout",
                "retry_count": 1,
                "next_retry_at": None,
                "created_at": "2026-07-15T08:00:00Z",
            },
            task,
            self.document,
        )

        audit_schema = self.document["components"]["schemas"]["AuditLog"]
        self.assertIn("organization_id", audit_schema["properties"])
        self.assertNotIn("tenant_id", audit_schema["properties"])
        self.assertEqual(audit_schema["properties"]["diff_summary"]["type"], ["object", "null"])
        assert_schema_valid(
            {
                "audit_log_id": "audit-example",
                "actor_system_user_id": "sysadmin-example",
                "organization_id": "org-example",
                "store_id": "store-example",
                "object_type": "background_task",
                "object_id": "task-example",
                "action": "system_admin.task.retry",
                "reason": "manual retry",
                "diff_summary": {"reason": "manual retry", "sensitive_access": False},
                "sensitive_access": False,
                "created_at": "2026-07-15T08:00:00Z",
            },
            audit_schema,
            self.document,
        )

        audit = self.document["paths"]["/v1/system-admin/audit-logs"]["get"]
        parameter_names = {
            parameter.get("name")
            for parameter in audit["parameters"]
            if "$ref" not in parameter
        }
        self.assertIn("action", parameter_names)
        self.assertIn("actor_user_id", parameter_names)
        self.assertIn("sensitive_access", parameter_names)

    def test_system_dashboard_contract_contains_real_recent_release_summaries(self):
        schema = self.document["components"]["schemas"]["SystemDashboardSummary"]
        self.assertIn("recent_releases", schema["required"])
        self.assertIn("recent_releases_status", schema["required"])
        self.assertIn("recent_releases_error", schema["required"])
        release_ref = schema["properties"]["recent_releases"]["items"]["$ref"]
        self.assertEqual(release_ref, "#/components/schemas/SystemRecentRelease")

    def test_system_dashboard_response_example_validates_with_formats(self):
        operation = self.document["paths"]["/v1/system-admin/dashboard-summary"]["get"]
        content = operation["responses"]["200"]["content"]["application/json"]

        assert_schema_valid(
            content["example"],
            self.document["components"]["schemas"]["SystemDashboardSummary"],
            self.document,
        )

    def test_customer_admin_provisioning_capability_guard_has_positive_and_negative_cases(self):
        self.assertTrue(presents_customer_admin_provisioning_as_current_capability("第一版能开通客户后台初始管理员。"))
        self.assertTrue(presents_customer_admin_provisioning_as_current_capability("客户管理员邀请当前可用。"))
        self.assertFalse(presents_customer_admin_provisioning_as_current_capability("展示经批准部署流程配置的客户后台初始管理员准备状态。"))
        self.assertFalse(presents_customer_admin_provisioning_as_current_capability("邀请系统管理员加入平台。"))

    def test_system_admin_design_does_not_claim_customer_admin_provisioning_as_current_ui_capability(self):
        provisioning_lines = [
            line.strip()
            for line in SYSTEM_ADMIN_DESIGN_PATH.read_text(encoding="utf-8").splitlines()
            if any(term in line for term in ("客户后台初始管理员", "客户管理员邀请", "客户管理员开通"))
        ]

        self.assertTrue(provisioning_lines)
        for line in provisioning_lines:
            self.assertFalse(
                presents_customer_admin_provisioning_as_current_capability(line),
                f"customer admin provisioning is presented as a current UI capability: {line}",
            )

    def test_actual_system_admin_organization_store_readiness_and_trace_shapes_validate(self):
        self.assertNotIn("/v1/system-admin/tenants", self.document["paths"])
        for stale_schema in ("SystemTenant", "SystemTenantListResponse", "SystemTenantCreateRequest", "SystemTenantResponse"):
            self.assertNotIn(stale_schema, self.document["components"]["schemas"])
        for schema_name in (
            "SystemOrganization",
            "SystemStore",
            "SystemStoreCreateRequest",
            "SystemStoreReadinessSummary",
            "SystemMessageTraceSummary",
        ):
            self.assertNotIn("tenant_id", json.dumps(self.document["components"]["schemas"][schema_name]))
        for path in (
            "/v1/system-admin/stores",
            "/v1/system-admin/readiness/stores",
            "/v1/system-admin/message-traces",
            "/v1/system-admin/tasks",
        ):
            parameter_names = [
                resolve_pointer(self.document, item["$ref"])["name"] if "$ref" in item else item["name"]
                for item in self.document["paths"][path]["get"]["parameters"]
            ]
            self.assertIn("organization_id", parameter_names, path)
            self.assertNotIn("tenant_id", parameter_names, path)

        client = TestClient(create_test_app(Settings(environment="test", database_url=None)))
        headers = {"Cookie": "agent_system_admin_session=test-system-session"}
        organization_response = client.post(
            "/v1/system-admin/organizations",
            headers=headers,
            json={
                "name": "Contract Organization",
                "status": "active",
                "external_ref": "org-contract",
                "reason": "contract validation",
                "idempotency_key": "org-contract-create",
            },
        )
        store_response = client.post(
            "/v1/system-admin/stores",
            headers=headers,
            json={
                "organization_id": "org-contract",
                "name": "Contract Store",
                "platform": "pdd",
                "external_store_id": "store-contract",
                "status": "active",
                "reason": "contract validation",
                "idempotency_key": "store-contract-create",
            },
        )
        organization_update_response = client.post(
            "/v1/system-admin/organizations",
            headers=headers,
            json={
                "name": "Contract Organization Updated",
                "status": "suspended",
                "external_ref": "org-contract",
                "reason": "contract update validation",
                "idempotency_key": "org-contract-update",
            },
        )
        actual = [
            (organization_response, "SystemOrganizationResponse"),
            (organization_update_response, "SystemOrganizationResponse"),
            (client.get("/v1/system-admin/organizations", headers=headers), "SystemOrganizationListResponse"),
            (store_response, "SystemStoreResponse"),
            (client.get("/v1/system-admin/stores?organization_id=org-contract", headers=headers), "SystemStoreListResponse"),
            (client.get("/v1/system-admin/readiness/stores?organization_id=org-contract", headers=headers), "ReadinessListResponse"),
        ]
        for response, schema_name in actual:
            self.assertLess(response.status_code, 300, schema_name)
            assert_schema_valid(response.json(), self.document["components"]["schemas"][schema_name], self.document)

        for status in self.document["components"]["schemas"]["DecisionStatus"]["enum"]:
            trace_summary = _message_trace_summary_from_row((
                f"decision-{status}",
                "org-contract",
                "store-contract",
                "request-contract",
                None,
                "candidate",
                "low",
                status,
                "2026-07-15T08:00:00Z",
            ))
            assert_schema_valid(
                {"items": [trace_summary], "page_info": {"page": 1, "page_size": 20, "total": 1}},
                self.document["components"]["schemas"]["SystemMessageTraceListResponse"],
                self.document,
            )

    def test_usage_endpoints_share_component_query_parameters(self):
        paths = [
            "/v1/system-admin/llm/usage/summary",
            "/v1/system-admin/llm/usage/timeseries",
            "/v1/system-admin/llm/usage/breakdown",
            "/v1/system-admin/llm/usage/invocations",
        ]
        expected_refs = [
            f"#/components/parameters/{name}"
            for name in (
                "LlmUsageStartAt",
                "LlmUsageEndAt",
                "LlmUsageProviderConfigId",
                "LlmUsageModel",
                "LlmUsageScenario",
                "LlmUsageOrganizationId",
                "LlmUsageStoreId",
                "LlmUsageCurrency",
                "LlmUsageStatus",
                "LlmUsageRouteRole",
            )
        ]
        resolved_sets = []
        for path in paths:
            parameters = self.document["paths"][path]["get"]["parameters"]
            refs = [parameter["$ref"] for parameter in parameters if "$ref" in parameter]
            self.assertEqual(refs[: len(expected_refs)], expected_refs)
            resolved_sets.append(
                [resolve_pointer(self.document, ref) for ref in refs[: len(expected_refs)]]
            )
        self.assertTrue(all(value == resolved_sets[0] for value in resolved_sets[1:]))

    def test_llm_cursor_contract_documents_scope_exclusive_boundary_and_end_of_pages(self):
        paths = self.document["paths"]
        config_parameters = paths["/v1/system-admin/llm/config-versions"]["get"]["parameters"]
        invocation_parameters = paths["/v1/system-admin/llm/usage/invocations"]["get"]["parameters"]
        config_cursor = next(item for item in config_parameters if item.get("name") == "cursor")
        invocation_cursor = next(item for item in invocation_parameters if item.get("name") == "cursor")
        page_info = self.document["components"]["schemas"]["LlmPageInfo"]

        for parameter in (config_cursor, invocation_cursor):
            description = parameter.get("description", "").lower()
            self.assertIn("same", description)
            self.assertIn("exclusive", description)
            self.assertIn("422", description)
        self.assertIn("organization", config_cursor["description"].lower())
        self.assertIn("filters", invocation_cursor["description"].lower())

        schema_description = page_info.get("description", "").lower()
        next_description = page_info["properties"]["next_cursor"].get("description", "").lower()
        self.assertIn("same organization", schema_description)
        self.assertIn("same filters", schema_description)
        self.assertIn("exclusive", schema_description)
        self.assertIn("null", next_description)
        self.assertIn("no next page", next_description)

    def test_schema_validator_rejects_formats_enums_bounds_patterns_and_one_of(self):
        schemas = self.document["components"]["schemas"]
        connection_test = {
            "connection_test_id": "11111111-1111-4111-8111-111111111111",
            "provider_config_id": "22222222-2222-4222-8222-222222222222",
            "config_version_id": "33333333-3333-4333-8333-333333333333",
            "provider_revision": 1,
            "status": "passed",
            "latency_ms": 1,
            "checked_at": "2026-07-15T00:00:00Z",
        }
        provider_request = {
            "name": "provider",
            "provider_type": "openai",
            "base_url": "https://provider.example/v1",
            "secret_ref": {"namespace": "runtime", "name": "llm", "key": "api-key"},
            "reason": "contract",
            "idempotency_key": "provider-create",
        }
        connection_request = {
            "config_version_id": "33333333-3333-4333-8333-333333333333",
            "timeout_seconds": 3,
            "max_tokens": 8,
            "reason": "contract",
            "idempotency_key": "connection-test",
        }
        route = {
            "scenario": "reply_generation",
            "primary_provider_config_id": "22222222-2222-4222-8222-222222222222",
            "primary_model": "chat-pro",
            "fallback_provider_config_id": None,
            "fallback_model": None,
            "enabled": True,
            "temperature": 0.2,
            "max_output_tokens": 1200,
            "timeout_seconds": 18,
            "max_retries": 2,
            "circuit_breaker_threshold": 5,
            "recovery_probe_seconds": 30,
        }
        routes_request = {
            "routes": [route],
            "expected_revision": 1,
            "reason": "contract",
            "idempotency_key": "routes",
        }
        submit_request = {
            "expected_revision": 1,
            "evaluation_run_id": "eval-contract",
            "reason": "contract",
            "idempotency_key": "submit",
        }

        invalid_cases = [
            (schemas["LlmConnectionTest"], {**connection_test, "provider_config_id": "not-a-uuid"}),
            (schemas["LlmConnectionTest"], {**connection_test, "status": "unknown"}),
            (schemas["LlmConnectionTest"], {**connection_test, "checked_at": "not-a-date-time"}),
            (schemas["LlmProviderCreateRequest"], {**provider_request, "base_url": "https:// bad"}),
            (schemas["LlmConnectionTestRequest"], {**connection_request, "timeout_seconds": 0}),
            (schemas["LlmConnectionTestRequest"], {**connection_request, "max_tokens": 257}),
            (schemas["LlmRoutesReplaceRequest"], {**routes_request, "routes": []}),
            (
                schemas["LlmRoutesReplaceRequest"],
                {**routes_request, "routes": [{**route, "fallback_provider_config_id": 42}]},
            ),
            (
                schemas["LlmSubmitPublishRequest"],
                {**submit_request, "evaluation_run_id": "invalid evaluation id"},
            ),
        ]
        for schema, instance in invalid_cases:
            with self.assertRaises((AssertionError, ValidationError)):
                assert_schema_valid(instance, schema, self.document)

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

    def test_decision_continuation_routes_document_trusted_scope_forbidden_response(self):
        paths = self.document["paths"]
        continuation_paths = [
            "/v1/reply-decisions/{decision_id}/contexts/products",
            "/v1/reply-decisions/{decision_id}/contexts/orders",
            "/v1/reply-decisions/{decision_id}/contexts/logistics",
            "/v1/reply-decisions/{decision_id}/contexts/rules",
            "/v1/reply-decisions/{decision_id}/actions/results",
            "/v1/feedback/human-replies",
        ]

        for path in continuation_paths:
            self.assertEqual(
                paths[path]["post"]["responses"]["403"]["$ref"],
                "#/components/responses/Forbidden",
                path,
            )

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

    def test_customer_admin_oidc_contract_is_customer_scoped(self):
        paths = self.document["paths"]
        link_schema = self.document["components"]["schemas"]["AdminOidcLinkRequest"]

        self.assertEqual(paths["/v1/admin/auth/oidc/start"]["get"]["security"], [])
        self.assertEqual(paths["/v1/admin/auth/oidc/callback"]["get"]["security"], [])
        self.assertEqual(paths["/v1/admin/auth/oidc/link"]["post"]["security"], [{"AdminSession": []}])
        self.assertNotIn("/v1/system-admin/auth/oidc/start", paths)
        self.assertEqual(set(link_schema["required"]), {"code", "state"})
        self.assertNotIn("token", link_schema["properties"])
        self.assertNotIn("client_secret", link_schema["properties"])

    def test_product_snapshot_contract_separates_master_product_and_listing_context(self):
        schema = self.document["components"]["schemas"]["ProductSnapshot"]
        properties = schema["properties"]

        self.assertIn("product_master_ref", properties)
        self.assertIn("listing_ref", properties)
        self.assertIn("external_store_id", properties)
        self.assertIn("platform_account_ref", properties)
        self.assertIn("external_sku_id", properties)

    def test_llm_governance_contract_uses_only_system_session_and_never_models_secrets(self):
        document_text = json.dumps(self.document).lower()
        self.assertNotIn("secret_value", document_text)
        self.assertNotIn("authorization", json.dumps(self.document["components"]["schemas"].get("LlmProviderCreateRequest", {})).lower())

        for path, path_item in self.document["paths"].items():
            if not path.startswith("/v1/system-admin/llm/"):
                continue
            for method, operation in path_item.items():
                if method in {"get", "post", "put", "patch", "delete"}:
                    self.assertEqual(operation["security"], [{"SystemAdminSession": []}], f"{method} {path}")

        secret_ref = self.document["components"]["schemas"]["LlmSecretReference"]
        self.assertEqual(set(secret_ref["required"]), {"namespace", "name", "key"})
        self.assertEqual(set(secret_ref["properties"]), {"namespace", "name", "key"})
        namespace = secret_ref["properties"]["namespace"]
        name = secret_ref["properties"]["name"]
        key = secret_ref["properties"]["key"]
        strict_end = r"(?![\s\S])"
        dns_label = f"^[a-z0-9](?:[-a-z0-9]{{0,61}}[a-z0-9])?{strict_end}"
        dns_subdomain = f"^[a-z0-9](?:[-a-z0-9]{{0,61}}[a-z0-9])?(?:\\.[a-z0-9](?:[-a-z0-9]{{0,61}}[a-z0-9])?)*{strict_end}"
        self.assertEqual((namespace["maxLength"], namespace["pattern"]), (63, dns_label))
        self.assertEqual((name["maxLength"], name["pattern"]), (253, dns_subdomain))
        self.assertEqual((key["maxLength"], key["pattern"]), (253, f"^[A-Za-z0-9._-]+{strict_end}"))

        readiness_codes = self.document["components"]["schemas"]["ReadinessCheck"]["properties"]["code"]["enum"]
        self.assertEqual(
            readiness_codes,
            ["product_content", "price_snapshot", "knowledge_review", "api_integration"],
        )

        health_dependencies = self.document["components"]["schemas"]["HealthDependency"]["properties"]["name"]["enum"]
        self.assertEqual(health_dependencies, ["api", "postgresql", "pgvector", "queue"])
        self.assertEqual(
            set(self.document["components"]["schemas"]["HealthDependency"]["required"]),
            {"name", "status", "message", "checked_at"},
        )

    def test_llm_secret_reference_schema_strictly_validates_input_boundaries(self):
        secret_ref = self.document["components"]["schemas"]["LlmSecretReference"]
        maximum_name = ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61])
        legal_references = [
            {"namespace": "a", "name": "a", "key": "A"},
            {"namespace": "a" * 63, "name": maximum_name, "key": "K" * 253},
            {"namespace": "runtime-1", "name": "provider.runtime-1", "key": "api_key.v1-"},
        ]
        for reference in legal_references:
            with self.subTest(reference=reference):
                assert_schema_valid(reference, secret_ref, self.document)

        base = {"namespace": "runtime", "name": "llm-provider", "key": "api-key"}
        invalid_references = []
        for field in ("namespace", "name", "key"):
            for prefix, suffix in (("", "\n"), (" ", ""), ("", " "), ("\t", ""), ("", "\t")):
                reference = dict(base)
                reference[field] = f"{prefix}{reference[field]}{suffix}"
                invalid_references.append((field, prefix, suffix, reference))
        for field, prefix, suffix, reference in invalid_references:
            with self.subTest(field=field, prefix=prefix, suffix=suffix):
                with self.assertRaises(ValidationError):
                    assert_schema_valid(reference, secret_ref, self.document)

    def test_llm_governance_contract_documents_roles_lifecycle_filters_and_mixed_currency(self):
        paths = self.document["paths"]
        connection = paths["/v1/system-admin/llm/providers/{provider_id}/connection-tests"]["post"]
        self.assertIn("technical_support", connection["description"])
        self.assertEqual(connection["responses"]["202"]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/LlmConnectionTest")

        publish = paths["/v1/system-admin/llm/config-versions/{version_id}/publish"]["post"]
        self.assertIn("pending_publish", publish["description"])
        self.assertIn("release_admin", publish["description"])
        self.assertIn("409", publish["responses"])

        component_parameters = self.document["components"]["parameters"]
        summary_parameters = {
            component_parameters[item["$ref"].rsplit("/", 1)[-1]]["name"]
            if "$ref" in item
            else item["name"]
            for item in paths["/v1/system-admin/llm/usage/summary"]["get"]["parameters"]
        }
        self.assertEqual(
            summary_parameters,
            {"start_at", "end_at", "provider_config_id", "model", "scenario", "organization_id", "store_id", "currency", "status", "route_role"},
        )
        summary = self.document["components"]["schemas"]["LlmUsageSummary"]
        self.assertIn("cost_by_currency", summary["properties"])
        self.assertIn("null", summary["properties"]["estimated_cost_micros"]["type"])

        version = self.document["components"]["schemas"]["LlmConfigVersion"]
        self.assertIn("release_record", version["properties"])
        self.assertIn("evaluation", version["properties"])
        request_route = self.document["components"]["schemas"]["LlmScenarioRoute"]
        self.assertNotIn("route_id", request_route["properties"])
        self.assertEqual(
            version["properties"]["routes"]["items"]["$ref"],
            "#/components/schemas/LlmScenarioRouteView",
        )
        audit_parameters = {item.get("name") for item in paths["/v1/system-admin/audit-logs"]["get"]["parameters"] if "name" in item}
        self.assertIn("action_prefix", audit_parameters)
        release = self.document["components"]["schemas"]["LlmReleaseRecord"]
        self.assertIn("rollback_of_release_id", release["properties"])

    def test_llm_operations_document_exact_roles_base_errors_and_safe_request_examples(self):
        read_roles = {"super_admin", "release_admin", "technical_support", "security_auditor"}
        write_roles = {"super_admin", "release_admin"}
        connection_roles = write_roles | {"technical_support"}
        write_operations = 0

        for path, path_item in self.document["paths"].items():
            if not path.startswith("/v1/system-admin/llm/"):
                continue
            for method, operation in path_item.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                expected_roles = read_roles if method == "get" else write_roles
                if path.endswith("/connection-tests"):
                    expected_roles = connection_roles
                self.assertEqual(set(operation.get("x-roles", [])), expected_roles, f"{method} {path}")
                self.assertTrue({"401", "403", "422", "500"} <= set(operation["responses"]), f"{method} {path}")
                if method != "get":
                    write_operations += 1
                    media = operation["requestBody"]["content"]["application/json"]
                    example = media.get("example") or next(iter(media.get("examples", {}).values()), {}).get("value")
                    self.assertIsInstance(example, dict, f"missing request example {method} {path}")
                    safe = json.dumps(example).lower()
                    self.assertNotIn("secret_value", safe)
                    self.assertNotIn("bearer ", safe)
                    self.assertNotIn("prompt", safe)

        self.assertEqual(write_operations, 10)

        not_found = {
            ("patch", "/v1/system-admin/llm/providers/{provider_id}"),
            ("post", "/v1/system-admin/llm/providers/{provider_id}/connection-tests"),
            ("get", "/v1/system-admin/llm/config-versions/{version_id}"),
            ("put", "/v1/system-admin/llm/config-versions/{version_id}/routes"),
            ("patch", "/v1/system-admin/llm/config-versions/{version_id}/routes"),
            ("post", "/v1/system-admin/llm/config-versions/{version_id}/validate"),
            ("post", "/v1/system-admin/llm/config-versions/{version_id}/submit-publish"),
            ("post", "/v1/system-admin/llm/config-versions/{version_id}/publish"),
            ("post", "/v1/system-admin/llm/config-versions/{version_id}/rollback"),
        }
        conflict = {
            ("post", "/v1/system-admin/llm/providers"),
            ("patch", "/v1/system-admin/llm/providers/{provider_id}"),
            ("post", "/v1/system-admin/llm/providers/{provider_id}/connection-tests"),
            ("post", "/v1/system-admin/llm/config-versions/drafts"),
            ("put", "/v1/system-admin/llm/config-versions/{version_id}/routes"),
            ("patch", "/v1/system-admin/llm/config-versions/{version_id}/routes"),
            ("post", "/v1/system-admin/llm/config-versions/{version_id}/validate"),
            ("post", "/v1/system-admin/llm/config-versions/{version_id}/submit-publish"),
            ("post", "/v1/system-admin/llm/config-versions/{version_id}/publish"),
            ("post", "/v1/system-admin/llm/config-versions/{version_id}/rollback"),
        }
        for method, path in not_found:
            self.assertIn("404", self.document["paths"][path][method]["responses"], f"{method} {path}")
        for method, path in conflict:
            self.assertIn("409", self.document["paths"][path][method]["responses"], f"{method} {path}")

        organization = self.document["paths"]["/v1/system-admin/llm/config-versions"]["get"]["parameters"][0]
        self.assertEqual(organization["schema"]["format"], "uuid")
        self.assertTrue(organization["required"])

    def test_actual_llm_errors_validate_against_error_response_schema(self):
        client = TestClient(
            create_test_app(
                Settings(environment="test", database_url=None),
                llm_connection_tester=lambda _provider, _request: {"status": "passed", "latency_ms": 5},
            )
        )
        headers = {"Cookie": "agent_system_admin_session=test-system-session"}
        provider_payload = {
            "name": "contract-provider",
            "provider_type": "openai_compatible",
            "base_url": "https://provider.example/v1",
            "secret_ref": {"namespace": "runtime", "name": "llm-provider", "key": "api-key"},
            "reason": "contract setup",
            "idempotency_key": "contract-provider-create",
        }
        provider = client.post("/v1/system-admin/llm/providers", headers=headers, json=provider_payload).json()
        stale = client.patch(
            f"/v1/system-admin/llm/providers/{provider['provider_id']}",
            headers=headers,
            json={"enabled": False, "expected_revision": 2, "reason": "stale", "idempotency_key": "contract-stale"},
        )
        missing = client.patch(
            "/v1/system-admin/llm/providers/99999999-9999-9999-9999-999999999999",
            headers=headers,
            json={"enabled": False, "expected_revision": 1, "reason": "missing", "idempotency_key": "contract-missing"},
        )
        invalid = client.post(
            "/v1/system-admin/llm/providers",
            headers=headers,
            json={**provider_payload, "idempotency_key": "contract-invalid", "secret_value": "must-not-return"},
        )
        draft = client.post(
            "/v1/system-admin/llm/config-versions/drafts",
            headers=headers,
            json={"organization_id": "11111111-1111-1111-1111-111111111111", "reason": "draft", "idempotency_key": "contract-draft"},
        ).json()
        routes = [
            {
                "scenario": scenario,
                "primary_provider_config_id": provider["provider_id"],
                "primary_model": "chat-pro",
                "fallback_provider_config_id": None,
                "fallback_model": None,
                "enabled": True,
                "temperature": 0.2,
                "max_output_tokens": 1200,
                "timeout_seconds": 18,
                "max_retries": 2,
                "circuit_breaker_threshold": 5,
                "recovery_probe_seconds": 30,
            }
            for scenario in ("reply_generation", "knowledge_extraction", "blind_test_question_generation")
        ]
        changed = client.put(
            f"/v1/system-admin/llm/config-versions/{draft['version_id']}/routes",
            headers=headers,
            json={"routes": routes, "expected_revision": 1, "reason": "routes", "idempotency_key": "contract-routes"},
        ).json()
        client.post(
            f"/v1/system-admin/llm/providers/{provider['provider_id']}/connection-tests",
            headers=headers,
            json={"config_version_id": draft["version_id"], "reason": "test", "idempotency_key": "contract-test"},
        )
        validated = client.post(
            f"/v1/system-admin/llm/config-versions/{draft['version_id']}/validate",
            headers=headers,
            json={"expected_revision": changed["revision"], "reason": "validate", "idempotency_key": "contract-validate"},
        ).json()
        gate = client.post(
            f"/v1/system-admin/llm/config-versions/{draft['version_id']}/submit-publish",
            headers=headers,
            json={"expected_revision": validated["revision"], "evaluation_run_id": "eval-contract", "reason": "submit", "idempotency_key": "contract-submit"},
        )

        expected = [(stale, 409, "stale_revision"), (missing, 404, "provider_not_found"), (gate, 409, "release_gate_failed"), (invalid, 422, "validation_error")]
        schema = self.document["components"]["schemas"]["ErrorResponse"]
        for response, status, code in expected:
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["error"]["code"], code)
            assert_schema_valid(response.json(), schema, self.document)
            safe = response.text.lower()
            self.assertNotIn("must-not-return", safe)
            self.assertNotIn("postgresql://", safe)

        business_details = {
            "detail": "business validation failed",
            "error": {
                "code": "business_rule_failed",
                "message": "business validation failed",
                "details": {"field": "safe-reference"},
            },
        }
        assert_schema_valid(business_details, schema, self.document)

    def test_actual_llm_success_payloads_validate_distinct_response_schemas(self):
        client = TestClient(
            create_test_app(
                Settings(environment="test", database_url=None),
                llm_connection_tester=lambda _provider, _request: {"status": "passed", "latency_ms": 5},
            )
        )
        headers = {"Cookie": "agent_system_admin_session=test-system-session"}
        provider_response = client.post(
            "/v1/system-admin/llm/providers",
            headers=headers,
            json={
                "name": "success-provider",
                "provider_type": "openai_compatible",
                "base_url": "https://provider.example/v1",
                "secret_ref": {"namespace": "runtime", "name": "llm-provider", "key": "api-key"},
                "reason": "schema",
                "idempotency_key": "schema-provider",
            },
        )
        provider = provider_response.json()
        draft_response = client.post(
            "/v1/system-admin/llm/config-versions/drafts",
            headers=headers,
            json={"organization_id": "11111111-1111-1111-1111-111111111111", "reason": "schema", "idempotency_key": "schema-draft"},
        )
        draft = draft_response.json()
        connection_response = client.post(
            f"/v1/system-admin/llm/providers/{provider['provider_id']}/connection-tests",
            headers=headers,
            json={"config_version_id": draft["version_id"], "reason": "schema", "idempotency_key": "schema-connection"},
        )
        actual = [
            (provider_response, "LlmProvider"),
            (client.get("/v1/system-admin/llm/providers", headers=headers), "LlmProviderListResponse"),
            (draft_response, "LlmConfigVersion"),
            (client.get("/v1/system-admin/llm/config-versions?organization_id=11111111-1111-1111-1111-111111111111", headers=headers), "LlmConfigVersionListResponse"),
            (client.get("/v1/system-admin/llm/releases?organization_id=11111111-1111-1111-1111-111111111111", headers=headers), "LlmReleaseRecordListResponse"),
            (connection_response, "LlmConnectionTest"),
            (client.get("/v1/system-admin/llm/usage/summary", headers=headers), "LlmUsageSummary"),
            (client.get("/v1/system-admin/llm/usage/timeseries", headers=headers), "LlmUsageTimeseriesResponse"),
            (client.get("/v1/system-admin/llm/usage/breakdown?group_by=model", headers=headers), "LlmUsageBreakdownResponse"),
            (client.get("/v1/system-admin/llm/usage/invocations", headers=headers), "LlmInvocationListResponse"),
        ]
        for response, schema_name in actual:
            self.assertLess(response.status_code, 300, schema_name)
            assert_schema_valid(response.json(), self.document["components"]["schemas"][schema_name], self.document)


if __name__ == "__main__":
    unittest.main()
