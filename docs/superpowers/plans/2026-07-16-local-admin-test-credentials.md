# Local Admin Test Credentials Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Load both Customer Admin and System Admin live-test accounts from one owner-only file outside the repository, without logging secrets or weakening the two authentication domains.

**Architecture:** Put environment-file parsing, path checks, permission enforcement, and secure initialization in a new dependency-free Node module. Keep HTTP login, `/auth/me` verification, and temporary storageState generation in the existing login script. Run deterministic helper tests in PR and image-publication gates; create the real local file only after code verification.

**Tech Stack:** Node.js 24+ ESM, `node:test`, built-in `node:util.parseEnv`, Python deployment guard tests, GitHub Actions.

---

## File Structure

- Create `scripts/admin_web_credentials.mjs`: strict four-key parsing, environment precedence, repository/path checks, ownership/mode checks, secure template creation, and secure loading.
- Create `scripts/admin_web_credentials.test.mjs`: deterministic parser, redaction, path, symlink, owner, mode, initialization, and CLI-init tests.
- Modify `scripts/admin_web_login_state.mjs`: add `--credentials-file` and `--init-credentials-file`, load both accounts, and keep login/session output redacted.
- Modify `package.json`: add the root deterministic credential-helper test entry.
- Create `tests/deploy/test_admin_web_login_state_artifacts.py`: lock the repository-external path and no-secret/no-build-artifact contract.
- Modify `.github/workflows/pr-checks.yml`: run the root credential-helper test under Node 24.
- Modify `.github/workflows/publish-images.yml`: run the same helper test before building images.
- Modify `docs/security-local-files.md`: document the owner-only local file and temporary storageState lifecycle.
- Modify `docs/testing.md`: document deterministic and live commands without credential values.
- Modify `docs/development-handoff.md`: record implementation and verification completion.
- Create locally, never in Git: `~/.config/ecommerce-cs-agent/admin-test-credentials.env`.

### Task 1: Strict credential parsing and source precedence

**Files:**
- Create: `scripts/admin_web_credentials.mjs`
- Create: `scripts/admin_web_credentials.test.mjs`
- Modify: `package.json`

- [ ] **Step 1: Write the failing parser and precedence tests**

Create `scripts/admin_web_credentials.test.mjs` with the parser tests first:

```javascript
import assert from "node:assert/strict";
import test from "node:test";

import {
  ADMIN_CREDENTIAL_KEYS,
  defaultAdminCredentialsFile,
  mergeAdminCredentialSources,
  parseAdminCredentialText
} from "./admin_web_credentials.mjs";

const completeText = [
  'CUSTOMER_ADMIN_EMAIL="customer@example.test"',
  'CUSTOMER_ADMIN_PASSWORD="customer pass; $HOME # inert"',
  'SYSTEM_ADMIN_EMAIL="system@example.test"',
  'SYSTEM_ADMIN_PASSWORD="system pass && echo inert"'
].join("\n");

test("parses exactly four Admin credential keys as inert data", () => {
  const parsed = parseAdminCredentialText(completeText);
  assert.deepEqual(Object.keys(parsed), ADMIN_CREDENTIAL_KEYS);
  assert.equal(parsed.CUSTOMER_ADMIN_PASSWORD, "customer pass; $HOME # inert");
  assert.equal(parsed.SYSTEM_ADMIN_PASSWORD, "system pass && echo inert");
});

test("rejects missing, blank, unknown, and duplicate keys without exposing values", () => {
  const secretMarker = "must-not-appear-in-errors";
  const invalidInputs = [
    completeText.replace('SYSTEM_ADMIN_PASSWORD="system pass && echo inert"', ""),
    completeText.replace('SYSTEM_ADMIN_PASSWORD="system pass && echo inert"', "SYSTEM_ADMIN_PASSWORD="),
    `${completeText}\nUNEXPECTED_KEY="${secretMarker}"`,
    `${completeText}\nCUSTOMER_ADMIN_PASSWORD="${secretMarker}"`,
    `${completeText}\nnot-an-assignment-${secretMarker}`
  ];

  for (const input of invalidInputs) {
    assert.throws(
      () => parseAdminCredentialText(input),
      (error) => error instanceof Error && !error.message.includes(secretMarker)
    );
  }
});

test("environment values override file values without mutating process.env", () => {
  const originalCustomerPassword = process.env.CUSTOMER_ADMIN_PASSWORD;
  const fileCredentials = parseAdminCredentialText(completeText);
  const environment = {
    CUSTOMER_ADMIN_PASSWORD: "temporary-customer-override",
    SYSTEM_ADMIN_EMAIL: "temporary-system@example.test"
  };
  const merged = mergeAdminCredentialSources(fileCredentials, environment);

  assert.equal(merged.CUSTOMER_ADMIN_EMAIL, "customer@example.test");
  assert.equal(merged.CUSTOMER_ADMIN_PASSWORD, "temporary-customer-override");
  assert.equal(merged.SYSTEM_ADMIN_EMAIL, "temporary-system@example.test");
  assert.equal(merged.SYSTEM_ADMIN_PASSWORD, "system pass && echo inert");
  assert.equal(process.env.CUSTOMER_ADMIN_PASSWORD, originalCustomerPassword);
});

test("builds the default path below the supplied home directory", () => {
  assert.equal(
    defaultAdminCredentialsFile("/Users/example"),
    "/Users/example/.config/ecommerce-cs-agent/admin-test-credentials.env"
  );
});
```

