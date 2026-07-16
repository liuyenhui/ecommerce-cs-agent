import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import fs, {
  chmodSync,
  copyFileSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  renameSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { createServer } from "node:http";
import { syncBuiltinESMExports } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  ADMIN_CREDENTIAL_KEYS,
  ADMIN_CREDENTIAL_TEMPLATE,
  assertSecureAdminCredentialFile,
  defaultAdminCredentialsFile,
  initializeAdminCredentialFile,
  loadAdminCredentialFile,
  mergeAdminCredentialSources,
  parseAdminCredentialText,
} from "./admin_web_credentials.mjs";

const PROJECT_ROOT = fileURLToPath(new URL("..", import.meta.url));

const completeText = `CUSTOMER_ADMIN_EMAIL="customer@example.test"
CUSTOMER_ADMIN_PASSWORD="customer pass; $HOME # inert"
SYSTEM_ADMIN_EMAIL="system@example.test"
SYSTEM_ADMIN_PASSWORD="system pass && echo inert"
`;

async function withLoginStateCliSandbox(run) {
  const sandbox = mkdtempSync(join(tmpdir(), "admin-web-login-state-cli-"));
  const repositoryRoot = join(sandbox, "repository");
  const scriptsDirectory = join(repositoryRoot, "scripts");
  const credentialFile = join(
    sandbox,
    "external-credentials",
    "admin-test-credentials.env",
  );
  const kubectlMarker = join(sandbox, "kubectl-was-called");
  const fakeBin = join(sandbox, "bin");
  mkdirSync(scriptsDirectory, { recursive: true });
  mkdirSync(fakeBin);
  copyFileSync(
    join(PROJECT_ROOT, "scripts", "admin_web_login_state.mjs"),
    join(scriptsDirectory, "admin_web_login_state.mjs"),
  );
  copyFileSync(
    join(PROJECT_ROOT, "scripts", "admin_web_credentials.mjs"),
    join(scriptsDirectory, "admin_web_credentials.mjs"),
  );
  writeFileSync(
    join(fakeBin, "kubectl"),
    `#!/bin/sh\n: > "${kubectlMarker}"\nexit 97\n`,
    { mode: 0o700 },
  );

  function runCli(args, options = {}) {
    const environment = { ...process.env };
    for (const key of ADMIN_CREDENTIAL_KEYS) {
      delete environment[key];
    }
    return spawnSync(
      process.execPath,
      [join(scriptsDirectory, "admin_web_login_state.mjs"), ...args],
      {
        cwd: repositoryRoot,
        encoding: "utf8",
        env: {
          ...environment,
          PATH: `${fakeBin}:${process.env.PATH || ""}`,
          ...options.env,
        },
      },
    );
  }

  function runCliAsync(args, options = {}) {
    const environment = { ...process.env };
    for (const key of ADMIN_CREDENTIAL_KEYS) {
      delete environment[key];
    }
    return new Promise((resolveRun, rejectRun) => {
      const child = spawn(
        process.execPath,
        [join(scriptsDirectory, "admin_web_login_state.mjs"), ...args],
        {
          cwd: repositoryRoot,
          env: {
            ...environment,
            PATH: `${fakeBin}:${process.env.PATH || ""}`,
            ...options.env,
          },
          stdio: ["ignore", "pipe", "pipe"],
        },
      );
      let stdout = "";
      let stderr = "";
      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");
      child.stdout.on("data", (chunk) => {
        stdout += chunk;
      });
      child.stderr.on("data", (chunk) => {
        stderr += chunk;
      });
      child.once("error", rejectRun);
      child.once("close", (status, signal) => {
        resolveRun({ status, signal, stdout, stderr });
      });
    });
  }

  try {
    return await run({
      sandbox,
      repositoryRoot,
      credentialFile,
      kubectlMarker,
      runCli,
      runCliAsync,
    });
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
}

async function withLocalHttpServer(handler, run) {
  const server = createServer(handler);
  await new Promise((resolveListen, rejectListen) => {
    server.once("error", rejectListen);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  assert.notEqual(address, null);
  assert.equal(typeof address, "object");

  try {
    return await run(`http://127.0.0.1:${address.port}`);
  } finally {
    await new Promise((resolveClose, rejectClose) => {
      server.close((error) => {
        if (error) rejectClose(error);
        else resolveClose();
      });
    });
  }
}

async function readRequestJson(request) {
  const chunks = [];
  for await (const chunk of request) {
    chunks.push(chunk);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

test("CLI initializes an external owner-only credential file before side effects", async () => {
  await withLoginStateCliSandbox(({ credentialFile, kubectlMarker, runCli }) => {
    const environmentCredentialValues = {
      CUSTOMER_ADMIN_EMAIL: "customer-init-value-never-print",
      CUSTOMER_ADMIN_PASSWORD: "customer-init-secret-never-print",
      SYSTEM_ADMIN_EMAIL: "system-init-value-never-print",
      SYSTEM_ADMIN_PASSWORD: "system-init-secret-never-print",
    };
    const first = runCli([
      "--credentials-file",
      credentialFile,
      "--init-credentials-file",
      "--customer-url",
      "http://127.0.0.1:1",
      "--system-url",
      "http://127.0.0.1:1",
    ], {
      env: environmentCredentialValues,
    });

    assert.equal(first.status, 0, first.stderr);
    assert.equal(first.signal, null);
    assert.equal(lstatSync(dirname(credentialFile)).mode & 0o777, 0o700);
    assert.equal(lstatSync(credentialFile).mode & 0o777, 0o600);
    assert.equal(readFileSync(credentialFile, "utf8"), ADMIN_CREDENTIAL_TEMPLATE);
    assert.throws(() => lstatSync(kubectlMarker), { code: "ENOENT" });

    const output = `${first.stdout}\n${first.stderr}`;
    assert.doesNotMatch(output, /password|cookie/iu);
    for (const key of ADMIN_CREDENTIAL_KEYS) {
      assert.equal(output.includes(key), false);
    }
    assert.deepEqual(
      Object.entries(environmentCredentialValues)
        .filter(([, value]) => output.includes(value))
        .map(([key]) => key),
      [],
    );

    const parsed = JSON.parse(first.stdout);
    assert.deepEqual(Object.keys(parsed).sort(), ["ok", "path", "warning"]);
    assert.equal(parsed.ok, true);
    assert.equal(parsed.path, resolve(credentialFile));

    const second = runCli([
      "--credentials-file",
      credentialFile,
      "--init-credentials-file",
    ]);
    assert.notEqual(second.status, 0);
    assert.match(second.stderr, /already exists/u);
    assert.equal(readFileSync(credentialFile, "utf8"), ADMIN_CREDENTIAL_TEMPLATE);
    assert.throws(() => lstatSync(kubectlMarker), { code: "ENOENT" });
  });
});

test("CLI uses a secure file for isolated Customer and System login states", async () => {
  await withLoginStateCliSandbox(
    async ({
      sandbox,
      repositoryRoot,
      credentialFile,
      kubectlMarker,
      runCliAsync,
    }) => {
      const customerEmail = "customer-cli@example.test";
      const customerPassword = "customer-cli-password-secret";
      const systemEmail = "system-cli@example.test";
      const systemPassword = "system-cli-password-secret";
      const customerCookieValue = "customer-cookie-secret";
      const systemCookieValue = "system-cookie-secret";
      const outputDir = join(sandbox, "login-state");
      const customerRequests = [];
      const systemRequests = [];

      initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot });
      writeFileSync(
        credentialFile,
        `CUSTOMER_ADMIN_EMAIL=${customerEmail}
CUSTOMER_ADMIN_PASSWORD=${customerPassword}
SYSTEM_ADMIN_EMAIL=${systemEmail}
SYSTEM_ADMIN_PASSWORD=${systemPassword}
`,
        "utf8",
      );
      chmodSync(credentialFile, 0o600);

      await withLocalHttpServer(async (request, response) => {
        const pathname = new URL(request.url, "http://customer.test").pathname;
        response.setHeader("Content-Type", "application/json");
        if (
          request.method === "POST" &&
          pathname === "/v1/admin/auth/login"
        ) {
          const payload = await readRequestJson(request);
          customerRequests.push({
            method: request.method,
            pathname,
            payloadMatches:
              payload.email === customerEmail &&
              payload.password === customerPassword &&
              payload.organization_id === "org-001",
          });
          response.setHeader(
            "Set-Cookie",
            `agent_admin_session=${customerCookieValue}; Path=/; HttpOnly`,
          );
          response.end("{}");
          return;
        }
        if (request.method === "GET" && pathname === "/v1/admin/auth/me") {
          customerRequests.push({
            method: request.method,
            pathname,
            cookieMatches:
              request.headers.cookie ===
              `agent_admin_session=${customerCookieValue}`,
          });
          response.end(
            JSON.stringify({
              user: { email: customerEmail, role: "fixture" },
            }),
          );
          return;
        }
        customerRequests.push({
          method: request.method,
          pathname,
          rejected: true,
        });
        response.statusCode = 404;
        response.end("{}");
      }, async (customerOrigin) => {
        await withLocalHttpServer(async (request, response) => {
          const pathname = new URL(request.url, "http://system.test").pathname;
          response.setHeader("Content-Type", "application/json");
          if (
            request.method === "POST" &&
            pathname === "/v1/system-admin/auth/login"
          ) {
            const payload = await readRequestJson(request);
            systemRequests.push({
              method: request.method,
              pathname,
              payloadMatches:
                payload.email === systemEmail &&
                payload.password === systemPassword &&
                !Object.hasOwn(payload, "organization_id"),
            });
            response.setHeader(
              "Set-Cookie",
              `agent_system_admin_session=${systemCookieValue}; Path=/; HttpOnly`,
            );
            response.end("{}");
            return;
          }
          if (
            request.method === "GET" &&
            pathname === "/v1/system-admin/auth/me"
          ) {
            systemRequests.push({
              method: request.method,
              pathname,
              cookieMatches:
                request.headers.cookie ===
                `agent_system_admin_session=${systemCookieValue}`,
            });
            response.end(
              JSON.stringify({
                user: { email: systemEmail, role: "fixture" },
              }),
            );
            return;
          }
          systemRequests.push({
            method: request.method,
            pathname,
            rejected: true,
          });
          response.statusCode = 404;
          response.end("{}");
        }, async (systemOrigin) => {
          assert.notEqual(customerOrigin, systemOrigin);
          const result = await runCliAsync([
            "--credentials-file",
            credentialFile,
            "--skip-kubectl",
            "--customer-url",
            customerOrigin,
            "--system-url",
            systemOrigin,
            "--output-dir",
            outputDir,
          ]);

          assert.equal(result.status, 0, result.stderr);
          assert.equal(result.signal, null);
          assert.throws(() => lstatSync(kubectlMarker), { code: "ENOENT" });
          assert.equal(lstatSync(outputDir).mode & 0o777, 0o700);

          const customerStatePath = join(
            outputDir,
            "customer-admin.storageState.json",
          );
          const systemStatePath = join(
            outputDir,
            "system-admin.storageState.json",
          );
          assert.equal(lstatSync(customerStatePath).mode & 0o777, 0o600);
          assert.equal(lstatSync(systemStatePath).mode & 0o777, 0o600);

          const customerState = JSON.parse(
            readFileSync(customerStatePath, "utf8"),
          );
          const systemState = JSON.parse(
            readFileSync(systemStatePath, "utf8"),
          );
          assert.deepEqual(
            {
              customerCookieCount: customerState.cookies.length,
              customerCookieNameMatches:
                customerState.cookies[0]?.name === "agent_admin_session",
              customerCookieValueMatches:
                customerState.cookies[0]?.value === customerCookieValue,
              customerOriginMatches:
                customerState.origins[0]?.origin === customerOrigin,
              systemCookieCount: systemState.cookies.length,
              systemCookieNameMatches:
                systemState.cookies[0]?.name === "agent_system_admin_session",
              systemCookieValueMatches:
                systemState.cookies[0]?.value === systemCookieValue,
              systemOriginMatches:
                systemState.origins[0]?.origin === systemOrigin,
            },
            {
              customerCookieCount: 1,
              customerCookieNameMatches: true,
              customerCookieValueMatches: true,
              customerOriginMatches: true,
              systemCookieCount: 1,
              systemCookieNameMatches: true,
              systemCookieValueMatches: true,
              systemOriginMatches: true,
            },
          );

          assert.deepEqual(customerRequests, [
            {
              method: "POST",
              pathname: "/v1/admin/auth/login",
              payloadMatches: true,
            },
            {
              method: "GET",
              pathname: "/v1/admin/auth/me",
              cookieMatches: true,
            },
          ]);
          assert.deepEqual(systemRequests, [
            {
              method: "POST",
              pathname: "/v1/system-admin/auth/login",
              payloadMatches: true,
            },
            {
              method: "GET",
              pathname: "/v1/system-admin/auth/me",
              cookieMatches: true,
            },
          ]);

          const commandOutput = `${result.stdout}\n${result.stderr}`;
          const leakedSecretKinds = [
            ["customer password", customerPassword],
            ["system password", systemPassword],
            ["customer cookie", customerCookieValue],
            ["system cookie", systemCookieValue],
          ]
            .filter(([, value]) => commandOutput.includes(value))
            .map(([kind]) => kind);
          assert.deepEqual(leakedSecretKinds, []);
        });
      });
    },
  );
});

test("CLI authentication failures expose only method, pathname, and status", async () => {
  await withLoginStateCliSandbox(
    async ({ sandbox, repositoryRoot, runCliAsync }) => {
      const echoedPassword = "auth-failure-password-secret";
      const echoedBodyMarker = "raw-auth-response-body-marker";
      const requestedPaths = [];
      const outputDir = join(sandbox, "failed-login-state");
      const homeDirectory = join(sandbox, "home");
      const credentialFile = defaultAdminCredentialsFile(homeDirectory);

      initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot });
      writeFileSync(
        credentialFile,
        `CUSTOMER_ADMIN_EMAIL=customer-failure@example.test
CUSTOMER_ADMIN_PASSWORD=${echoedPassword}
SYSTEM_ADMIN_EMAIL=system-failure@example.test
SYSTEM_ADMIN_PASSWORD=unused-system-password
`,
        "utf8",
      );
      chmodSync(credentialFile, 0o600);

      await withLocalHttpServer(async (request, response) => {
        const pathname = new URL(request.url, "http://fixture.test").pathname;
        requestedPaths.push(pathname);
        const payload = await readRequestJson(request);
        response.statusCode = 401;
        response.setHeader("Content-Type", "application/json");
        response.end(
          JSON.stringify({
            error: {
              message: `${echoedBodyMarker}: ${payload.password}`,
            },
          }),
        );
      }, async (origin) => {
        const result = await runCliAsync([
          "--skip-kubectl",
          "--customer-url",
          origin,
          "--system-url",
          origin,
          "--output-dir",
          outputDir,
        ], {
          env: { HOME: homeDirectory },
        });

        assert.notEqual(result.status, 0);
        assert.deepEqual(requestedPaths, ["/v1/admin/auth/login"]);
        const commandOutput = `${result.stdout}\n${result.stderr}`;
        const leakedSecretKinds = [
          ["submitted password", echoedPassword],
          ["response body", echoedBodyMarker],
        ]
          .filter(([, value]) => commandOutput.includes(value))
          .map(([kind]) => kind);
        assert.deepEqual(leakedSecretKinds, []);
        assert.equal(
          result.stderr.trim(),
          "admin web login state failed: POST /v1/admin/auth/login failed with HTTP 401",
        );
      });
    },
  );
});

test("CLI redacts malformed JSON from a successful login response", async () => {
  await withLoginStateCliSandbox(
    async ({ sandbox, repositoryRoot, credentialFile, runCliAsync }) => {
      const submittedPassword = "pwLGIN7";
      const responseFragment = "LGIN7";
      const outputDir = join(sandbox, "malformed-login-state");

      initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot });
      writeFileSync(
        credentialFile,
        `CUSTOMER_ADMIN_EMAIL=malformed-login@example.test
CUSTOMER_ADMIN_PASSWORD=${submittedPassword}
SYSTEM_ADMIN_EMAIL=unused-system@example.test
SYSTEM_ADMIN_PASSWORD=unused-system-password
`,
        "utf8",
      );
      chmodSync(credentialFile, 0o600);

      await withLocalHttpServer(async (request, response) => {
        const payload = await readRequestJson(request);
        response.statusCode = 200;
        response.setHeader("Content-Type", "application/json");
        response.end(`${payload.password}:${responseFragment}`);
      }, async (origin) => {
        const result = await runCliAsync([
          "--credentials-file",
          credentialFile,
          "--skip-kubectl",
          "--customer-url",
          origin,
          "--system-url",
          origin,
          "--output-dir",
          outputDir,
        ]);

        assert.notEqual(result.status, 0);
        const commandOutput = `${result.stdout}\n${result.stderr}`;
        const leakedSecretKinds = [
          ["submitted password", submittedPassword],
          ["response fragment", responseFragment],
        ]
          .filter(([, value]) => commandOutput.includes(value))
          .map(([kind]) => kind);
        assert.deepEqual(leakedSecretKinds, []);
        assert.equal(
          result.stderr.trim(),
          "admin web login state failed: POST /v1/admin/auth/login failed with HTTP 200: invalid JSON response",
        );
      });
    },
  );
});

