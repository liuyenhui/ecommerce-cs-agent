import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";
import ts from "typescript";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const adminRoot = path.resolve(scriptDir, "..");
const projectRoot = path.resolve(adminRoot, "..");

function repoPath(...parts) {
  return path.join(adminRoot, ...parts);
}

function readRelative(file) {
  return readFileSync(repoPath(file), "utf8");
}

function readProjectRelative(file) {
  return readFileSync(path.join(projectRoot, file), "utf8");
}

function assertNoAdminDemoFallback(source) {
  assert.doesNotMatch(source, /\b(?:Demo|Test|Sample|Fake) (?:Organization|Tenant|PDD Store|Store)\b/i);
  assert.doesNotMatch(source, /(?:demo|sample|fake)[_-]?(?:organization|tenant|store|admin)[_-]?(?:fallback|default|seed)?/i);
}

function assertLlmUiUsesSecretReferencesOnly(source) {
  const forbidden = new Set([
    "apikey",
    "secretvalue",
    "rawsecret",
    "password",
    "accesstoken",
    "refreshtoken",
    "privatekey",
    "clientsecret",
    "authorization",
    "bearertoken"
  ]);
  const identifiers = source.match(/[A-Za-z][A-Za-z0-9_-]*/g) || [];
  for (const identifier of identifiers) {
    const canonical = identifier.replace(/[-_]/g, "").toLowerCase();
    assert.ok(!forbidden.has(canonical), `forbidden raw credential field ${identifier}`);
  }
  assert.match(source, /<label>Secret namespace<input[^>]*value=\{form\.namespace\}/);
  assert.match(source, /<label>Secret name<input[^>]*value=\{form\.secret_name\}/);
  assert.match(source, /<label>Secret key<input[^>]*value=\{form\.secret_key\}/);
  assert.match(
    source,
    /provider\.secret_ref\.namespace[\s\S]*provider\.secret_ref\.name[\s\S]*provider\.secret_ref\.key/
  );
}

