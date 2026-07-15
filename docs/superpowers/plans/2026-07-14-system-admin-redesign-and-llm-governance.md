# System Admin Redesign and LLM Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild System Admin as a nine-page real-data operations console and add secure, versioned LLM provider, routing, usage, release, and audit governance.

**Architecture:** Keep the existing FastAPI application and PostgreSQL repository pattern, but isolate new LLM governance logic in a focused service and mount its routes from a dedicated API module. Split the System Admin React workspace into small page components behind one typed API client; all totals and charts consume server responses, while non-test runtimes fail fast instead of falling back to in-memory demo repositories.

**Tech Stack:** Python 3.11+, FastAPI, psycopg 3, PostgreSQL migrations, pytest, React 19, TypeScript 5.9, Vite 7, Vitest, Lucide React, CSS, OpenAPI, Helm/Kubernetes.

---

## File map

### Backend

- Create `migrations/012_system_admin_llm_governance.sql`: durable Provider, config version, scenario route, connection test, invocation metric, and release fields/indexes.
- Create `ecommerce_cs_agent/services/llm_governance.py`: LLM governance protocol plus in-memory test and PostgreSQL implementations.
- Create `ecommerce_cs_agent/api/system_admin_llm.py`: typed route registration for Provider, config, route, usage, publish, and rollback endpoints.
- Modify `ecommerce_cs_agent/services/system_admin.py`: non-test fail-fast repository selection and dashboard summary aggregation.
- Modify `ecommerce_cs_agent/services/admin_auth.py`: non-test System Admin auth fail-fast behavior.
- Modify `ecommerce_cs_agent/api/app.py`: initialize the LLM governance repository, register the new routes, and expose dashboard summary.
- Modify `ecommerce_cs_agent/core/config.py`: require PostgreSQL for development/production and define a 20-second connection-test timeout plus a 256-token response ceiling.
- Modify `docs/openapi.yaml`: publish the exact System Admin LLM and dashboard contracts.

### Frontend

- Create `admin-web/system-admin/src/system-types.ts`: page keys and typed response models.
- Create `admin-web/system-admin/src/system-api.ts`: System Admin-only API functions.
- Create `admin-web/system-admin/src/SystemWorkspace.tsx`: data loading, filters, page selection, drawers, and error boundaries.
- Create `admin-web/system-admin/src/pages/DashboardPage.tsx`.
- Create `admin-web/system-admin/src/pages/TenantsPage.tsx`.
- Create `admin-web/system-admin/src/pages/ReadinessPage.tsx`.
- Create `admin-web/system-admin/src/pages/LlmGovernancePage.tsx`.
- Create `admin-web/system-admin/src/pages/ReleasesPage.tsx`.
- Create `admin-web/system-admin/src/pages/TracesPage.tsx`.
- Create `admin-web/system-admin/src/pages/TasksPage.tsx`.
- Create `admin-web/system-admin/src/pages/AuditPage.tsx`.
- Create `admin-web/system-admin/src/pages/HealthPage.tsx`.
- Create `admin-web/system-admin/src/system-admin.test.tsx`: Vitest component and data-state tests.
- Modify `admin-web/system-admin/src/App.tsx`: authentication shell and page composition only.
- Modify `admin-web/system-admin/src/styles.css`: Carbon-style layout, collapsible rail, functional sections, usage views, and responsive states.
- Modify `admin-web/shared/components.tsx` and `admin-web/shared/styles/base.css`: reusable loading, empty, inline error, permission, status, and navigation collapse primitives.
- Modify `admin-web/package.json`: include System Admin Vitest tests.

### Tests and docs

- Create `tests/services/test_llm_governance.py`.
- Create `tests/api/test_system_admin_llm_v1.py`.
- Modify `tests/api/test_system_admin_v1.py`.
- Modify `tests/api/test_admin_boundaries.py`.
- Modify `tests/db/test_migrations.py`.
- Modify `tests/contract/test_openapi_contract.py`.
- Modify `admin-web/scripts/admin-boundary.test.mjs` and `admin-web/scripts/assert-ui-regressions.mjs`.
- Modify `docs/system-admin-design.md`, `docs/http-api-design.md`, `docs/testing.md`, and `docs/development-handoff.md` when implementation contracts are finalized.