test("CLI redacts malformed JSON from a successful auth me response", async () => {
  await withLoginStateCliSandbox(
    async ({ sandbox, repositoryRoot, credentialFile, runCliAsync }) => {
      const sessionCookieValue = "ckMEJ8";
      const responseFragment = "MEJ8";
      const outputDir = join(sandbox, "malformed-me-state");

      initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot });
      writeFileSync(
        credentialFile,
        `CUSTOMER_ADMIN_EMAIL=malformed-me@example.test
CUSTOMER_ADMIN_PASSWORD=malformed-me-password
SYSTEM_ADMIN_EMAIL=unused-system@example.test
SYSTEM_ADMIN_PASSWORD=unused-system-password
`,
        "utf8",
      );
      chmodSync(credentialFile, 0o600);

      await withLocalHttpServer((request, response) => {
        const pathname = new URL(request.url, "http://fixture.test").pathname;
        response.statusCode = 200;
        response.setHeader("Content-Type", "application/json");
        if (pathname === "/v1/admin/auth/login") {
          response.setHeader(
            "Set-Cookie",
            `agent_admin_session=${sessionCookieValue}; Path=/; HttpOnly`,
          );
          response.end("{}");
          return;
        }
        response.end(`${sessionCookieValue}:${responseFragment}`);
      }, async (origin) => {
        const result = await runCliAsync([
          "--credentials-file",
          credentialFile,
          "--skip-kubectl",
          "--customer-url",
          origin,
          "--system-url",
          origin,
          "--output-dir",
          outputDir,
        ]);

        assert.notEqual(result.status, 0);
        const commandOutput = `${result.stdout}\n${result.stderr}`;
        const leakedSecretKinds = [
          ["session cookie", sessionCookieValue],
          ["response fragment", responseFragment],
        ]
          .filter(([, value]) => commandOutput.includes(value))
          .map(([kind]) => kind);
        assert.deepEqual(leakedSecretKinds, []);
        assert.equal(
          result.stderr.trim(),
          "admin web login state failed: GET /v1/admin/auth/me failed with HTTP 200: invalid JSON response",
        );
      });
    },
  );
});

