#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import {
  closeSync,
  fchmodSync,
  fstatSync,
  lstatSync,
  mkdirSync,
  openSync,
  realpathSync,
  unlinkSync,
  writeFileSync
} from "node:fs";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
  sep
} from "node:path";
import { fileURLToPath } from "node:url";

import {
  defaultAdminCredentialsFile,
  initializeAdminCredentialFile,
  loadAdminCredentialFile,
  mergeAdminCredentialSources,
} from "./admin_web_credentials.mjs";

const REPOSITORY_ROOT = fileURLToPath(new URL("..", import.meta.url));

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
It writes Playwright-compatible storageState files under a 0700 directory with mode 0600.

Options:
  --namespace <name>       Kubernetes namespace. Default: ${DEFAULTS.namespace}
  --secret <name>          Runtime Secret name. Default: ${DEFAULTS.secret}
  --kubeconfig <path>      kubeconfig path. Default: ${DEFAULTS.kubeconfig}
  --customer-url <url>     Customer Admin URL. Default: ${DEFAULTS.customerUrl}
  --system-url <url>       System Admin URL. Default: ${DEFAULTS.systemUrl}
  --organization-id <id>   Customer organization_id. Default: ${DEFAULTS.organizationId}
  --output-dir <path>      Output directory. Default: /tmp/ecommerce-admin-auth-<timestamp>
  --credentials-file <path>
                           Credential file. Default: repository-external
                           ${defaultAdminCredentialsFile()}
  --init-credentials-file  Create the selected credential file and parent with
                           modes 0600 and 0700, then exit without logging in.
  --skip-kubectl           Only use CUSTOMER_ADMIN_* and SYSTEM_ADMIN_* env vars.
  -h, --help               Show this help.

Credential precedence:
  Non-empty environment values override the credential file. Kubernetes Secret
  fallback remains available unless --skip-kubectl is set.

Environment values:
  CUSTOMER_ADMIN_EMAIL
  CUSTOMER_ADMIN_PASSWORD
  SYSTEM_ADMIN_EMAIL
  SYSTEM_ADMIN_PASSWORD

Notes:
  - Secret password hashes are only usable when stored as plain:<password>.
  - If a password is hashed, pass the plaintext through the corresponding env var.
  - Never paste passwords into chat or commit the credential file.
  - The generated storageState files contain session cookies. Do not commit or share them.