## Task 1: Enforce the real-data runtime boundary

**Files:**
- Modify: `ecommerce_cs_agent/services/system_admin.py:1080`
- Modify: `ecommerce_cs_agent/services/admin_auth.py:1321`
- Modify: `tests/api/test_admin_boundaries.py`
- Modify: `tests/api/test_system_admin_v1.py`

- [ ] **Step 1: Write failing repository-selection tests**

Add tests that make the environment boundary explicit:

```python
def test_system_admin_repository_allows_in_memory_only_in_test() -> None:
    repository = system_admin_repository_for(Settings(environment="test", database_url=None))
    assert isinstance(repository, InMemorySystemAdminRepository)


def test_system_admin_repository_requires_database_outside_test() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL is required for System Admin"):
        system_admin_repository_for(Settings(environment="development", database_url=None))
```

Add equivalent tests for `system_admin_auth_service_for`.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
APP_ENV=test .venv/bin/pytest tests/api/test_admin_boundaries.py tests/api/test_system_admin_v1.py -q
```

Expected: the new non-test assertions fail because both factories currently return in-memory demo implementations.

- [ ] **Step 3: Implement fail-fast repository selection**

Use the same rule in both factories:

```python
def system_admin_repository_for(settings: Settings) -> SystemAdminRepository:
    if settings.environment.lower() == "test":
        return InMemorySystemAdminRepository()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for System Admin outside test")
    return PostgresSystemAdminRepository(settings.database_url)
```

For System Admin auth, return `InMemorySystemAdminAuthService` only in test and otherwise require `database_url` before constructing `PostgresSystemAdminAuthService`.

- [ ] **Step 4: Make test settings explicit**

Where tests call `create_app()` without a database, set `APP_ENV=test` through a shared autouse fixture or pass `Settings(environment="test")`. Do not weaken the production factory rule.

- [ ] **Step 5: Run API tests**

Run:

```bash
APP_ENV=test .venv/bin/pytest tests/api/test_admin_boundaries.py tests/api/test_system_admin_v1.py -q
```

Expected: PASS; no non-test path creates `Demo Organization` or `Demo PDD Store`.

- [ ] **Step 6: Commit**

```bash
git add ecommerce_cs_agent/services/system_admin.py ecommerce_cs_agent/services/admin_auth.py tests/api/test_admin_boundaries.py tests/api/test_system_admin_v1.py
git commit -m "fix: prohibit System Admin demo fallback"
```

## Task 2: Add dashboard aggregation backed by PostgreSQL totals

**Files:**
- Modify: `ecommerce_cs_agent/services/system_admin.py`
- Modify: `ecommerce_cs_agent/api/app.py`
- Modify: `tests/api/test_system_admin_v1.py`

- [ ] **Step 1: Write the failing dashboard contract test**

```python
def test_system_admin_dashboard_uses_repository_aggregates() -> None:
    client = TestClient(create_app(Settings(environment="test")))
    response = client.get(
        "/v1/system-admin/dashboard-summary",
        headers={"Cookie": "agent_system_admin_session=test-system-session"},
    )
    assert response.status_code == 200
    assert response.json().keys() >= {
        "active_organizations", "active_stores", "decisions_today",
        "auto_reply_rate", "handoff_rate", "error_rate",
        "readiness_blockers", "pending_tasks", "critical_alerts",
    }
```

- [ ] **Step 2: Verify the endpoint is absent**

Run:

```bash
APP_ENV=test .venv/bin/pytest tests/api/test_system_admin_v1.py::test_system_admin_dashboard_uses_repository_aggregates -q
```

Expected: FAIL with HTTP 404.

- [ ] **Step 3: Extend the repository protocol and test implementation**

Add `dashboard_summary(session)` to `SystemAdminRepository`. The in-memory test repository may calculate values from explicit test collections, but must return no seeded business records by default:

```python
return {
    "active_organizations": len([x for x in self.organizations.values() if x["status"] == "active"]),
    "active_stores": len([x for x in self.stores.values() if x["status"] == "active"]),
    "decisions_today": 0,
    "auto_reply_rate": None,
    "handoff_rate": None,
    "error_rate": None,
    "readiness_blockers": 0,
    "pending_tasks": 0,
    "critical_alerts": 0,
    "generated_at": _now(),
}
```

- [ ] **Step 4: Implement one PostgreSQL aggregation query**

Use conditional aggregates and `NULLIF` for rates; do not load entire tables into Python. Return `None` when a denominator is zero so the UI can show “暂无数据”. Audit the dashboard read once, not once per metric.

- [ ] **Step 5: Register the endpoint and pass tests**

```python
@app.get("/v1/system-admin/dashboard-summary")
def get_system_dashboard_summary(session: Any = Depends(system_session)) -> dict[str, Any]:
    return system_admin_data.dashboard_summary(session)
