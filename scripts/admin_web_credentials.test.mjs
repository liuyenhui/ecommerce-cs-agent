import assert from "node:assert/strict";
import fs, {
  chmodSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  renameSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
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

const completeText = `CUSTOMER_ADMIN_EMAIL="customer@example.test"
CUSTOMER_ADMIN_PASSWORD="customer pass; $HOME # inert"
SYSTEM_ADMIN_EMAIL="system@example.test"
SYSTEM_ADMIN_PASSWORD="system pass && echo inert"
`;

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