Add the root test command to `package.json`:

```json
{
  "private": true,
  "type": "module",
  "scripts": {
    "test:admin-credentials": "node --test scripts/admin_web_credentials.test.mjs",
    "dev:acs:env": "node scripts/acs_local_env.mjs",
    "dev:acs:port-forward": "node scripts/acs_port_forward.mjs",
    "dev:api:acs-local": "bash -lc 'set -a; . ./.local/acs-runtime.env; set +a; ACS_DEBUG_MODE=local-acs .venv/bin/python -m uvicorn ecommerce_cs_agent.api.app:app --host 127.0.0.1 --port 8000'",
    "dev:admin:customer": "npm --prefix admin-web run dev:customer"
  }
}
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
npm run test:admin-credentials
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `scripts/admin_web_credentials.mjs`.

- [ ] **Step 3: Implement the parser and precedence functions**

Create `scripts/admin_web_credentials.mjs`:

```javascript
import { homedir } from "node:os";
import { join } from "node:path";
import { parseEnv } from "node:util";

export const ADMIN_CREDENTIAL_KEYS = Object.freeze([
  "CUSTOMER_ADMIN_EMAIL",
  "CUSTOMER_ADMIN_PASSWORD",
  "SYSTEM_ADMIN_EMAIL",
  "SYSTEM_ADMIN_PASSWORD"
]);

export const ADMIN_CREDENTIAL_TEMPLATE = `${ADMIN_CREDENTIAL_KEYS.map((key) => `${key}=`).join("\n")}\n`;

export function defaultAdminCredentialsFile(homeDirectory = homedir()) {
  return join(homeDirectory, ".config", "ecommerce-cs-agent", "admin-test-credentials.env");
}

function assignmentKeys(text) {
  const keys = [];
  for (const [index, line] of text.split(/\r?\n/).entries()) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const match = /^([A-Za-z_][A-Za-z0-9_]*)\s*=/.exec(trimmed);
    if (!match) throw new Error(`Invalid credential assignment at line ${index + 1}.`);
    keys.push(match[1]);
  }
  return keys;
}

export function parseAdminCredentialText(text) {
  const assigned = assignmentKeys(text);
  const duplicate = assigned.find((key, index) => assigned.indexOf(key) !== index);
  if (duplicate) throw new Error(`Duplicate credential key: ${duplicate}.`);

  let parsed;
  try {
    parsed = parseEnv(text);
  } catch {
    throw new Error("Credential file contains invalid environment syntax.");
  }
  const unknown = Object.keys(parsed).find((key) => !ADMIN_CREDENTIAL_KEYS.includes(key));
  if (unknown) throw new Error(`Unknown credential key: ${unknown}.`);

  for (const key of ADMIN_CREDENTIAL_KEYS) {
    if (!(key in parsed)) throw new Error(`Missing credential key: ${key}.`);
    if (parsed[key].length === 0) throw new Error(`Credential key is blank: ${key}.`);
  }

  return Object.fromEntries(ADMIN_CREDENTIAL_KEYS.map((key) => [key, parsed[key]]));
}