test("CLI fails before side effects when an explicit credential file is missing", async () => {
  await withLoginStateCliSandbox(
    ({ sandbox, kubectlMarker, runCli }) => {
      const missingCredentialFile = join(
        sandbox,
        "missing-parent",
        "missing-credentials.env",
      );
      const outputDir = join(sandbox, "must-not-exist");
      const result = runCli([
        "--credentials-file",
        missingCredentialFile,
        "--output-dir",
        outputDir,
        "--customer-url",
        "http://127.0.0.1:1",
        "--system-url",
        "http://127.0.0.1:1",
      ]);

      assert.notEqual(result.status, 0);
      assert.throws(() => lstatSync(kubectlMarker), { code: "ENOENT" });
      assert.throws(() => lstatSync(outputDir), { code: "ENOENT" });
    },
  );
});

test("CLI rejects a recognized option token as a credentials file value", async () => {
  await withLoginStateCliSandbox(
    ({ sandbox, kubectlMarker, runCli }) => {
      const outputDir = join(sandbox, "must-not-exist");
      const result = runCli([
        "--credentials-file",
        "--skip-kubectl",
        "--output-dir",
        outputDir,
        "--customer-url",
        "http://127.0.0.1:1",
        "--system-url",
        "http://127.0.0.1:1",
      ]);

      assert.notEqual(result.status, 0);
      assert.equal(
        result.stderr.trim(),
        "admin web login state failed: Missing value for --credentials-file",
      );
      assert.throws(() => lstatSync(kubectlMarker), { code: "ENOENT" });
      assert.throws(() => lstatSync(outputDir), { code: "ENOENT" });
    },
  );
});