```

Run:

```bash
APP_ENV=test .venv/bin/pytest tests/api/test_system_admin_v1.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ecommerce_cs_agent/services/system_admin.py ecommerce_cs_agent/api/app.py tests/api/test_system_admin_v1.py
git commit -m "feat: add System Admin dashboard aggregates"
```

## Task 3: Add the LLM governance database migration

**Files:**
- Create: `migrations/012_system_admin_llm_governance.sql`
- Modify: `tests/db/test_migrations.py`

- [ ] **Step 1: Write the failing migration assertions**

```python
def test_llm_governance_migration_contains_versioned_secure_tables() -> None:
    sql = Path("migrations/012_system_admin_llm_governance.sql").read_text(encoding="utf-8").lower()
    for snippet in [
        "create table if not exists llm_provider_config",
        "secret_namespace",
        "secret_name",
        "secret_key",
        "create table if not exists llm_config_version",
        "create unique index",
        "create table if not exists llm_scenario_route",
        "create table if not exists llm_connection_test",
        "create table if not exists llm_invocation_metric",
        "estimated_cost_minor",
    ]:
        assert snippet in sql
    assert "secret_value" not in sql
```

- [ ] **Step 2: Verify the test fails because the migration is missing**

Run:

```bash
.venv/bin/pytest tests/db/test_migrations.py::test_llm_governance_migration_contains_versioned_secure_tables -q
```

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Create the forward-only migration**

Define UUID primary keys, timestamps, foreign keys to `system_admin_user`, status checks, one-running-version partial unique index, scenario uniqueness per version, filter indexes on invocation time/provider/model/scenario/organization/store, and comments stating that Secret values and message bodies are forbidden. Use `ON DELETE RESTRICT` for released configuration history.

- [ ] **Step 4: Run migration tests and dry-run planning**

```bash
.venv/bin/pytest tests/db/test_migrations.py -q
.venv/bin/python -m ecommerce_cs_agent.db.cli migrate --database-url postgresql://example.local/cs_agent --migrations-dir migrations --dry-run
```

Expected: tests PASS and dry-run lists `012_system_admin_llm_governance.sql` as pending.

- [ ] **Step 5: Commit**

```bash
git add migrations/012_system_admin_llm_governance.sql tests/db/test_migrations.py
git commit -m "feat: add LLM governance schema"
```

## Task 4: Implement LLM governance service behavior with TDD

**Files:**
- Create: `ecommerce_cs_agent/services/llm_governance.py`
- Create: `tests/services/test_llm_governance.py`

- [ ] **Step 1: Write failing service tests**

Cover these concrete transitions:

```python
def test_draft_publish_and_rollback_preserve_immutable_history() -> None:
    service = InMemoryLlmGovernanceRepository()
    draft = service.create_draft(SYSTEM_SESSION, {"reason": "tune reply model", "idempotency_key": "draft-1"})
    service.replace_routes(SYSTEM_SESSION, draft["version_id"], [REPLY_ROUTE], expected_revision=1)
    published = service.publish(SYSTEM_SESSION, draft["version_id"], {"reason": "eval passed", "idempotency_key": "pub-1"})
    rolled_back = service.rollback(SYSTEM_SESSION, published["version_id"], {"reason": "provider regression", "idempotency_key": "rb-1"})
    assert published["status"] == "running"
    assert rolled_back["status"] == "running"
    assert rolled_back["rollback_of_version_id"] == published["version_id"]


def test_provider_response_never_contains_secret_value() -> None:
    provider = service.create_provider(SYSTEM_SESSION, PROVIDER_PAYLOAD)
    assert provider["secret_ref"] == {"namespace": "runtime", "name": "llm", "key": "api-key"}
    assert "secret_value" not in json.dumps(provider)