export function mergeAdminCredentialSources(fileCredentials = {}, environment = {}) {
  return Object.fromEntries(ADMIN_CREDENTIAL_KEYS.flatMap((key) => {
    const environmentValue = typeof environment[key] === "string" && environment[key].length > 0
      ? environment[key]
      : undefined;
    const value = environmentValue ?? fileCredentials[key];
    return value === undefined ? [] : [[key, value]];
  }));
}
```

- [ ] **Step 4: Run the parser tests and verify GREEN**

Run:

```bash
npm run test:admin-credentials
```

Expected: 4 tests pass, 0 fail.

- [ ] **Step 5: Commit the parser slice**

```bash
git add package.json scripts/admin_web_credentials.mjs scripts/admin_web_credentials.test.mjs
git diff --cached --check
git diff --cached | rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET" || true
git commit -m "feat: parse local admin test credentials"
```

### Task 2: Owner-only initialization and fail-closed loading

**Files:**
- Modify: `scripts/admin_web_credentials.mjs`
- Modify: `scripts/admin_web_credentials.test.mjs`

- [ ] **Step 1: Add failing filesystem-security tests**

Extend `scripts/admin_web_credentials.test.mjs`:

```javascript
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

import {
  assertSecureAdminCredentialFile,
  initializeAdminCredentialFile,
  loadAdminCredentialFile
} from "./admin_web_credentials.mjs";

function withSandbox(run) {
  const sandbox = mkdtempSync(join(tmpdir(), "admin-credentials-test-"));
  const repositoryRoot = join(sandbox, "repository");
  const credentialFile = join(sandbox, "home", ".config", "ecommerce-cs-agent", "admin-test-credentials.env");
  mkdirSync(repositoryRoot, { recursive: true, mode: 0o700 });
  try {
    return run({ sandbox, repositoryRoot, credentialFile });
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
}

test("initializes an owner-only directory and four-key template", () => withSandbox(({ repositoryRoot, credentialFile }) => {
  const created = initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot });
  assert.equal(created, credentialFile);
  assert.equal(lstatSync(dirname(credentialFile)).mode & 0o777, 0o700);
  assert.equal(lstatSync(credentialFile).mode & 0o777, 0o600);
  assert.equal(readFileSync(credentialFile, "utf8"), [
    "CUSTOMER_ADMIN_EMAIL=",
    "CUSTOMER_ADMIN_PASSWORD=",
    "SYSTEM_ADMIN_EMAIL=",
    "SYSTEM_ADMIN_PASSWORD=",
    ""
  ].join("\n"));
  assert.throws(() => initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot }), /already exists/);
}));

test("loads a secure complete file", () => withSandbox(({ repositoryRoot, credentialFile }) => {
  initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot });
  writeFileSync(credentialFile, completeText, { mode: 0o600 });
  chmodSync(credentialFile, 0o600);
  assert.equal(loadAdminCredentialFile({ filePath: credentialFile, repositoryRoot }).SYSTEM_ADMIN_EMAIL, "system@example.test");
}));

test("rejects repository paths, symlinks, broad modes, non-files, and wrong owners", () => withSandbox(({ sandbox, repositoryRoot, credentialFile }) => {
  const repositoryFile = join(repositoryRoot, "admin-test-credentials.env");
  assert.throws(
    () => initializeAdminCredentialFile({ filePath: repositoryFile, repositoryRoot }),
    /outside the repository/
  );

  const parent = dirname(credentialFile);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  const realFile = join(sandbox, "real.env");
  writeFileSync(realFile, completeText, { mode: 0o600 });
  symlinkSync(realFile, credentialFile);
  assert.throws(
    () => assertSecureAdminCredentialFile({ filePath: credentialFile, repositoryRoot }),
    /symbolic link/
  );
  rmSync(credentialFile);

  symlinkSync(join(sandbox, "missing.env"), credentialFile);
  assert.throws(
    () => initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot }),
    /already exists/
  );
  rmSync(credentialFile);

  const realParent = join(sandbox, "real-parent");
  mkdirSync(realParent, { mode: 0o700 });
  rmSync(parent);
  symlinkSync(realParent, parent);
  assert.throws(
    () => initializeAdminCredentialFile({ filePath: credentialFile, repositoryRoot }),
    /parent directory must not be a symbolic link/
  );
  rmSync(parent);
  mkdirSync(parent, { recursive: true, mode: 0o700 });

  writeFileSync(credentialFile, completeText, { mode: 0o644 });
  assert.throws(
    () => assertSecureAdminCredentialFile({ filePath: credentialFile, repositoryRoot }),
    /mode 0600/
  );
  chmodSync(credentialFile, 0o600);
  chmodSync(parent, 0o755);
  assert.throws(
    () => assertSecureAdminCredentialFile({ filePath: credentialFile, repositoryRoot }),
    /mode 0700/
  );
  chmodSync(parent, 0o700);

  const currentUid = typeof process.getuid === "function" ? process.getuid() : undefined;
  if (currentUid !== undefined) {
    assert.throws(
      () => assertSecureAdminCredentialFile({
        filePath: credentialFile,
        repositoryRoot,
        expectedUid: currentUid + 1
      }),
      /current user/
    );
  }

  rmSync(credentialFile);
  mkdirSync(credentialFile, { mode: 0o600 });
  assert.throws(
    () => assertSecureAdminCredentialFile({ filePath: credentialFile, repositoryRoot }),
    /regular file/
  );
}));
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
npm run test:admin-credentials
```

Expected: FAIL because the three filesystem functions are not exported.

- [ ] **Step 3: Implement secure initialization and loading**

Extend the imports and add these functions to `scripts/admin_web_credentials.mjs`:

```javascript
import {
  chmodSync,
  lstatSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  writeFileSync
} from "node:fs";
import { dirname, homedir, join, relative, resolve, sep } from "node:path";