test("CLI fails closed for a dangling default credential symlink", async () => {
  await withLoginStateCliSandbox(
    ({ sandbox, kubectlMarker, runCli }) => {
      const homeDirectory = join(sandbox, "home");
      const credentialFile = defaultAdminCredentialsFile(homeDirectory);
      mkdirSync(dirname(credentialFile), { recursive: true, mode: 0o700 });
      chmodSync(dirname(credentialFile), 0o700);
      symlinkSync(join(sandbox, "missing-target"), credentialFile);

      const result = runCli(["--skip-kubectl"], {
        env: { HOME: homeDirectory },
      });

      assert.notEqual(result.status, 0);
      assert.match(result.stderr, /symbolic link/u);
      assert.throws(() => lstatSync(kubectlMarker), { code: "ENOENT" });
    },
  );
});

function withCredentialSandbox(run) {
  const sandbox = mkdtempSync(join(tmpdir(), "admin-web-credentials-"));
  const repositoryRoot = join(sandbox, "repository");
  const credentialFile = join(
    sandbox,
    "home",
    ".config",
    "ecommerce-cs-agent",
    "admin-test-credentials.env",
  );
  mkdirSync(repositoryRoot, { recursive: true });

  try {
    return run({ sandbox, repositoryRoot, credentialFile });
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
}

test("parses exactly the ordered credential keys without evaluating shell syntax", () => {
  assert.deepEqual(ADMIN_CREDENTIAL_KEYS, [
    "CUSTOMER_ADMIN_EMAIL",
    "CUSTOMER_ADMIN_PASSWORD",
    "SYSTEM_ADMIN_EMAIL",
    "SYSTEM_ADMIN_PASSWORD",
  ]);
  assert.equal(
    ADMIN_CREDENTIAL_TEMPLATE,
    "CUSTOMER_ADMIN_EMAIL=\nCUSTOMER_ADMIN_PASSWORD=\nSYSTEM_ADMIN_EMAIL=\nSYSTEM_ADMIN_PASSWORD=\n",
  );

  const credentials = parseAdminCredentialText(completeText);

  assert.deepEqual(Object.keys(credentials), ADMIN_CREDENTIAL_KEYS);
  assert.deepEqual(credentials, {
    CUSTOMER_ADMIN_EMAIL: "customer@example.test",
    CUSTOMER_ADMIN_PASSWORD: "customer pass; $HOME # inert",
    SYSTEM_ADMIN_EMAIL: "system@example.test",
    SYSTEM_ADMIN_PASSWORD: "system pass && echo inert",
  });
});

test("rejects missing, blank, unknown, duplicate, and malformed assignments without leaking values", () => {
  const secretMarker = "must-not-appear-in-errors";
  const invalidTexts = [
    `CUSTOMER_ADMIN_EMAIL="customer@example.test"
CUSTOMER_ADMIN_PASSWORD="customer pass"
SYSTEM_ADMIN_EMAIL="system@example.test"
SYSTEM_ADMIN_PASSWORD="${secretMarker}
`,
    `CUSTOMER_ADMIN_EMAIL="customer@example.test" ignored
CUSTOMER_ADMIN_PASSWORD="${secretMarker}"
SYSTEM_ADMIN_EMAIL="system@example.test"
SYSTEM_ADMIN_PASSWORD="system pass"
`,
    `export CUSTOMER_ADMIN_EMAIL="${secretMarker}"
CUSTOMER_ADMIN_PASSWORD="customer pass"
SYSTEM_ADMIN_EMAIL="system@example.test"
SYSTEM_ADMIN_PASSWORD="system pass"
`,
    `CUSTOMER_ADMIN_EMAIL="customer@example.test"
CUSTOMER_ADMIN_PASSWORD="${secretMarker}"
SYSTEM_ADMIN_EMAIL="system@example.test"
`,
    `CUSTOMER_ADMIN_EMAIL=
CUSTOMER_ADMIN_PASSWORD="${secretMarker}"
SYSTEM_ADMIN_EMAIL="system@example.test"
SYSTEM_ADMIN_PASSWORD="system pass"
`,
    `CUSTOMER_ADMIN_EMAIL="customer@example.test"
CUSTOMER_ADMIN_PASSWORD="${secretMarker}"
SYSTEM_ADMIN_EMAIL="system@example.test"
SYSTEM_ADMIN_PASSWORD="system pass"
UNEXPECTED_CREDENTIAL="unknown"
`,
    `CUSTOMER_ADMIN_EMAIL="customer@example.test"
CUSTOMER_ADMIN_PASSWORD="${secretMarker}"
SYSTEM_ADMIN_EMAIL="system@example.test"
SYSTEM_ADMIN_PASSWORD="system pass"
CUSTOMER_ADMIN_PASSWORD="duplicate"
`,
    `CUSTOMER_ADMIN_EMAIL="customer@example.test"
CUSTOMER_ADMIN_PASSWORD="${secretMarker}"
SYSTEM_ADMIN_EMAIL="system@example.test"
SYSTEM_ADMIN_PASSWORD="system pass"
invalid assignment ${secretMarker}
`,
  ];

  const acceptedInvalidTextIndexes = [];
  for (const [index, text] of invalidTexts.entries()) {
    try {
      parseAdminCredentialText(text);
      acceptedInvalidTextIndexes.push(index);
    } catch (error) {
      assert.ok(error instanceof Error);
      assert.doesNotMatch(error.message, new RegExp(secretMarker));
    }
  }
  assert.deepEqual(acceptedInvalidTextIndexes, []);
});

test("merges non-empty environment overrides without mutating process.env", () => {
  const originalCustomerPassword = process.env.CUSTOMER_ADMIN_PASSWORD;
  const fileCredentials = parseAdminCredentialText(completeText);
  const environment = {
    CUSTOMER_ADMIN_EMAIL: "environment-customer@example.test",
    CUSTOMER_ADMIN_PASSWORD: "",
    SYSTEM_ADMIN_PASSWORD: "environment system pass",
  };
  const environmentSnapshot = { ...environment };

  const merged = mergeAdminCredentialSources(fileCredentials, environment);

  assert.deepEqual(merged, {
    CUSTOMER_ADMIN_EMAIL: "environment-customer@example.test",
    CUSTOMER_ADMIN_PASSWORD: "customer pass; $HOME # inert",
    SYSTEM_ADMIN_EMAIL: "system@example.test",
    SYSTEM_ADMIN_PASSWORD: "environment system pass",
  });
  assert.deepEqual(
    mergeAdminCredentialSources(
      {
        CUSTOMER_ADMIN_EMAIL: undefined,
        SYSTEM_ADMIN_EMAIL: "system@example.test",
      },
      {},
    ),
    {
      SYSTEM_ADMIN_EMAIL: "system@example.test",
    },
  );
  assert.deepEqual(environment, environmentSnapshot);
  assert.equal(process.env.CUSTOMER_ADMIN_PASSWORD, originalCustomerPassword);
});

test("builds the default repository-external credential path from the supplied home", () => {
  assert.equal(
    defaultAdminCredentialsFile("/Users/example"),
    "/Users/example/.config/ecommerce-cs-agent/admin-test-credentials.env",
  );
});

test("initializes an owner-only credential file and refuses to overwrite it", () => {
  withCredentialSandbox(({ repositoryRoot, credentialFile }) => {
    assert.equal(
      initializeAdminCredentialFile({
        filePath: credentialFile,
        repositoryRoot,
      }),
      resolve(credentialFile),
    );

    const parentInfo = lstatSync(dirname(credentialFile));
    assert.equal(parentInfo.isDirectory(), true);
    assert.equal(parentInfo.isSymbolicLink(), false);
    assert.equal(parentInfo.mode & 0o777, 0o700);

    const fileInfo = lstatSync(credentialFile);
    assert.equal(fileInfo.isFile(), true);
    assert.equal(fileInfo.isSymbolicLink(), false);
    assert.equal(fileInfo.mode & 0o777, 0o600);

    if (typeof process.getuid === "function") {
      assert.equal(parentInfo.uid, process.getuid());
      assert.equal(fileInfo.uid, process.getuid());
    }

    assert.equal(readFileSync(credentialFile, "utf8"), ADMIN_CREDENTIAL_TEMPLATE);
    assert.throws(
      () =>
        initializeAdminCredentialFile({
          filePath: credentialFile,
          repositoryRoot,
        }),
      /already exists/u,
    );
  });
});

test("loads and parses a secure credential file", () => {
  withCredentialSandbox(({ repositoryRoot, credentialFile }) => {
    initializeAdminCredentialFile({
      filePath: credentialFile,
      repositoryRoot,
    });
    writeFileSync(credentialFile, completeText, "utf8");
    chmodSync(credentialFile, 0o600);

    assert.equal(
      loadAdminCredentialFile({
        filePath: credentialFile,
        repositoryRoot,
      }).SYSTEM_ADMIN_EMAIL,
      "system@example.test",
    );
  });
});

test("uses the module repository as the default boundary regardless of cwd", () => {
  withCredentialSandbox(({ sandbox }) => {
    const moduleRepositoryRoot = fileURLToPath(new URL("..", import.meta.url));
    const inRepositoryParent = mkdtempSync(
      join(moduleRepositoryRoot, ".admin-default-root-test-"),
    );
    const credentialFile = join(
      inRepositoryParent,
      "admin-test-credentials.env",
    );
    const originalCwd = process.cwd();

    try {
      process.chdir(sandbox);
      assert.throws(
        () => initializeAdminCredentialFile({ filePath: credentialFile }),
        /repository/u,
      );
      assert.throws(() => lstatSync(credentialFile), { code: "ENOENT" });
    } finally {
      process.chdir(originalCwd);
      rmSync(inRepositoryParent, { recursive: true, force: true });
    }
  });
});

test("loads the validated credential entry through the same descriptor", () => {
  withCredentialSandbox(({ sandbox, repositoryRoot, credentialFile }) => {
    const originalCredentialFile = join(sandbox, "original-credentials.env");
    const replacementFile = join(sandbox, "replacement-credentials.env");
    initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot });
    writeFileSync(credentialFile, completeText, "utf8");
    chmodSync(credentialFile, 0o600);
    writeFileSync(
      replacementFile,
      completeText.replace(
        'SYSTEM_ADMIN_EMAIL="system@example.test"',
        'SYSTEM_ADMIN_EMAIL="replacement@example.test"',
      ),
      { mode: 0o600 },
    );

    const originalReadFileSync = fs.readFileSync;
    let pathReplacementAttempted = false;
    fs.readFileSync = (path, ...args) => {
      if (
        !pathReplacementAttempted &&
        typeof path !== "number" &&
        resolve(path) === resolve(credentialFile)
      ) {
        pathReplacementAttempted = true;
        renameSync(credentialFile, originalCredentialFile);
        symlinkSync(replacementFile, credentialFile);
      }
      return originalReadFileSync(path, ...args);
    };
    syncBuiltinESMExports();

    try {
      const credentials = loadAdminCredentialFile({
        filePath: credentialFile,
        repositoryRoot,
      });
      assert.equal(pathReplacementAttempted, false);
      assert.equal(credentials.SYSTEM_ADMIN_EMAIL, "system@example.test");
    } finally {
      fs.readFileSync = originalReadFileSync;
      syncBuiltinESMExports();
    }
  });
});