```

Also test role denial, missing reason, idempotency replay/conflict, stale revision 409, connection-test metadata redaction, and zero-usage summaries.

- [ ] **Step 2: Run tests and verify missing module failure**

```bash
.venv/bin/pytest tests/services/test_llm_governance.py -q
```

Expected: collection FAIL because `llm_governance` does not exist.

- [ ] **Step 3: Implement shared types and security helpers**

Define explicit protocol methods and centralize `_require_role`, `_require_reason`, `_idempotency_replay`, `_audit`, `_public_provider`, and response-copy behavior. `_public_provider` must construct the public dictionary from an allowlist rather than deleting sensitive keys after the fact.

- [ ] **Step 4: Implement in-memory Provider and connection-test behavior**

Add Provider create/list/update and connection-test records for tests. Enforce the 20-second timeout and 256-token response ceiling at the request object boundary; store only status, latency, checked time, and a redacted error code/message.

- [ ] **Step 5: Implement in-memory draft, route, publish, and rollback behavior**

Create copied immutable version snapshots, increment `revision` on draft changes, reject stale revisions, require one route per scenario, and create a new running version for rollback rather than mutating history.

- [ ] **Step 6: Implement in-memory usage queries**

Return nullable summary rates and empty arrays when there are no invocation metrics. Implement exact filters for time, Provider, model, scenario, organization, and store.

- [ ] **Step 7: Implement PostgreSQL Provider and version persistence**

Use parameterized SQL and transactions. Provider responses select only the Secret reference columns. Draft updates use `WHERE revision = %s` and return a 409 conflict when no row is updated.

- [ ] **Step 8: Implement transactional publish and rollback**

Lock the target version and current running version with `FOR UPDATE`; mark the old running version superseded only after validation succeeds. Rollback clones the selected historical routes into a new running version and links `rollback_of_version_id`.

- [ ] **Step 9: Implement SQL usage aggregation**

Use `date_trunc`, `SUM`, `percentile_cont`, and filtered counts. Return `NULL` for rates without a denominator and never select prompt/message/response content.

- [ ] **Step 10: Run service tests**

```bash
.venv/bin/pytest tests/services/test_llm_governance.py -q
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add ecommerce_cs_agent/services/llm_governance.py tests/services/test_llm_governance.py
git commit -m "feat: implement LLM governance service"
```

## Task 5: Expose System Admin LLM APIs and OpenAPI contracts

**Files:**
- Create: `ecommerce_cs_agent/api/system_admin_llm.py`
- Create: `tests/api/test_system_admin_llm_v1.py`
- Modify: `ecommerce_cs_agent/api/app.py`
- Modify: `docs/openapi.yaml`
- Modify: `tests/contract/test_openapi_contract.py`

- [ ] **Step 1: Write failing API tests**

Test Provider creation/redaction, draft creation, route replacement, connection test, publish, rollback, usage summary, and Customer Admin rejection. A representative assertion is:

```python
response = client.post(
    "/v1/system-admin/llm/providers",
    headers=SYSTEM_HEADERS,
    json={
        "name": "primary",
        "provider_type": "openai_compatible",
        "base_url": "https://provider.example/v1",
        "secret_ref": {"namespace": "runtime", "name": "llm", "key": "api-key"},
        "reason": "configure primary provider",
        "idempotency_key": "provider-1",
    },
)
assert response.status_code == 201
assert response.json()["secret_ref"]["name"] == "llm"
assert "secret_value" not in response.text
```

- [ ] **Step 2: Verify endpoint tests fail with 404**

```bash
APP_ENV=test .venv/bin/pytest tests/api/test_system_admin_llm_v1.py -q
```

Expected: FAIL because routes are absent.

- [ ] **Step 3: Register the dedicated route module**

Expose `register_system_admin_llm_routes(app, repository, system_session)` and keep request validation close to each route. Use 201 for create, 202 for connection tests, 200 for publish/rollback, 409 for stale revision, and existing `api_error` response shapes.

- [ ] **Step 4: Add exact OpenAPI paths and schemas**

Document every request/response field, role/secret rules, pagination, filters, error responses, and examples containing only fake references. Do not document a `secret_value` field.

- [ ] **Step 5: Run API and contract tests**

```bash
APP_ENV=test .venv/bin/pytest tests/api/test_system_admin_llm_v1.py tests/contract/test_openapi_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Run the targeted secret scan and commit**

