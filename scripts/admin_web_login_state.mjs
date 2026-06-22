#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync, chmodSync } from "node:fs";
import { join } from "node:path";

const DEFAULTS = {
  namespace: "ecommerce-cs-agent-dev",
  secret: "ecommerce-cs-agent-runtime",
  kubeconfig: `${process.env.HOME || ""}/.kube/bpg-debian12-master-public.yaml`,
  customerUrl: "https://admin.ecommerce-cs-agent-dev.fcihome.com",
  systemUrl: "https://system-admin.ecommerce-cs-agent-dev.fcihome.com",
  organizationId: "org-001"
};

function usage() {
  console.log(`Usage: node scripts/admin_web_login_state.mjs [options]

Logs in to Customer Admin and System Admin without printing credentials or cookies.
It writes Playwright-compatible storageState files with mode 0600.

Options:
  --namespace <name>       Kubernetes namespace. Default: ${DEFAULTS.namespace}
  --secret <name>          Runtime Secret name. Default: ${DEFAULTS.secret}
  --kubeconfig <path>      kubeconfig path. Default: ${DEFAULTS.kubeconfig}
  --customer-url <url>     Customer Admin URL. Default: ${DEFAULTS.customerUrl}
  --system-url <url>       System Admin URL. Default: ${DEFAULTS.systemUrl}
  --organization-id <id>   Customer organization_id. Default: ${DEFAULTS.organizationId}
  --output-dir <path>      Output directory. Default: /tmp/ecommerce-admin-auth-<timestamp>
  --skip-kubectl           Only use CUSTOMER_ADMIN_* and SYSTEM_ADMIN_* env vars.
  -h, --help               Show this help.

Environment overrides:
  CUSTOMER_ADMIN_EMAIL
  CUSTOMER_ADMIN_PASSWORD
  SYSTEM_ADMIN_EMAIL
  SYSTEM_ADMIN_PASSWORD

Notes:
  - Secret password hashes are only usable when stored as plain:<password>.
  - If a password is hashed, pass the plaintext through the corresponding env var.
  - The generated storageState files contain session cookies. Do not commit or share them.
`);
}

function parseArgs(argv) {
  const args = {
    ...DEFAULTS,
    outputDir: join("/tmp", `ecommerce-admin-auth-${new Date().toISOString().replace(/[:.]/g, "-")}`),
    skipKubectl: false
  };
  for (let index = 2; index < argv.length; index += 1) {
    const arg = argv[index];
    if (arg === "-h" || arg === "--help") {
      args.help = true;
      continue;
    }
    if (arg === "--skip-kubectl") {
      args.skipKubectl = true;
      continue;
    }
    const valueFlags = {
      "--namespace": "namespace",
      "--secret": "secret",
      "--kubeconfig": "kubeconfig",
      "--customer-url": "customerUrl",
      "--system-url": "systemUrl",
      "--organization-id": "organizationId",
      "--output-dir": "outputDir"
    };
    const key = valueFlags[arg];
    if (!key) throw new Error(`Unknown option: ${arg}`);
    const value = argv[index + 1];
    if (!value) throw new Error(`Missing value for ${arg}`);
    args[key] = value;
    index += 1;
  }
  return args;
}

function kubectlSecretValue(args, key) {
  try {
    const encoded = execFileSync(
      "kubectl",
      [
        "--kubeconfig",
        args.kubeconfig,
        "-n",
        args.namespace,
        "get",
        "secret",
        args.secret,
        "-o",
        `jsonpath={.data.${key}}`
      ],
      { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
    ).trim();
    if (!encoded) return "";
    return Buffer.from(encoded, "base64").toString("utf8");
  } catch (error) {
    throw new Error(`Failed to read Secret key ${key}. Check kubeconfig, namespace, and Secret name.`);
  }
}

function passwordFromHash(label, hash, envPassword) {
  if (envPassword) return envPassword;
  if (!hash) throw new Error(`${label} password is missing. Set ${label.toUpperCase().replaceAll(" ", "_")}_PASSWORD.`);
  if (hash.startsWith("plain:")) return hash.slice("plain:".length);
  throw new Error(`${label} password is hashed and cannot be recovered. Pass plaintext with env var.`);
}

function normalizeBaseUrl(url) {
  return url.replace(/\/+$/, "");
}

function cookieLines(headers) {
  if (typeof headers.getSetCookie === "function") return headers.getSetCookie();
  const single = headers.get("set-cookie");
  return single ? [single] : [];
}

function parseCookies(setCookieLines, domain) {
  return setCookieLines.map((line) => {
    const parts = line.split(";").map((part) => part.trim());
    const [name, ...valueParts] = parts[0].split("=");
    const lower = new Map(parts.slice(1).map((part) => {
      const [key, ...value] = part.split("=");
      return [key.toLowerCase(), value.join("=") || true];
    }));
    return {
      name,
      value: valueParts.join("="),
      domain,
      path: typeof lower.get("path") === "string" ? lower.get("path") : "/",
      expires: -1,
      httpOnly: lower.has("httponly"),
      secure: lower.has("secure"),
      sameSite: "Lax"
    };
  });
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    redirect: "manual"
  });
  const body = await safeRead(response);
  if (!response.ok) {
    throw new Error(`POST ${url} failed with ${response.status}: ${summarizeBody(body)}`);
  }
  return { response, body };
}

