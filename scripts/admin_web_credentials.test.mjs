import assert from "node:assert/strict";
import test from "node:test";

import {
  ADMIN_CREDENTIAL_KEYS,
  ADMIN_CREDENTIAL_TEMPLATE,
  defaultAdminCredentialsFile,
  mergeAdminCredentialSources,
  parseAdminCredentialText,
} from "./admin_web_credentials.mjs";

const completeText = `CUSTOMER_ADMIN_EMAIL="customer@example.test"
CUSTOMER_ADMIN_PASSWORD="customer pass; $HOME # inert"
SYSTEM_ADMIN_EMAIL="system@example.test"
SYSTEM_ADMIN_PASSWORD="system pass && echo inert"
`;

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
