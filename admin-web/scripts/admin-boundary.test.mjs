import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const adminRoot = path.resolve(scriptDir, "..");

function repoPath(...parts) {
  return path.join(adminRoot, ...parts);
}

function readRelative(file) {
  return readFileSync(repoPath(file), "utf8");
}

function collectSource(dir) {
  const root = repoPath(dir);
  assert.ok(existsSync(root), `${dir} must exist`);
  const files = [];
  const walk = (current) => {
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      const next = path.join(current, entry.name);
      if (entry.isDirectory()) {
        walk(next);
      } else if (/\.(tsx?|css)$/.test(entry.name)) {
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

test("customer admin login page keeps customer-only email password and fcihome account entry", () => {
  const customerApp = readRelative("customer-admin/src/App.tsx");
  const sharedComponents = readRelative("shared/components.tsx");
  const loginRoute = sliceBetween(customerApp, 'if (path === "/login")', 'if (path.startsWith("/admin"))');
  const loginPanel = sliceBetween(sharedComponents, "export function LoginPanelBase", "function loginFailureMessage");
  const loginSource = `${loginRoute}\n${loginPanel}`;

  assert.match(loginSource, /客户后台登录/);
  assert.match(loginSource, /使用 Fcihome Account 登录/);
  assert.match(loginSource, /\/v1\/admin\/auth\/oidc\/start/);
  assert.match(loginSource, /邮箱/);
  assert.match(loginSource, /密码/);
  assert.doesNotMatch(loginSource, /组织 ID/);
  assert.doesNotMatch(loginSource, /\borganization\b/i);
  assert.doesNotMatch(loginSource, /org-001/);
  assert.doesNotMatch(loginSource, /system-admin/i);
});

test("system admin source stays inside system auth boundary", () => {
  const source = collectSource("system-admin/src");

  assert.match(source, /\/v1\/system-admin\/auth\/me/);
  assert.doesNotMatch(source, /\/v1\/admin\/auth\/me/);
  assert.doesNotMatch(source, /agent_admin_session/);
  assert.doesNotMatch(source, /\b(CustomerSite|CustomerAdminShell|CustomerWorkspace|CustomerOverview|ProductContent|KnowledgeReview|ProductUploadModal)\b/);
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