test("rejects lexical credential paths inside the repository", () => {
  withCredentialSandbox(({ repositoryRoot }) => {
    const credentialFile = join(repositoryRoot, "admin-test-credentials.env");

    assert.throws(
      () =>
        initializeAdminCredentialFile({
          filePath: credentialFile,
          repositoryRoot,
        }),
      /repository/u,
    );
    assert.equal(lstatSync(repositoryRoot).isDirectory(), true);
    assert.throws(() => lstatSync(credentialFile), { code: "ENOENT" });
  });
});

test("rejects a credential file symlink without leaking its contents", () => {
  withCredentialSandbox(({ sandbox, repositoryRoot, credentialFile }) => {
    const secretMarker = "file-symlink-secret-marker";
    const realFile = join(sandbox, "real-credentials.env");
    mkdirSync(dirname(credentialFile), { recursive: true, mode: 0o700 });
    chmodSync(dirname(credentialFile), 0o700);
    writeFileSync(realFile, `${completeText}\n# ${secretMarker}\n`, { mode: 0o600 });
    symlinkSync(realFile, credentialFile);

    assert.throws(
      () =>
        loadAdminCredentialFile({
          filePath: credentialFile,
          repositoryRoot,
        }),
      (error) => {
        assert.ok(error instanceof Error);
        assert.match(error.message, /symbolic link/u);
        assert.doesNotMatch(error.message, new RegExp(secretMarker, "u"));
        return true;
      },
    );
  });
});