function assertNoRawCredentialAst(source, fileName) {
  const forbidden = new Set([
    "apikey",
    "credential",
    "credentialvalue",
    "secretvalue",
    "rawsecret",
    "password",
    "accesstoken",
    "refreshtoken",
    "privatekey",
    "clientsecret",
    "authorization",
    "bearertoken"
  ]);
  const canonical = (value) => value.replace(/[-_]/g, "").toLowerCase();
  const sourceFile = ts.createSourceFile(fileName, source, ts.ScriptTarget.Latest, true, fileName.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const namedLoginScope = (node) => {
    if (!(ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node) || ts.isVariableDeclaration(node) || ts.isPropertyAssignment(node))) return false;
    return node.name && canonical(node.name.getText(sourceFile).replace(/^['"]|['"]$/g, "")) === "login";
  };
  const check = (value, loginScope) => {
    const normalized = canonical(value);
    if (forbidden.has(normalized) && !(normalized === "password" && loginScope)) {
      throw new Error(`forbidden raw credential field ${value} in ${fileName}`);
    }
  };
  const visit = (node, loginScope = false) => {
    const nextLoginScope = loginScope || namedLoginScope(node);
    if (ts.isIdentifier(node)) check(node.text, nextLoginScope);
    if (ts.isStringLiteral(node) && node.parent && "name" in node.parent && node.parent.name === node) check(node.text, nextLoginScope);
    if (ts.isJsxAttribute(node) && node.name.getText(sourceFile) === "name" && node.initializer) {
      if (ts.isStringLiteral(node.initializer)) check(node.initializer.text, nextLoginScope);
      if (ts.isJsxExpression(node.initializer) && node.initializer.expression && ts.isStringLiteral(node.initializer.expression)) check(node.initializer.expression.text, nextLoginScope);
    }
    ts.forEachChild(node, (child) => visit(child, nextLoginScope));
  };
  visit(sourceFile);
}

function collectSourceFiles(dir, { includeTests = true } = {}) {
  const root = repoPath(dir);
  assert.ok(existsSync(root), `${dir} must exist`);
  const files = [];
  const walk = (current) => {
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const next = path.join(current, entry.name);
      if (entry.isDirectory()) {
        walk(next);
      } else if (/\.(tsx?|css)$/.test(entry.name) && (includeTests || !/\.test\.[^.]+$/.test(entry.name))) {
        files.push(next);
      }
    }
  };
  walk(root);
  return files;
}

function collectSource(dir, options = {}) {
  return collectSourceFiles(dir, options).map((file) => `\n/* ${path.relative(adminRoot, file)} */\n${readFileSync(file, "utf8")}`).join("\n");
}

function sliceBetween(source, start, end) {
  const startIndex = source.indexOf(start);
  const endIndex = source.indexOf(end, startIndex + start.length);
  assert.ok(startIndex >= 0, `missing slice start ${start}`);
  assert.ok(endIndex > startIndex, `missing slice end ${end}`);
  return source.slice(startIndex, endIndex);
}

test("admin web has independent customer and system entry roots", () => {
  assert.ok(existsSync(repoPath("customer-admin", "index.html")), "customer-admin/index.html must exist");
  assert.ok(existsSync(repoPath("customer-admin", "src", "main.tsx")), "customer-admin/src/main.tsx must exist");
  assert.ok(existsSync(repoPath("customer-admin", "src", "App.tsx")), "customer-admin/src/App.tsx must exist");
  assert.ok(existsSync(repoPath("system-admin", "index.html")), "system-admin/index.html must exist");
  assert.ok(existsSync(repoPath("system-admin", "src", "main.tsx")), "system-admin/src/main.tsx must exist");
  assert.ok(existsSync(repoPath("system-admin", "src", "App.tsx")), "system-admin/src/App.tsx must exist");
  assert.ok(existsSync(repoPath("shared", "api.ts")), "shared/api.ts must exist");

  const packageJson = JSON.parse(readRelative("package.json"));
  assert.equal(packageJson.scripts["build:customer"], "vite build --mode customer");
  assert.equal(packageJson.scripts["build:system"], "vite build --mode system");
  assert.match(packageJson.scripts.build, /build:customer/);
  assert.match(packageJson.scripts.build, /build:system/);
});

test("customer admin source stays inside customer auth and host boundary", () => {
  const source = collectSource("customer-admin/src");

  assert.match(source, /\/v1\/admin\/auth\/me/);
  assert.doesNotMatch(source, /\/v1\/system-admin/);
  assert.doesNotMatch(source, /system-admin\.ecommerce-cs-agent-dev\.fcihome\.com/);
  assert.doesNotMatch(source, /agent_system_admin_session/);
  assert.doesNotMatch(source, /\b(SystemSite|SystemWorkspace|SystemHome|TenantManagement|TraceTable|TaskCenter|HealthPanel|SystemCreateModal)\b/);
});

test("customer admin login page keeps customer-only email password and open erp wechat bridge entry", () => {
  const customerApp = readRelative("customer-admin/src/App.tsx");
  const sharedComponents = readRelative("shared/components.tsx");
  const loginRoute = sliceBetween(customerApp, 'if (path === "/login")', 'if (path.startsWith("/admin"))');
  const loginPanel = sliceBetween(sharedComponents, "export function LoginPanelBase", "function loginFailureMessage");
  const loginSource = `${loginRoute}\n${loginPanel}`;

  assert.match(loginSource, /客户后台登录/);
  assert.match(loginSource, /使用 open_erp_agent 微信登录/);
  assert.match(customerApp, /https:\/\/www\.fcihome\.com\/ai-cs\/customer-admin-login/);
  assert.match(loginSource, /邮箱/);
  assert.match(loginSource, /密码/);
  assert.doesNotMatch(loginSource, /组织 ID/);
  assert.doesNotMatch(loginSource, /\borganization\b/i);
  assert.doesNotMatch(loginSource, /org-001/);
  assert.doesNotMatch(loginSource, /system-admin/i);
});

test("customer admin launch exchange submits each one-time token only once in dev", () => {
  const customerApp = readRelative("customer-admin/src/App.tsx");
  const launchExchange = sliceBetween(customerApp, "function LaunchExchange", "function MessageHistory");

  assert.match(launchExchange, /useRef/);
  assert.match(launchExchange, /exchangedLaunchTokenRef/);
  assert.match(launchExchange, /exchangedLaunchTokenRef\.current === token/);
  assert.match(launchExchange, /exchangedLaunchTokenRef\.current = token/);
  assert.match(launchExchange, /\/v1\/admin\/auth\/launch\/exchange/);
});

test("customer admin launch exchange pending state does not render an action button", () => {
  const customerApp = readRelative("customer-admin/src/App.tsx");
  const launchExchange = sliceBetween(customerApp, "function LaunchExchange", "function MessageHistory");
  const pendingBranch = sliceBetween(launchExchange, ") : (", ")}\n      </section>");

  assert.match(pendingBranch, /正在校验一次性启动票据/);
  assert.doesNotMatch(pendingBranch, /<button\b/);
  assert.doesNotMatch(pendingBranch, /微信扫码登录/);
  assert.doesNotMatch(pendingBranch, /登录\/注册/);
});

test("login secondary action is hidden while the login form is processing", () => {
  const sharedComponents = readRelative("shared/components.tsx");
  const loginPanel = sliceBetween(sharedComponents, "export function LoginPanelBase", "function loginFailureMessage");

  assert.match(loginPanel, /loading \? \(/);
  assert.match(loginPanel, /正在处理/);
  assert.match(loginPanel, /\{secondaryAction && !loading \? \(/);
});

test("customer message history reuses the simulation composer for existing and empty conversations", () => {
  const customerApp = readRelative("customer-admin/src/App.tsx");
  const composer = readRelative("customer-admin/src/SimulationComposer.tsx");
  const messageHistory = sliceBetween(customerApp, "function MessageHistory", "function ChatBubble");

  assert.match(customerApp, /import \{ SimulationComposer \}/);
  assert.equal((messageHistory.match(/<SimulationComposer/g) || []).length, 2);
  assert.match(composer, /还没有会话，先模拟一次客户咨询/);
  assert.match(composer, /模拟咨询不会发送给真实买家/);
  assert.match(composer, /role="alert"/);
  assert.match(composer, /请输入模拟客户问题/);
  assert.match(composer, /disabled=\{loading\}/);
  assert.match(composer, /textarea[\s\S]*disabled=\{loading\}/);
  assert.match(messageHistory, /setSearchText\(""\)/);
  assert.match(messageHistory, /const createdTrace = await requireReloadedSimulation\(/);
  assert.match(messageHistory, /reportError: false, throwOnError: true/);
  assert.doesNotMatch(messageHistory, /setRows\(\(current\) => \[newTrace, \.\.\.current\]\)/);
  assert.match(messageHistory, /generationRef/);
  assert.match(messageHistory, /currentStoreRef/);
  assert.match(messageHistory, /mountedRef/);
  assert.match(messageHistory, /return \(\) => \{[\s\S]*mountedRef\.current = false/);
  assert.match(messageHistory, /isCurrentOperation/);
  assert.match(messageHistory, /setSelectedTrace\(buildCanonicalSimulationTrace\(createdTrace, content\)\)/);
  assert.match(messageHistory, /SectionHeader[\s\S]*disabled=\{simulationLoading\}[\s\S]*刷新/);
});

test("decision metrics preserve raw values as accessible titles", () => {
  const customerApp = readRelative("customer-admin/src/App.tsx");
  const sharedComponents = readRelative("shared/components.tsx");
  const metric = sliceBetween(sharedComponents, "export function Metric", "export function DataTable");

  assert.match(customerApp, /value=\{presentation\.actionLabel\}/);
  assert.match(customerApp, /title=\{String\(trace\.action/);
  assert.match(metric, /title\?: string/);
  assert.match(metric, /title=\{title\}/);
});

test("system admin source stays inside system auth boundary", () => {
  const source = collectSource("system-admin/src");

  assert.match(source, /\/v1\/system-admin\/auth\/me/);
  assert.doesNotMatch(source, /\/v1\/admin\/auth\/me/);
  assert.doesNotMatch(source, /agent_admin_session/);
  assert.doesNotMatch(source, /\b(CustomerSite|CustomerAdminShell|CustomerWorkspace|CustomerOverview|ProductContent|KnowledgeReview|ProductUploadModal)\b/);
});

test("system admin keeps all nine task-oriented destinations reachable", () => {
  const source = readRelative("system-admin/src/SystemWorkspace.tsx");
  const labels = [
    "系统总览",
    "租户与店铺",
    "配置完成度",
    "LLM 治理",
    "评测与发布",
    "决策追踪",
    "任务中心",
    "安全审计",
    "系统健康"
  ];

  for (const label of labels) assert.match(source, new RegExp(label));
  assert.equal((source.match(/\{ key: "/g) || []).length, labels.length);
});

test("admin production sources contain no demo organization or store fallback", () => {
  const source = [
    collectSource("customer-admin/src", { includeTests: false }),
    collectSource("system-admin/src", { includeTests: false }),
    collectSource("shared", { includeTests: false }),
    readProjectRelative("ecommerce_cs_agent/api/app.py"),
    readProjectRelative("ecommerce_cs_agent/services/admin.py"),
    readProjectRelative("ecommerce_cs_agent/services/admin_auth.py"),
    readProjectRelative("ecommerce_cs_agent/services/system_admin.py")
  ].join("\n");

  assertNoAdminDemoFallback(source);
});

test("demo fallback guard rejects an isolated forbidden seed", () => {
  assert.throws(
    () => assertNoAdminDemoFallback('const organization = { name: "Demo Organization" };'),
    /Demo Organization/
  );
});

test("renamed test seed guard still rejects an isolated fake business fixture", () => {
  assert.throws(
    () => assertNoAdminDemoFallback('self.organizations = {"org-001": {"name": "Test Organization"}}'),
    /Test Organization/
  );
});

test("in-memory Admin production classes default to empty collections and factories fail fast outside test", () => {
  const adminAuth = readProjectRelative("ecommerce_cs_agent/services/admin_auth.py");
  const systemAdmin = readProjectRelative("ecommerce_cs_agent/services/system_admin.py");
  const adminData = readProjectRelative("ecommerce_cs_agent/services/admin.py");
  const customerInMemory = sliceBetween(adminAuth, "class InMemoryAdminAuthService", "class PostgresAdminAuthService");
  const systemInMemoryAuth = sliceBetween(adminAuth, "class InMemorySystemAdminAuthService", "class PostgresSystemAdminAuthService");
  const customerFactory = sliceBetween(adminAuth, "def admin_auth_service_for", "def system_admin_auth_service_for");
  const customerDataFactory = adminData.slice(adminData.indexOf("def admin_repository_for"), adminData.indexOf("def _object_storage_for"));
  const systemInMemoryRepository = sliceBetween(systemAdmin, "class InMemorySystemAdminRepository", "class PostgresSystemAdminRepository");

  for (const marker of ["self.organizations = {}", "self.stores = {}", "self.users = {}", "self.sessions = {}"]) {
    assert.match(customerInMemory, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(systemInMemoryAuth, /self\.users = \{\}/);
  assert.match(systemInMemoryAuth, /self\.sessions = \{\}/);
  assert.match(systemInMemoryRepository, /self\.users = \{\}/);
  assert.match(systemInMemoryRepository, /self\.organizations = \{\}/);
  assert.match(systemInMemoryRepository, /self\.stores = \{\}/);
  assert.match(customerFactory, /if settings\.environment\.lower\(\) == "test"/);
  assert.match(customerFactory, /raise RuntimeError\("DATABASE_URL is required for Customer Admin outside test"\)/);
  assert.match(customerDataFactory, /if settings\.environment\.lower\(\) == "test"/);
  assert.match(customerDataFactory, /raise RuntimeError\("DATABASE_URL is required for Customer Admin data outside test"\)/);
});

test("LLM governance UI accepts Kubernetes Secret references but no raw secret fields", () => {
  const source = [
    readRelative("system-admin/src/pages/LlmGovernancePage.tsx"),
    readRelative("system-admin/src/pages/ReleasesPage.tsx")
  ].join("\n");

  assertLlmUiUsesSecretReferencesOnly(source);
});

test("LLM raw-secret source guard rejects an isolated forbidden field", () => {
  assert.throws(
    () => assertLlmUiUsesSecretReferencesOnly("const form = { secret_value: value };"),
    /secret_value/
  );
});

test("LLM raw-secret guard rejects camelCase form fields even when unrelated Secret markers exist", () => {
  const mutant = `
    const unrelated = { secret_ref, secret_name, secret_key };
    return <label>API key<input name="apiKey" /></label>;
  `;

  assert.throws(() => assertLlmUiUsesSecretReferencesOnly(mutant), /apiKey/);
});

test("LLM raw-secret guard accepts only concrete Kubernetes Secret reference controls and rendering", () => {
  const safeFixture = `
    <label>Secret namespace<input value={form.namespace} /></label>
    <label>Secret name<input value={form.secret_name} /></label>
    <label>Secret key<input value={form.secret_key} /></label>
    <span>{provider.secret_ref.namespace}/{provider.secret_ref.name}:{provider.secret_ref.key}</span>
  `;

  assert.doesNotThrow(() => assertLlmUiUsesSecretReferencesOnly(safeFixture));
});

test("Provider credential boundary keeps the real DOM allowlist regression and stable panel locator", () => {
  const providerPage = readRelative("system-admin/src/pages/LlmGovernancePage.tsx");
  const regression = readRelative("system-admin/src/system-admin.test.tsx");
  const packageJson = JSON.parse(readRelative("package.json"));

  assert.match(providerPage, /data-testid="llm-provider-panel"/);
  assert.match(regression, /allowlists the exact Provider create and edit controls across the real rendered panel/);
  assert.match(regression, /querySelectorAll<[^>]+>\("input, select, textarea"\)/);
  assert.match(regression, /APPROVED_PROVIDER_CREATE_CONTROLS/);
  assert.match(regression, /APPROVED_PROVIDER_UPDATE_CONTROLS/);
  assert.match(regression, /providerControlMutant/);
  assert.match(regression, /"credential", "密钥值"/);
  assert.match(packageJson.scripts.test, /system-admin\/src\/system-admin\.test\.tsx/);
});

test("System Admin production AST rejects raw credential fields with an auth-login-only password exception", () => {
  for (const file of collectSourceFiles("system-admin/src", { includeTests: false })) {
    assertNoRawCredentialAst(readFileSync(file, "utf8"), file);
  }
  assert.doesNotThrow(() => assertNoRawCredentialAst("// password is handled only by auth\nconst note = 'password is never an LLM field';", "comment.ts"));
  assert.doesNotThrow(() => assertNoRawCredentialAst("const login = async (email, password) => ({ email, password });", "auth.ts"));
});

test("System Admin AST credential guard rejects API, type, and child-component mutants", () => {
  const mutants = [
    ["system-api.ts", "export const systemApi = { createLlmProvider: (credential_value: string) => credential_value };"],
    ["system-types.ts", "export type LlmProvider = { credential_value: string };"],
    ["LlmProviderChild.tsx", "export const Child = () => <input name=\"credential_value\" />;"],
  ];
  for (const [file, source] of mutants) {
    assert.throws(() => assertNoRawCredentialAst(source, file), /credential_value/);
  }
});

test("shared components do not import System Admin request-state types", () => {
  const sharedComponents = readRelative("shared/components.tsx");
  const systemTypes = readRelative("system-admin/src/system-types.ts");

  assert.doesNotMatch(sharedComponents, /system-admin\/src/);
  assert.match(systemTypes, /export type RequestState/);
});

test("runtime workspace detection is removed from admin web sources", () => {
  const source = [
    collectSource("customer-admin/src"),
    collectSource("system-admin/src"),
    existsSync(repoPath("shared")) ? collectSource("shared") : ""
  ].join("\n");

  assert.doesNotMatch(source, /detectWorkspaceFromLocation/);
  assert.doesNotMatch(source, /workspace === "customer"/);
  assert.doesNotMatch(source, /workspace === "system"/);
});
