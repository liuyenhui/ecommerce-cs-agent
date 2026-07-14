import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";

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
  assert.doesNotMatch(source, /Demo Organization|Demo PDD Store/);
  assert.doesNotMatch(source, /(?:demo|sample|fake)[_-]?(?:organization|tenant|store|admin)[_-]?(?:fallback|default|seed)?/i);
}

function assertLlmUiUsesSecretReferencesOnly(source) {
  assert.doesNotMatch(source, /\b(?:secret_value|api_key|raw_secret)\b/i);
  assert.match(source, /secret_ref/);
  assert.match(source, /secret_name/);
  assert.match(source, /secret_key/);
}

function collectSource(dir, { includeTests = true } = {}) {
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
  return files.map((file) => `\n/* ${path.relative(adminRoot, file)} */\n${readFileSync(file, "utf8")}`).join("\n");
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

test("LLM governance UI accepts Kubernetes Secret references but no raw secret fields", () => {
  const source = collectSource("system-admin/src", { includeTests: false });

  assertLlmUiUsesSecretReferencesOnly(source);
});

test("LLM raw-secret source guard rejects an isolated forbidden field", () => {
  assert.throws(
    () => assertLlmUiUsesSecretReferencesOnly("const form = { secret_value: value, secret_ref, secret_name, secret_key };"),
    /secret_value/
  );
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