async function getJson(url, cookieHeader) {
  const response = await fetch(url, {
    headers: Object.fromEntries([["Cookie", cookieHeader]])
  });
  const body = await safeRead(response);
  if (!response.ok) {
    throw new Error(`GET ${url} failed with ${response.status}: ${summarizeBody(body)}`);
  }
  return body;
}

async function safeRead(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return response.json();
  return response.text();
}

function summarizeBody(body) {
  if (typeof body === "string") return body.slice(0, 160);
  if (body && typeof body === "object" && "error" in body) {
    const error = body.error;
    if (error && typeof error === "object" && "message" in error) return String(error.message).slice(0, 160);
  }
  return JSON.stringify(body).slice(0, 160);
}

async function loginAdmin(kind, baseUrl, payload, expectedCookieName) {
  const origin = normalizeBaseUrl(baseUrl);
  const hostname = new URL(origin).hostname;
  const loginPath = kind === "customer" ? "/v1/admin/auth/login" : "/v1/system-admin/auth/login";
  const mePath = kind === "customer" ? "/v1/admin/auth/me" : "/v1/system-admin/auth/me";
  const { response } = await postJson(`${origin}${loginPath}`, payload);
  const cookies = parseCookies(cookieLines(response.headers), hostname);
  const sessionCookie = cookies.find((cookie) => cookie.name === expectedCookieName);
  if (!sessionCookie) throw new Error(`${kind} login did not return expected cookie ${expectedCookieName}`);
  const cookieHeader = `${sessionCookie.name}=${sessionCookie.value}`;
  const me = await getJson(`${origin}${mePath}`, cookieHeader);
  return {
    origin,
    cookieName: expectedCookieName,
    me,
    storageState: {
      cookies: [sessionCookie],
      origins: [
        {
          origin,
          localStorage: []
        }
      ]
    }
  };
}

function writeStorageState(outputDir, name, storageState) {
  const path = join(outputDir, `${name}.storageState.json`);
  writeFileSync(path, `${JSON.stringify(storageState, null, 2)}\n`, { mode: 0o600 });
  chmodSync(path, 0o600);
  return path;
}

function userSummary(me) {
  const user = me && typeof me === "object" ? me.user : null;
  if (!user || typeof user !== "object") return "authenticated";
  const email = typeof user.email === "string" ? user.email : "unknown-email";
  const role = typeof user.role === "string" ? user.role : Array.isArray(user.roles) ? user.roles.join(",") : "unknown-role";
  return `${email} (${role})`;
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    usage();
    return;
  }

  const customerEmail = process.env.CUSTOMER_ADMIN_EMAIL || (!args.skipKubectl ? kubectlSecretValue(args, "ADMIN_INITIAL_EMAIL") : "");
  const customerHash = !args.skipKubectl ? kubectlSecretValue(args, "ADMIN_INITIAL_PASSWORD_HASH") : "";
  const customerPassword = passwordFromHash("customer admin", customerHash, process.env.CUSTOMER_ADMIN_PASSWORD);

  const systemEmail = process.env.SYSTEM_ADMIN_EMAIL
    || (!args.skipKubectl ? kubectlSecretValue(args, "SYSTEM_ADMIN_INITIAL_EMAIL") : "")
    || customerEmail;
  const systemHash = (!args.skipKubectl ? kubectlSecretValue(args, "SYSTEM_ADMIN_INITIAL_PASSWORD_HASH") : "") || customerHash;
  const systemPassword = passwordFromHash("system admin", systemHash, process.env.SYSTEM_ADMIN_PASSWORD);

  mkdirSync(args.outputDir, { recursive: true, mode: 0o700 });
  chmodSync(args.outputDir, 0o700);

  const customer = await loginAdmin(
    "customer",
    args.customerUrl,
    {
      email: customerEmail,
      password: customerPassword,
      organization_id: args.organizationId
    },
    "agent_admin_session"
  );
  const system = await loginAdmin(
    "system",
    args.systemUrl,
    {
      email: systemEmail,
      password: systemPassword
    },
    "agent_system_admin_session"
  );

  const customerStatePath = writeStorageState(args.outputDir, "customer-admin", customer.storageState);
  const systemStatePath = writeStorageState(args.outputDir, "system-admin", system.storageState);

  console.log(JSON.stringify(
    {
      ok: true,
      outputDir: args.outputDir,
      customer: {
        url: args.customerUrl,
        authMe: "PASS",
        user: userSummary(customer.me),
        storageStatePath: customerStatePath
      },
      system: {
        url: args.systemUrl,
        authMe: "PASS",
        user: userSummary(system.me),
        storageStatePath: systemStatePath
      },
      warning: "storageState files contain session cookies. Keep them local, chmod 600, and delete them after testing."
    },
    null,
    2
  ));
}

main().catch((error) => {
  console.error(`admin web login state failed: ${error.message}`);
  process.exit(1);
});