function modeOf(info) {
  return info.mode & 0o777;
}

function isWithin(root, candidate) {
  const result = relative(root, candidate);
  return result === "" || (result !== ".." && !result.startsWith(`..${sep}`));
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

function assertOutsideRepository(filePath, repositoryRoot) {
  const repository = realpathSync(repositoryRoot);
  const candidate = resolve(filePath);
  if (isWithin(repository, candidate)) {
    throw new Error("Admin credential file must stay outside the repository.");
  }
  return { repository, candidate };
}

function assertOwned(info, expectedUid, label) {
  if (expectedUid !== undefined && info.uid !== expectedUid) {
    throw new Error(`${label} must be owned by the current user.`);
  }
}

export function assertSecureAdminCredentialFile({
  filePath,
  repositoryRoot,
  expectedUid = typeof process.getuid === "function" ? process.getuid() : undefined
}) {
  const { repository, candidate } = assertOutsideRepository(filePath, repositoryRoot);
  const parent = dirname(candidate);
  const parentInfo = lstatSync(parent);
  if (parentInfo.isSymbolicLink()) throw new Error("Admin credential parent directory must not be a symbolic link.");
  if (!parentInfo.isDirectory()) throw new Error("Admin credential parent path must be a directory.");
  assertOwned(parentInfo, expectedUid, "Admin credential parent directory");
  if (modeOf(parentInfo) !== 0o700) throw new Error("Admin credential parent directory must use mode 0700.");
  if (isWithin(repository, realpathSync(parent))) throw new Error("Admin credential file must stay outside the repository.");

  const fileInfo = lstatSync(candidate);
  if (fileInfo.isSymbolicLink()) throw new Error("Admin credential file must not be a symbolic link.");
  if (!fileInfo.isFile()) throw new Error("Admin credential path must be a regular file.");
  assertOwned(fileInfo, expectedUid, "Admin credential file");
  if (modeOf(fileInfo) !== 0o600) throw new Error("Admin credential file must use mode 0600.");
  return candidate;
}

export function initializeAdminCredentialFile({
  filePath = defaultAdminCredentialsFile(),
  repositoryRoot,
  expectedUid = typeof process.getuid === "function" ? process.getuid() : undefined
}) {
  const { repository, candidate } = assertOutsideRepository(filePath, repositoryRoot);
  if (pathEntryExists(candidate)) throw new Error("Admin credential file already exists; refusing to overwrite it.");

  const parent = dirname(candidate);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  const parentInfo = lstatSync(parent);
  if (parentInfo.isSymbolicLink()) throw new Error("Admin credential parent directory must not be a symbolic link.");
  assertOwned(parentInfo, expectedUid, "Admin credential parent directory");
  chmodSync(parent, 0o700);
  if (isWithin(repository, realpathSync(parent))) {
    throw new Error("Admin credential file must stay outside the repository.");
  }

  writeFileSync(candidate, ADMIN_CREDENTIAL_TEMPLATE, { encoding: "utf8", flag: "wx", mode: 0o600 });
  chmodSync(candidate, 0o600);
  return assertSecureAdminCredentialFile({ filePath: candidate, repositoryRoot, expectedUid });
}

export function loadAdminCredentialFile(options) {
  const filePath = assertSecureAdminCredentialFile(options);
  return parseAdminCredentialText(readFileSync(filePath, "utf8"));
}
```

- [ ] **Step 4: Run the security tests and verify GREEN**

Run:

```bash
npm run test:admin-credentials
```

Expected: all parser and filesystem tests pass; no test output contains fake password values.

- [ ] **Step 5: Commit the filesystem-security slice**

```bash
git add scripts/admin_web_credentials.mjs scripts/admin_web_credentials.test.mjs
git diff --cached --check
git diff --cached | rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET" || true
git commit -m "feat: secure local admin credential files"
```

### Task 3: Integrate the credential file with Admin login state generation

**Files:**
- Modify: `scripts/admin_web_login_state.mjs`
- Modify: `scripts/admin_web_credentials.test.mjs`

- [ ] **Step 1: Add a failing CLI initialization test**

Extend `scripts/admin_web_credentials.test.mjs`:

```javascript
import { spawnSync } from "node:child_process";

test("login helper initializes the requested credential file and exits before login", () => withSandbox(({ repositoryRoot, credentialFile }) => {
  const completed = spawnSync(
    process.execPath,
    [
      join(repositoryRoot, "scripts", "admin_web_login_state.mjs"),
      "--credentials-file",
      credentialFile,
      "--init-credentials-file"
    ],
    {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: { ...process.env, HOME: join(dirname(credentialFile), "..", "..") }
    }
  );

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(lstatSync(credentialFile).mode & 0o777, 0o600);
  assert.doesNotMatch(completed.stdout, /CUSTOMER_ADMIN_PASSWORD|SYSTEM_ADMIN_PASSWORD/);
  assert.doesNotMatch(completed.stderr, /CUSTOMER_ADMIN_PASSWORD|SYSTEM_ADMIN_PASSWORD/);
}));
```

Adjust `withSandbox` so the temporary repository contains the current scripts through a test-only symlink-free copy:

```javascript
import { cpSync } from "node:fs";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = fileURLToPath(new URL("..", import.meta.url));

function withSandbox(run) {
  const sandbox = mkdtempSync(join(tmpdir(), "admin-credentials-test-"));
  const repositoryRoot = join(sandbox, "repository");
  const credentialFile = join(sandbox, "home", ".config", "ecommerce-cs-agent", "admin-test-credentials.env");
  mkdirSync(join(repositoryRoot, "scripts"), { recursive: true, mode: 0o700 });
  cpSync(join(PROJECT_ROOT, "scripts", "admin_web_login_state.mjs"), join(repositoryRoot, "scripts", "admin_web_login_state.mjs"));
  cpSync(join(PROJECT_ROOT, "scripts", "admin_web_credentials.mjs"), join(repositoryRoot, "scripts", "admin_web_credentials.mjs"));
  try {
    return run({ sandbox, repositoryRoot, credentialFile });
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
}
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
npm run test:admin-credentials
```

Expected: FAIL with `Unknown option: --credentials-file`.

- [ ] **Step 3: Add CLI flags and credential resolution**

Update `scripts/admin_web_login_state.mjs` imports:

```javascript
import { execFileSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

import {
  defaultAdminCredentialsFile,
  initializeAdminCredentialFile,
  loadAdminCredentialFile,
  mergeAdminCredentialSources
} from "./admin_web_credentials.mjs";

const REPOSITORY_ROOT = fileURLToPath(new URL("..", import.meta.url));
```

Add to `parseArgs` defaults:

```javascript
credentialsFile: "",
initCredentialsFile: false
```

Handle the boolean flag before value flags:

```javascript
if (arg === "--init-credentials-file") {
  args.initCredentialsFile = true;
  continue;
}
```

Add the value flag:

```javascript
"--credentials-file": "credentialsFile"
```

Add the usage text:

```text
  --credentials-file <path>  Owner-only Customer/System credential file.
                             Default: ~/.config/ecommerce-cs-agent/admin-test-credentials.env
  --init-credentials-file    Create an empty 0600 credential template and exit.
```

Add the environment-file notes:

```text
  - The credential file must stay outside the repository with parent mode 0700 and file mode 0600.
  - Environment overrides take precedence over credential-file values.
  - Never paste Admin passwords into chat or commit the credential file.
```

Add a resolver above `main`:

```javascript
function resolveCredentialEnvironment(args, selectedFile) {
  const shouldLoad = Boolean(args.credentialsFile) || existsSync(selectedFile);
  const fileCredentials = shouldLoad
    ? loadAdminCredentialFile({ filePath: selectedFile, repositoryRoot: REPOSITORY_ROOT })
    : {};
  return mergeAdminCredentialSources(fileCredentials, process.env);
}
```

At the start of `main`, initialize before attempting to load the file and before any Kubernetes read:

```javascript
const selectedFile = args.credentialsFile || defaultAdminCredentialsFile();
if (args.initCredentialsFile) {
  const createdPath = initializeAdminCredentialFile({
    filePath: selectedFile,
    repositoryRoot: REPOSITORY_ROOT
  });
  console.log(JSON.stringify({
    ok: true,
    credentialsFile: createdPath,
    warning: "Fill this file locally. Do not paste passwords into chat or commit the file."
  }, null, 2));
  return;
}
const credentials = resolveCredentialEnvironment(args, selectedFile);
```

Replace direct `process.env` reads:

```javascript
const customerEmail = credentials.CUSTOMER_ADMIN_EMAIL
  || (!args.skipKubectl ? kubectlSecretValue(args, "ADMIN_INITIAL_EMAIL") : "");
const customerHash = !args.skipKubectl ? kubectlSecretValue(args, "ADMIN_INITIAL_PASSWORD_HASH") : "";
const customerPassword = passwordFromHash(
  "customer admin",
  customerHash,
  credentials.CUSTOMER_ADMIN_PASSWORD
);

const systemEmail = credentials.SYSTEM_ADMIN_EMAIL
  || (!args.skipKubectl ? kubectlSecretValue(args, "SYSTEM_ADMIN_INITIAL_EMAIL") : "")
  || customerEmail;
const systemHash = (!args.skipKubectl ? kubectlSecretValue(args, "SYSTEM_ADMIN_INITIAL_PASSWORD_HASH") : "")
  || customerHash;
const systemPassword = passwordFromHash(
  "system admin",
  systemHash,
  credentials.SYSTEM_ADMIN_PASSWORD
);
```

Keep failed authentication responses redacted by replacing response-body summaries in `postJson` and `getJson` with method, URL path, and status only:

```javascript
if (!response.ok) {
  throw new Error(`POST ${new URL(url).pathname} failed with ${response.status}.`);
}
```

```javascript
if (!response.ok) {
  throw new Error(`GET ${new URL(url).pathname} failed with ${response.status}.`);
}
```

Remove `summarizeBody`; a server response must never be able to echo a submitted password or Cookie into terminal output.

- [ ] **Step 4: Run focused CLI and existing artifact tests**

Run:

```bash
npm run test:admin-credentials
python -m pytest tests/deploy/test_acs_local_debug_artifacts.py -q
node scripts/admin_web_login_state.mjs --help
```

Expected: Node tests pass, Python deploy tests pass, and help lists both new options without credential values.

- [ ] **Step 5: Commit the CLI integration**

```bash
git add scripts/admin_web_login_state.mjs scripts/admin_web_credentials.test.mjs
git diff --cached --check
git diff --cached | rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET" || true
git commit -m "feat: load Admin login state credentials from file"
```

### Task 4: Put the security contract into CI and documentation

**Files:**
- Create: `tests/deploy/test_admin_web_login_state_artifacts.py`
- Modify: `.github/workflows/pr-checks.yml`
- Modify: `.github/workflows/publish-images.yml`
- Modify: `docs/security-local-files.md`
- Modify: `docs/testing.md`
- Modify: `docs/development-handoff.md`

- [ ] **Step 1: Add failing deployment-boundary tests**

Create `tests/deploy/test_admin_web_login_state_artifacts.py`:

```python
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_admin_credential_helper_is_part_of_the_root_test_gate():
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["scripts"]["test:admin-credentials"] == (
        "node --test scripts/admin_web_credentials.test.mjs"
    )


def test_admin_credential_contract_stays_outside_repository_and_redacted():
    helper = (ROOT / "scripts" / "admin_web_credentials.mjs").read_text(encoding="utf-8")
    login = (ROOT / "scripts" / "admin_web_login_state.mjs").read_text(encoding="utf-8")

    assert '.config", "ecommerce-cs-agent", "admin-test-credentials.env' in helper
    assert "0o700" in helper
    assert "0o600" in helper
    assert "isSymbolicLink" in helper
    assert "outside the repository" in helper
    assert "console.log(credentials" not in login
    assert "console.log(fileCredentials" not in login
    assert "console.log(customerPassword" not in login
    assert "console.log(systemPassword" not in login
    assert "summarizeBody(body)" not in login
    assert not (ROOT / "admin-test-credentials.env").exists()


def test_admin_credential_file_is_not_referenced_by_build_artifacts():
    build_sources = [
        ROOT / "Dockerfile.api",
        ROOT / "admin-web" / "Dockerfile",
        *sorted((ROOT / "deploy" / "helm" / "ecommerce-cs-agent").rglob("*")),
    ]
    for path in build_sources:
        if path.is_file():
            assert "admin-test-credentials.env" not in path.read_text(
                encoding="utf-8", errors="ignore"
            )


def test_admin_credential_tests_run_in_pr_and_publish_gates():
    workflows = [
        ROOT / ".github" / "workflows" / "pr-checks.yml",
        ROOT / ".github" / "workflows" / "publish-images.yml",
    ]
    for workflow in workflows:
        source = workflow.read_text(encoding="utf-8")
        assert "Admin credential helper tests" in source
        assert "npm run test:admin-credentials" in source
```

- [ ] **Step 2: Run the deployment test and verify RED**

Run:

```bash
python -m pytest tests/deploy/test_admin_web_login_state_artifacts.py -q
```

Expected: FAIL because the PR and image-publication workflows do not yet run `npm run test:admin-credentials`.

- [ ] **Step 3: Add the Node helper gate to PR and image workflows**

In both `.github/workflows/pr-checks.yml` and the `verify` job in `.github/workflows/publish-images.yml`, add after `Set up Node.js`:

```yaml
      - name: Admin credential helper tests
        run: npm run test:admin-credentials
```

- [ ] **Step 4: Document local storage and testing**

Add a new section to `docs/security-local-files.md` before “提交前检查”:

```markdown
## 4. Admin live 测试凭据

Customer Admin 与 System Admin 的本机 live 测试账号只允许保存在仓库外：

`~/.config/ecommerce-cs-agent/admin-test-credentials.env`

父目录必须为 `0700`，文件必须为 `0600`，且都归当前用户所有。文件只允许包含
`CUSTOMER_ADMIN_EMAIL`、`CUSTOMER_ADMIN_PASSWORD`、`SYSTEM_ADMIN_EMAIL`、
`SYSTEM_ADMIN_PASSWORD`。禁止把密码发到聊天、提交到 Git、同步到云盘或复制进
Kubernetes/Helm/Docker 工件。

使用 `node scripts/admin_web_login_state.mjs --init-credentials-file` 创建空模板。
登录生成的 storageState 继续只写入 `/tmp/ecommerce-admin-auth-*`，完成测试后删除。
```

Renumber the following sections.

Add to `docs/testing.md` under current runnable tests:

````markdown
Admin 本机凭据帮助器的确定性测试：

```bash
npm run test:admin-credentials
```

本机凭据文件只保存于仓库外。填好四项后，可生成临时 Customer/System storageState：

```bash
node scripts/admin_web_login_state.mjs \
  --credentials-file ~/.config/ecommerce-cs-agent/admin-test-credentials.env \
  --skip-kubectl
```

命令不得输出密码或 Cookie；测试结束后删除输出的 `/tmp/ecommerce-admin-auth-*`。
````

Add a dated implementation bullet under `2026-07-16` in `docs/development-handoff.md`:

```markdown
- 本机 Admin 测试凭据实现采用独立 Node 模块执行严格四键解析、仓库外路径、owner、`0700`/`0600`、符号链接和日志脱敏门禁；PR 与镜像发布流程运行确定性测试，登录后的 storageState 仍只保留在 `/tmp`。
```

- [ ] **Step 5: Run documentation, deployment, and workflow checks**

Run:

```bash
npm run test:admin-credentials
python -m pytest tests/deploy/test_admin_web_login_state_artifacts.py tests/deploy/test_acs_local_debug_artifacts.py -q
python scripts/check_markdown_links.py .
ruby -e 'require "yaml"; ARGV.each { |path| YAML.load_file(path); puts "YAML ok: #{path}" }' \
  .github/workflows/pr-checks.yml \
  .github/workflows/publish-images.yml
git diff --check
```

Expected: all Node/Python tests pass, Markdown links resolve, both workflows parse, and no whitespace errors appear.

- [ ] **Step 6: Commit CI and documentation**

```bash
git add \
  .github/workflows/pr-checks.yml \
  .github/workflows/publish-images.yml \
  tests/deploy/test_admin_web_login_state_artifacts.py \
  docs/security-local-files.md \
  docs/testing.md \
  docs/development-handoff.md
git diff --cached --check
git diff --cached | rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET" || true
git commit -m "test: gate local Admin credential safety"
```

### Task 5: Full verification and local secure-file initialization

**Files:**
- Create locally, outside Git: `~/.config/ecommerce-cs-agent/admin-test-credentials.env`
- Create temporarily: `/tmp/ecommerce-admin-auth-<timestamp>/customer-admin.storageState.json`
- Create temporarily: `/tmp/ecommerce-admin-auth-<timestamp>/system-admin.storageState.json`

- [ ] **Step 1: Run the full deterministic gate**

Run:

```bash
npm run test:admin-credentials
npm --prefix admin-web test
npm --prefix admin-web run build
python -m pytest tests -q
helm lint deploy/helm/ecommerce-cs-agent -f deploy/helm/ecommerce-cs-agent/values-dev.yaml
helm template ecommerce-cs-agent deploy/helm/ecommerce-cs-agent \
  -n ecommerce-cs-agent-dev \
  -f deploy/helm/ecommerce-cs-agent/values-dev.yaml >/tmp/ecommerce-cs-agent-rendered.yaml
python scripts/check_k8s_security.py
python scripts/check_sensitive_patterns.py .
rm -f /tmp/ecommerce-cs-agent-rendered.yaml
git diff --check
```

Expected: all deterministic tests and builds pass; Helm renders; security checks report no credential file or secret value.

- [ ] **Step 2: Audit the complete branch diff for secrets**

Run:

```bash
base="$(git merge-base HEAD origin/main)"
git status --short
git diff --stat "$base"...HEAD
git diff "$base"...HEAD | rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET" || true
```

Expected: only the design, plan, and implementation files are present; matches are key names, fake fixtures, or documented patterns, never a live value.

- [ ] **Step 3: Create the local empty credential template**

Run:

```bash
node scripts/admin_web_login_state.mjs --init-credentials-file
```

Expected: the command reports the path only, does not attempt login, and does not print any of the four values.

Verify permissions without reading file content:

```bash
python - <<'PY'
from pathlib import Path
from stat import S_IMODE

path = Path.home() / ".config" / "ecommerce-cs-agent" / "admin-test-credentials.env"
print({
    "parent_mode": oct(S_IMODE(path.parent.stat().st_mode)),
    "file_mode": oct(S_IMODE(path.stat().st_mode)),
    "is_file": path.is_file(),
})
PY
```

Expected: `parent_mode` is `0o700`, `file_mode` is `0o600`, and `is_file` is `True`.

- [ ] **Step 4: Pause for the user to fill the four local values**

Tell the user to edit `~/.config/ecommerce-cs-agent/admin-test-credentials.env` directly on the Mac and reply only when it is ready. Do not ask the user to paste passwords, file contents, screenshots, or terminal output into chat.

- [ ] **Step 5: Generate and verify both temporary login states**

After the user confirms the file is filled, run:

```bash
output_dir="$(mktemp -d /tmp/ecommerce-admin-auth-verify-XXXXXX)"
chmod 700 "$output_dir"
node scripts/admin_web_login_state.mjs \
  --credentials-file "$HOME/.config/ecommerce-cs-agent/admin-test-credentials.env" \
  --skip-kubectl \
  --output-dir "$output_dir"
```

Expected: Customer `/v1/admin/auth/me` PASS and System `/v1/system-admin/auth/me` PASS; output names two storageState paths but prints no password or Cookie.

Verify modes and isolated Cookie names without printing Cookie values:

```bash
python - "$output_dir" <<'PY'
import json
from pathlib import Path
from stat import S_IMODE
import sys

root = Path(sys.argv[1])
customer = root / "customer-admin.storageState.json"
system = root / "system-admin.storageState.json"
customer_state = json.loads(customer.read_text())
system_state = json.loads(system.read_text())
print({
    "directory_mode": oct(S_IMODE(root.stat().st_mode)),
    "customer_mode": oct(S_IMODE(customer.stat().st_mode)),
    "system_mode": oct(S_IMODE(system.stat().st_mode)),
    "customer_cookie_names": [item["name"] for item in customer_state["cookies"]],
    "system_cookie_names": [item["name"] for item in system_state["cookies"]],
})
PY
```

Expected:

```text
directory_mode: 0o700
customer_mode: 0o600
system_mode: 0o600
customer_cookie_names: [agent_admin_session]
system_cookie_names: [agent_system_admin_session]
```

- [ ] **Step 6: Delete temporary session state**

Run:

```bash
rm -rf "$output_dir"
test ! -e "$output_dir"
```

Expected: the temporary directory no longer exists. Keep the owner-only credential file for later live tests.

- [ ] **Step 7: Commit verification fixes only when needed**

If full verification exposes a deterministic defect, first add a failing regression test, then implement the minimal fix and commit only the affected files:

```bash
git add scripts tests package.json .github docs
git commit -m "fix: harden local Admin credential handling"
```

If no defect is found, do not create an empty commit.