test("treats a dangling credential symlink as an existing entry", () => {
  withCredentialSandbox(({ sandbox, repositoryRoot, credentialFile }) => {
    mkdirSync(dirname(credentialFile), { recursive: true, mode: 0o700 });
    chmodSync(dirname(credentialFile), 0o700);
    symlinkSync(join(sandbox, "missing-target"), credentialFile);

    assert.throws(
      () =>
        initializeAdminCredentialFile({
          filePath: credentialFile,
          repositoryRoot,
        }),
      /already exists/u,
    );
    assert.equal(lstatSync(credentialFile).isSymbolicLink(), true);
  });
});

test("rejects an immediate parent directory symlink", () => {
  withCredentialSandbox(({ sandbox, repositoryRoot, credentialFile }) => {
    const parent = dirname(credentialFile);
    const realParent = join(sandbox, "real-parent");
    mkdirSync(dirname(parent), { recursive: true, mode: 0o700 });
    mkdirSync(realParent, { mode: 0o700 });
    symlinkSync(realParent, parent);

    assert.throws(
      () =>
        initializeAdminCredentialFile({
          filePath: credentialFile,
          repositoryRoot,
        }),
      /symbolic link/u,
    );
    assert.throws(() => lstatSync(join(realParent, "admin-test-credentials.env")), {
      code: "ENOENT",
    });
  });
});