```bash
git add ecommerce_cs_agent/api/system_admin_llm.py ecommerce_cs_agent/api/app.py ecommerce_cs_agent/services/llm_governance.py tests/api/test_system_admin_llm_v1.py docs/openapi.yaml tests/contract/test_openapi_contract.py
git diff --cached | rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET"
git commit -m "feat: expose System Admin LLM governance APIs"
```

Expected: secret scan has no matches; commit succeeds.

## Task 6: Split and rebuild the System Admin shell

**Files:**
- Create: `admin-web/system-admin/src/system-types.ts`
- Create: `admin-web/system-admin/src/system-api.ts`
- Create: `admin-web/system-admin/src/SystemWorkspace.tsx`
- Create: `admin-web/system-admin/src/pages/DashboardPage.tsx`
- Create: `admin-web/system-admin/src/pages/TenantsPage.tsx`
- Create: `admin-web/system-admin/src/pages/ReadinessPage.tsx`
- Create: `admin-web/system-admin/src/pages/TracesPage.tsx`
- Create: `admin-web/system-admin/src/pages/TasksPage.tsx`
- Create: `admin-web/system-admin/src/pages/AuditPage.tsx`
- Create: `admin-web/system-admin/src/pages/HealthPage.tsx`
- Modify: `admin-web/system-admin/src/App.tsx`
- Modify: `admin-web/shared/components.tsx`
- Modify: `admin-web/shared/styles/base.css`
- Modify: `admin-web/system-admin/src/styles.css`
- Create: `admin-web/system-admin/src/system-admin.test.tsx`
- Modify: `admin-web/package.json`

- [ ] **Step 1: Write failing navigation and state tests**

```tsx
it("renders nine task-oriented navigation items and persists rail collapse", () => {
  render(<App />);
  for (const label of ["系统总览", "租户与店铺", "配置完成度", "LLM 治理", "评测与发布", "决策追踪", "任务中心", "安全审计", "系统健康"]) {
    expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
  }
  fireEvent.click(screen.getByRole("button", { name: "收起菜单" }));
  expect(localStorage.getItem("system-admin:rail-collapsed")).toBe("true");
});
```

Also test loading, empty, permission denied, partial failure, fatal error, and that dashboard values come from `dashboard-summary` rather than array length.

- [ ] **Step 2: Enable the System Admin Vitest file and verify failure**

Add `system-admin/src/system-admin.test.tsx` to the `vitest run` command, then run:

```bash
npm --prefix admin-web test
```

Expected: FAIL because the nine-page shell and collapse control do not exist.

- [ ] **Step 3: Define page keys and API response types**

Use a closed union:

```ts
export type SystemPage = "dashboard" | "tenants" | "readiness" | "llm" | "releases" | "traces" | "tasks" | "audit" | "health";
```

Define nullable rates, `page.total`, structured dependency health, and discriminated request states. Keep all URLs in `system-api.ts`, and assert that they begin with `/v1/system-admin/`.

- [ ] **Step 4: Implement collapsible navigation and responsive behavior**

Use Lucide icons, an explicit collapse button, `aria-expanded`, tooltips in collapsed mode, visible focus rings, and localStorage persistence. At `max-width: 900px`, ignore the desktop collapsed preference and use the existing overlay drawer behavior.

- [ ] **Step 5: Implement DashboardPage**

Render service aggregate fields, priority work, recent release/task/decision summaries, and nullable metric empty labels. Do not read list array lengths.

- [ ] **Step 6: Implement TenantsPage and ReadinessPage**

Use paginated responses and `page.total`. Keep organization/store detail drawers separate from readiness checks; every blocked check shows reason, impact, and next action.

- [ ] **Step 7: Implement TracesPage and TasksPage**

Preserve the existing per-decision replay fetch and shared `DecisionTraceReplay`. Restrict retry controls to rows whose server response declares `retryable=true`.

- [ ] **Step 8: Implement AuditPage and HealthPage**

Audit filters include actor, organization, store, action, sensitive access, and time. Health groups application, dependency, and deployment checks and renders partial dependency failure as degraded.