`);
}

function parseArgs(argv) {
  const valueFlags = {
    "--namespace": "namespace",
    "--secret": "secret",
    "--kubeconfig": "kubeconfig",
    "--customer-url": "customerUrl",
    "--system-url": "systemUrl",
    "--organization-id": "organizationId",
    "--output-dir": "outputDir",
    "--credentials-file": "credentialsFile"
  };
  const recognizedOptions = new Set([
    "-h",
    "--help",
    "--skip-kubectl",
    "--init-credentials-file",
    ...Object.keys(valueFlags)
  ]);
  const args = {
    ...DEFAULTS,
    outputDir: join("/tmp", `ecommerce-admin-auth-${new Date().toISOString().replace(/[:.]/g, "-")}`),
    skipKubectl: false,
    credentialsFile: "",
    initCredentialsFile: false
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
    if (arg === "--init-credentials-file") {
      args.initCredentialsFile = true;
      continue;
    }
    const key = valueFlags[arg];
    if (!key) throw new Error(`Unknown option: ${arg}`);
    const value = argv[index + 1];
    if (!value || recognizedOptions.has(value)) {
      throw new Error(`Missing value for ${arg}`);
    }
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

function pathEntryExists(path) {
  try {
    lstatSync(path);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

function isPathContainedBy(parentPath, candidatePath) {
  const relativePath = relative(parentPath, candidatePath);
  return (
    relativePath === ""
    || (
      relativePath !== ".."
      && !relativePath.startsWith(`..${sep}`)
      && !isAbsolute(relativePath)
    )
  );
}

function currentUserId() {
  if (typeof process.getuid !== "function") {
    throw new Error("Secure output directories require POSIX ownership support.");
  }
  return process.getuid();
}

function assertOutputDirectoryInfo(outputDir, expectedUid) {
  const info = lstatSync(outputDir);
  if (info.isSymbolicLink()) {
    throw new Error("Output directory must not be a symbolic link.");
  }
  if (!info.isDirectory()) {
    throw new Error("Output directory must be a directory.");
  }
  if (info.uid !== expectedUid) {
    throw new Error("Output directory must be owned by the current user.");
  }
  if ((info.mode & 0o777) !== 0o700) {
    throw new Error("Output directory must have mode 0700.");
  }
  return info;
}

function outputPathContext(outputDir) {
  const resolvedOutputDir = resolve(outputDir);
  if (!basename(resolvedOutputDir).startsWith("ecommerce-admin-auth-")) {
    throw new Error(
      "Output directory leaf must start with ecommerce-admin-auth-."
    );
  }

  const tmpPaths = {
    lexical: resolve("/tmp"),
    real: realpathSync("/tmp")
  };
  const repositoryPaths = {
    lexical: resolve(REPOSITORY_ROOT),
    real: realpathSync(REPOSITORY_ROOT)
  };
  if (
    isPathContainedBy(repositoryPaths.lexical, resolvedOutputDir)
    || isPathContainedBy(repositoryPaths.real, resolvedOutputDir)
  ) {
    throw new Error("Output directory must be outside the repository.");
  }

  const isLexicallyUnderTmp =
    isPathContainedBy(tmpPaths.lexical, resolvedOutputDir)
    || isPathContainedBy(tmpPaths.real, resolvedOutputDir);
  if (!isLexicallyUnderTmp) {
    throw new Error("Output directory must be under /tmp.");
  }

  const canonicalCandidate = isPathContainedBy(
    tmpPaths.lexical,
    resolvedOutputDir
  )
    ? resolve(
        tmpPaths.real,
        relative(tmpPaths.lexical, resolvedOutputDir)
      )
    : resolvedOutputDir;
  if (isPathContainedBy(repositoryPaths.real, canonicalCandidate)) {
    throw new Error("Output directory must be outside the repository.");
  }

  const lexicalParent = dirname(resolvedOutputDir);
  if (
    lexicalParent !== tmpPaths.lexical
    && lexicalParent !== tmpPaths.real
  ) {
    throw new Error("Output directory must be a direct child of /tmp.");
  }
  const realParent = realpathSync(lexicalParent);
  if (realParent !== tmpPaths.real) {
    throw new Error("Output directory parent must resolve to /tmp.");
  }

  const expectedRealPath = join(realParent, basename(resolvedOutputDir));
  if (isPathContainedBy(repositoryPaths.real, expectedRealPath)) {
    throw new Error("Output directory must be outside the repository.");
  }
  return {
    expectedRealPath,
    expectedUid: currentUserId(),
    path: resolvedOutputDir
  };
}

function preflightOutputDirectory(outputDir) {
  const context = outputPathContext(outputDir);
  if (!pathEntryExists(context.path)) {
    return { ...context, existed: false };
  }

  const info = assertOutputDirectoryInfo(context.path, context.expectedUid);
  if (realpathSync(context.path) !== context.expectedRealPath) {
    throw new Error("Output directory must resolve directly under /tmp.");
  }
  return {
    ...context,
    dev: info.dev,
    existed: true,
    ino: info.ino
  };
}

function prepareOutputDirectory(preflight) {
  if (!preflight.existed) {
    try {
      mkdirSync(preflight.path, { recursive: false, mode: 0o700 });
    } catch (error) {
      if (error?.code === "EEXIST") {
        throw new Error("Output directory appeared after preflight.");
      }
      throw error;
    }
  }

  const info = assertOutputDirectoryInfo(preflight.path, preflight.expectedUid);
  if (
    preflight.existed
    && (info.dev !== preflight.dev || info.ino !== preflight.ino)
  ) {
    throw new Error("Output directory changed after preflight.");
  }
  if (realpathSync(preflight.path) !== preflight.expectedRealPath) {
    throw new Error("Output directory must resolve directly under /tmp.");
  }
  return {
    ...preflight,
    dev: info.dev,
    ino: info.ino
  };
}

function revalidateOutputDirectory(prepared) {
  const info = assertOutputDirectoryInfo(prepared.path, prepared.expectedUid);
  if (info.dev !== prepared.dev || info.ino !== prepared.ino) {
    throw new Error("Output directory changed during login.");
  }
  if (realpathSync(prepared.path) !== prepared.expectedRealPath) {
    throw new Error("Output directory must resolve directly under /tmp.");
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
  if (!response.ok) {
    throw new Error(`POST ${new URL(url).pathname} failed with HTTP ${response.status}`);
  }
  const body = await readJsonResponse(response, "POST", url);
  return { response, body };
}

async function getJson(url, cookieHeader) {
  const response = await fetch(url, {
    headers: Object.fromEntries([["Cookie", cookieHeader]])
  });
  if (!response.ok) {
    throw new Error(`GET ${new URL(url).pathname} failed with HTTP ${response.status}`);
  }
  return readJsonResponse(response, "GET", url);
}

async function readJsonResponse(response, method, url) {
  try {
    return await response.json();
  } catch {
    throw new Error(
      `${method} ${new URL(url).pathname} failed with HTTP ${response.status}: invalid JSON response`
    );
  }
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

function removeCreatedStorageState(created) {
  try {
    const currentInfo = lstatSync(created.path);
    if (
      !currentInfo.isSymbolicLink()
      && currentInfo.isFile()
      && currentInfo.dev === created.dev
      && currentInfo.ino === created.ino
    ) {
      unlinkSync(created.path);
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

function cleanupCreatedStorageStates(createdStates) {
  for (const created of [...createdStates].reverse()) {
    removeCreatedStorageState(created);
  }
}

function storageStateTargets(outputDir, states) {
  return states.map(({ name, storageState }) => ({
    name,
    path: join(outputDir, `${name}.storageState.json`),
    storageState
  }));
}

function preflightStorageStateTargets(targets) {
  for (const target of targets) {
    if (pathEntryExists(target.path)) {
      throw new Error(`Storage state file already exists for ${target.name}.`);
    }
  }
}

function writeStorageState(target, expectedUid) {
  let fileDescriptor;
  let created;
  try {
    fileDescriptor = openSync(target.path, "wx", 0o600);
    const initialInfo = fstatSync(fileDescriptor);
    created = {
      dev: initialInfo.dev,
      ino: initialInfo.ino,
      path: target.path
    };
    writeFileSync(
      fileDescriptor,
      `${JSON.stringify(target.storageState, null, 2)}\n`,
      { encoding: "utf8" }
    );
    fchmodSync(fileDescriptor, 0o600);
    const finalInfo = fstatSync(fileDescriptor);
    if (
      !finalInfo.isFile()
      || finalInfo.uid !== expectedUid
      || (finalInfo.mode & 0o777) !== 0o600
      || finalInfo.dev !== created.dev
      || finalInfo.ino !== created.ino
    ) {
      throw new Error(
        `Storage state file verification failed for ${target.name}.`
      );
    }
    const descriptorToClose = fileDescriptor;
    fileDescriptor = undefined;
    try {
      closeSync(descriptorToClose);
    } catch {
      throw new Error(
        `Storage state file close failed for ${target.name}.`
      );
    }
    return created;
  } catch (error) {
    let cleanupFailed = false;
    if (fileDescriptor !== undefined) {
      const descriptorToClose = fileDescriptor;
      fileDescriptor = undefined;
      try {
        closeSync(descriptorToClose);
      } catch {
        // Cleanup by the recorded inode remains safe even if close failed.
      }
    }
    if (created) {
      try {
        removeCreatedStorageState(created);
      } catch {
        cleanupFailed = true;
      }
    }
    if (cleanupFailed) {
      throw new Error(
        `Storage state file cleanup failed for ${target.name}.`
      );
    }
    if (error?.code === "EEXIST") {
      throw new Error(`Storage state file already exists for ${target.name}.`);
    }
    throw error;
  } finally {
    if (fileDescriptor !== undefined) {
      const descriptorToClose = fileDescriptor;
      fileDescriptor = undefined;
      try {
        closeSync(descriptorToClose);
      } catch {
        let cleanupFailed = false;
        if (created) {
          try {
            removeCreatedStorageState(created);
          } catch {
            cleanupFailed = true;
          }
        }
        if (cleanupFailed) {
          throw new Error(
            `Storage state file cleanup failed for ${target.name}.`
          );
        }
        throw new Error(
          `Storage state file close failed for ${target.name}.`
        );
      }
    }
  }
}

function writeStorageStates(outputDir, states) {
  const targets = storageStateTargets(outputDir, states);
  preflightStorageStateTargets(targets);
  const createdStates = [];
  try {
    for (const target of targets) {
      createdStates.push(writeStorageState(target, currentUserId()));
    }
    return createdStates.map((created) => created.path);
  } catch (error) {
    try {
      cleanupCreatedStorageStates(createdStates);
    } catch {
      throw new Error("Storage state transaction cleanup failed.");
    }
    throw error;
  }
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

  const credentialsFile = args.credentialsFile || defaultAdminCredentialsFile();
  if (args.initCredentialsFile) {
    const path = initializeAdminCredentialFile({
      filePath: credentialsFile,
      repositoryRoot: REPOSITORY_ROOT
    });
    console.log(JSON.stringify(
      {
        ok: true,
        path,
        warning: "Keep this local file private and uncommitted."
      },
      null,
      2
    ));
    return;
  }

  const outputPreflight = preflightOutputDirectory(args.outputDir);

  const fileCredentials =
    args.credentialsFile || pathEntryExists(credentialsFile)
      ? loadAdminCredentialFile({
          filePath: credentialsFile,
          repositoryRoot: REPOSITORY_ROOT
        })
      : {};
  const credentials = mergeAdminCredentialSources(fileCredentials, process.env);

  const customerEmail = credentials.CUSTOMER_ADMIN_EMAIL || (!args.skipKubectl ? kubectlSecretValue(args, "ADMIN_INITIAL_EMAIL") : "");
  const customerHash = !credentials.CUSTOMER_ADMIN_PASSWORD && !args.skipKubectl
    ? kubectlSecretValue(args, "ADMIN_INITIAL_PASSWORD_HASH")
    : "";
  const customerPassword = passwordFromHash("customer admin", customerHash, credentials.CUSTOMER_ADMIN_PASSWORD);

  const systemEmail = credentials.SYSTEM_ADMIN_EMAIL
    || (!args.skipKubectl ? kubectlSecretValue(args, "SYSTEM_ADMIN_INITIAL_EMAIL") : "")
    || customerEmail;
  const systemHash = !credentials.SYSTEM_ADMIN_PASSWORD && !args.skipKubectl
    ? kubectlSecretValue(args, "SYSTEM_ADMIN_INITIAL_PASSWORD_HASH")
    : "";
  const systemPassword = credentials.SYSTEM_ADMIN_PASSWORD
    || (systemHash ? passwordFromHash("system admin", systemHash, "") : customerPassword);

  const preparedOutput = prepareOutputDirectory(outputPreflight);
  const outputDir = preparedOutput.path;

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

  revalidateOutputDirectory(preparedOutput);
  const [customerStatePath, systemStatePath] = writeStorageStates(
    outputDir,
    [
      { name: "customer-admin", storageState: customer.storageState },
      { name: "system-admin", storageState: system.storageState }
    ]
  );

  console.log(JSON.stringify(
    {
      ok: true,
      outputDir,
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