test("rejects an outside lexical path whose resolved parent is inside the repository", () => {
  withCredentialSandbox(({ sandbox, repositoryRoot }) => {
    const realParent = join(repositoryRoot, "escaped", "credential-parent");
    const ancestorLink = join(sandbox, "outside-link");
    const credentialFile = join(
      ancestorLink,
      "credential-parent",
      "admin-test-credentials.env",
    );
    mkdirSync(realParent, { recursive: true, mode: 0o700 });
    chmodSync(realParent, 0o700);
    symlinkSync(join(repositoryRoot, "escaped"), ancestorLink);

    assert.throws(
      () =>
        initializeAdminCredentialFile({
          filePath: credentialFile,
          repositoryRoot,
        }),
      /repository/u,
    );
    assert.throws(
      () => lstatSync(join(realParent, "admin-test-credentials.env")),
      { code: "ENOENT" },
    );
  });
});

test("rejects an existing resolved repository parent without changing its mode", () => {
  withCredentialSandbox(({ sandbox, repositoryRoot }) => {
    const realParent = join(repositoryRoot, "escaped", "credential-parent");
    const ancestorLink = join(sandbox, "outside-link");
    const credentialFile = join(
      ancestorLink,
      "credential-parent",
      "admin-test-credentials.env",
    );
    mkdirSync(realParent, { recursive: true, mode: 0o755 });
    chmodSync(realParent, 0o755);
    symlinkSync(join(repositoryRoot, "escaped"), ancestorLink);

    assert.throws(
      () =>
        initializeAdminCredentialFile({
          filePath: credentialFile,
          repositoryRoot,
        }),
      /repository/u,
    );
    assert.equal(lstatSync(realParent).mode & 0o777, 0o755);
    assert.throws(
      () => lstatSync(join(realParent, "admin-test-credentials.env")),
      { code: "ENOENT" },
    );
  });
});