- [ ] **Step 9: Run tests and build**

```bash
npm --prefix admin-web test
npm --prefix admin-web run build:system
```

Expected: PASS; Vite produces the System Admin bundle.

- [ ] **Step 10: Commit**

```bash
git add admin-web/system-admin/src admin-web/shared/components.tsx admin-web/shared/styles/base.css admin-web/package.json
git commit -m "feat: rebuild System Admin operations shell"
```

## Task 7: Build LLM governance and usage pages

**Files:**
- Create: `admin-web/system-admin/src/pages/LlmGovernancePage.tsx`
- Create: `admin-web/system-admin/src/pages/ReleasesPage.tsx`
- Modify: `admin-web/system-admin/src/system-api.ts`
- Modify: `admin-web/system-admin/src/system-types.ts`
- Modify: `admin-web/system-admin/src/system-admin.test.tsx`
- Modify: `admin-web/system-admin/src/styles.css`

- [ ] **Step 1: Write failing interaction tests**

```tsx
it("keeps Provider, route, parameters, usage, versions, and audit in separate functional sections", async () => {
  render(<LlmGovernancePage api={fakeApi} />);
  expect(await screen.findByRole("heading", { name: "Provider 连接" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "场景模型路由" })).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: "调用与成本" }));
  expect(await screen.findByText("输入 Token")).toBeVisible();
  expect(screen.getByText("估算成本")).toBeVisible();
});
```

Also test: Secret response redaction, save-draft does not change running version, connection-test progress/result, stale revision conflict, publish confirmation/reason, zero-usage empty state, and no chart rendering when timeseries is empty.

- [ ] **Step 2: Run the focused Vitest test and verify failure**

```bash
npm --prefix admin-web exec vitest run --root admin-web system-admin/src/system-admin.test.tsx
```

Expected: FAIL because `LlmGovernancePage` is absent.

- [ ] **Step 3: Implement four LLM tabs**

Create `配置与路由`, `调用与成本`, `版本记录`, and `变更审计` tabs. Provider and route sections must use separate bordered panels with their own headers and table columns. Use explicit labels and font stacks from the approved design; only model IDs and Secret refs use monospace.

- [ ] **Step 4: Implement safe edit and publish flows**

Keep a local draft revision, disable save while unchanged, validate numeric bounds before submit, include `reason` and `idempotency_key`, surface 409 as “配置已被其他管理员更新，请重新加载”, and require confirmation before publish/rollback. Never render an input for Secret values.

- [ ] **Step 5: Implement usage statistics**

Render summary cards, time series, model/scenario breakdown, failure reasons, and invocation metadata from API responses. Filters include time, Provider, model, scenario, organization, and store. If summary/timeseries is empty, show a structured empty state and no fabricated bars or values.

- [ ] **Step 6: Run frontend verification**

```bash
npm --prefix admin-web test
npm --prefix admin-web run build
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add admin-web/system-admin/src/pages/LlmGovernancePage.tsx admin-web/system-admin/src/pages/ReleasesPage.tsx admin-web/system-admin/src/system-api.ts admin-web/system-admin/src/system-types.ts admin-web/system-admin/src/system-admin.test.tsx admin-web/system-admin/src/styles.css
git commit -m "feat: add LLM governance console"
```

## Task 8: Strengthen boundary, accessibility, and no-demo regressions

**Files:**
- Modify: `admin-web/scripts/admin-boundary.test.mjs`
- Modify: `admin-web/scripts/assert-ui-regressions.mjs`
- Modify: `admin-web/src/mobile-shell.test.mjs`
- Modify: `tests/api/test_admin_boundaries.py`
- Modify: `tests/deploy/test_deploy_artifacts.py`

- [ ] **Step 1: Add source-level boundary assertions**

Assert that Customer Admin source has no `/v1/system-admin`, System Admin source has no `/v1/admin/auth/me`, all nine labels exist, no `Demo Organization` / `Demo PDD Store` fallback appears, and the LLM UI contains no `secret_value` field.

- [ ] **Step 2: Add mobile and accessibility assertions**

Check the 64px desktop rail, `aria-expanded`, `aria-label`, visible focus style, 44px mobile targets, drawer close-on-navigation, mobile table labels, and no horizontal overflow rules.

- [ ] **Step 3: Run boundary and frontend tests**

```bash
npm --prefix admin-web test
APP_ENV=test .venv/bin/pytest tests/api/test_admin_boundaries.py tests/deploy/test_deploy_artifacts.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add admin-web/scripts/admin-boundary.test.mjs admin-web/scripts/assert-ui-regressions.mjs admin-web/src/mobile-shell.test.mjs tests/api/test_admin_boundaries.py tests/deploy/test_deploy_artifacts.py
git commit -m "test: lock System Admin UX and auth boundaries"
```

## Task 9: Synchronize contracts and operator documentation

**Files:**
- Modify: `docs/http-api-design.md`
- Modify: `docs/system-admin-design.md`
- Modify: `docs/testing.md`
- Modify: `docs/development-handoff.md`
- Modify: `docs/openapi.yaml`

- [ ] **Step 1: Update implementation status and exact contracts**

Document actual endpoint paths, request/response fields, roles, status transitions, Secret reference shape, usage retention, empty-state semantics, and migration name. Clearly distinguish implemented behavior from future MFA/SSO/workflow enhancements.

- [ ] **Step 2: Update testing and handoff evidence**

Add exact commands for service/API/frontend/contract tests and a dated handoff entry describing the implemented real-data boundary and LLM governance surface.

- [ ] **Step 3: Run documentation validation**

```bash
.venv/bin/pytest tests/contract/test_markdown_links.py tests/contract/test_openapi_contract.py -q
git diff --check
```

Expected: PASS and no whitespace errors.

- [ ] **Step 4: Run the required staged secret check and commit**

```bash
git add docs/http-api-design.md docs/system-admin-design.md docs/testing.md docs/development-handoff.md docs/openapi.yaml
git diff --cached | rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET"
git commit -m "docs: document System Admin LLM governance"
```

Expected: secret scan has no matches; commit succeeds.

## Task 10: Complete local, visual, deployment, and live verification

**Files:**
- Modify only if verification reveals a scoped defect.

- [ ] **Step 1: Run the full local test suite**

```bash
APP_ENV=test .venv/bin/python -m pytest tests -q
npm --prefix admin-web test
npm --prefix admin-web run build
helm lint deploy/helm/ecommerce-cs-agent -f deploy/helm/ecommerce-cs-agent/values-dev.yaml
helm template ecommerce-cs-agent deploy/helm/ecommerce-cs-agent -f deploy/helm/ecommerce-cs-agent/values-dev.yaml >/tmp/ecommerce-cs-agent-rendered.yaml
```

Expected: all commands exit 0.

- [ ] **Step 2: Run targeted secret and diff checks**

```bash
git diff --check
git diff origin/main...HEAD | rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET"
```

Expected: no secret matches and no whitespace errors.

- [ ] **Step 3: Perform desktop and mobile visual QA**

Use System Admin at `1440x900` and `390x844`. Capture login, expanded rail, collapsed rail, dashboard, tenants, readiness, all four LLM tabs, releases, traces, tasks, audit, health, loading, empty, partial error, and permission states. Verify no horizontal overflow, no Customer/System cross-entry, readable contrast, keyboard focus, and functional separation.

- [ ] **Step 4: Publish through the repository workflow**

Push the feature branch and open a PR. Do not run `docker push` locally. Wait for Python tests, Admin tests/build, Helm checks, CodeQL SAST, and PR checks.

- [ ] **Step 5: Publish images and verify the remote tag**

After merge/approval, use `.github/workflows/publish-images.yml`, then create and delete a temporary `imagePullPolicy: Always` pull-check Pod for both API and Admin images according to project rules.

- [ ] **Step 6: Complete GitOps and live smoke verification**

Verify migration success, HelmRelease reconciliation, API/Admin rollout, public `/health`, System Admin login, own `/v1/system-admin/auth/me` request only, real dashboard totals, empty-state behavior, LLM Provider redaction, draft/publish behavior, and Customer Admin isolation. Do not print credentials, cookies, headers, or storage state.

- [ ] **Step 7: Record final evidence**

Update the PR or handoff with commit, workflow runs, image tags, HelmRelease revision, Pod readiness, public health, and live smoke results. If any gate fails, stop rollout, collect the scoped evidence, fix, and repeat the relevant verification step before claiming completion.