test("rejects a missing resolved repository parent without creating it", () => {
  withCredentialSandbox(({ sandbox, repositoryRoot }) => {
    const escapedDirectory = join(repositoryRoot, "escaped");
    const realParent = join(escapedDirectory, "missing-parent");
    const ancestorLink = join(sandbox, "outside-link");
    const credentialFile = join(
      ancestorLink,
      "missing-parent",
      "admin-test-credentials.env",
    );
    mkdirSync(escapedDirectory, { mode: 0o700 });
    symlinkSync(escapedDirectory, ancestorLink);

    assert.throws(
      () =>
        initializeAdminCredentialFile({
          filePath: credentialFile,
          repositoryRoot,
        }),
      /repository/u,
    );
    assert.throws(() => lstatSync(realParent), { code: "ENOENT" });
  });
});

test("rejects a credential file with mode 0644", () => {
  withCredentialSandbox(({ repositoryRoot, credentialFile }) => {
    initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot });
    chmodSync(credentialFile, 0o644);

    assert.throws(
      () =>
        assertSecureAdminCredentialFile({
          filePath: credentialFile,
          repositoryRoot,
        }),
      /0600/u,
    );
  });
});

test("rejects an immediate parent with mode 0755", () => {
  withCredentialSandbox(({ repositoryRoot, credentialFile }) => {
    initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot });
    chmodSync(dirname(credentialFile), 0o755);

    assert.throws(
      () =>
        assertSecureAdminCredentialFile({
          filePath: credentialFile,
          repositoryRoot,
        }),
      /0700/u,
    );
  });
});

test("rejects a non-regular credential entry", () => {
  withCredentialSandbox(({ repositoryRoot, credentialFile }) => {
    const parent = dirname(credentialFile);
    mkdirSync(parent, { recursive: true, mode: 0o700 });
    chmodSync(parent, 0o700);
    mkdirSync(credentialFile, { mode: 0o700 });

    assert.throws(
      () =>
        assertSecureAdminCredentialFile({
          filePath: credentialFile,
          repositoryRoot,
        }),
      /regular file/u,
    );
  });
});

test(
  "rejects the parent or file ownership boundary for a different expected uid",
  { skip: typeof process.getuid !== "function" },
  () => {
    withCredentialSandbox(({ repositoryRoot, credentialFile }) => {
      initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot });

      assert.throws(
        () =>
          assertSecureAdminCredentialFile({
            filePath: credentialFile,
            repositoryRoot,
            expectedUid: process.getuid() + 1,
          }),
        /owned by the expected user/u,
      );
    });
  },
);
