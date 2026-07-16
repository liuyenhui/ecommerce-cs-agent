import { homedir } from "node:os";
import { join } from "node:path";
import { parseEnv } from "node:util";

export const ADMIN_CREDENTIAL_KEYS = Object.freeze([
  "CUSTOMER_ADMIN_EMAIL",
  "CUSTOMER_ADMIN_PASSWORD",
  "SYSTEM_ADMIN_EMAIL",
  "SYSTEM_ADMIN_PASSWORD",
]);

export const ADMIN_CREDENTIAL_TEMPLATE = `${ADMIN_CREDENTIAL_KEYS.map((key) => `${key}=`).join("\n")}\n`;

export function defaultAdminCredentialsFile(homeDirectory = homedir()) {
  return join(
    homeDirectory,
    ".config",
    "ecommerce-cs-agent",
    "admin-test-credentials.env",
  );
}

function hasValidAssignmentValue(value) {
  if (value.startsWith('"')) {
    return /^"[^"]*"\s*(?:#.*)?$/u.test(value);
  }
  if (value.startsWith("'")) {
    return /^'[^']*'\s*(?:#.*)?$/u.test(value);
  }

  const commentStart = value.indexOf("#");
  const unquotedValue =
    commentStart === -1 ? value : value.slice(0, commentStart);
  return !/["']/u.test(unquotedValue);
}

function assignmentKeys(text) {
  const keys = [];

  for (const [index, line] of text.split(/\r?\n/u).entries()) {
    if (/^\s*(?:#.*)?$/u.test(line)) {
      continue;
    }

    const assignment = line.match(
      /^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/u,
    );
    if (!assignment || !hasValidAssignmentValue(assignment[2])) {
      throw new Error(
        `Credential file contains invalid assignment at line ${index + 1}.`,
      );
    }
    keys.push(assignment[1]);
  }

  return keys;
}

export function parseAdminCredentialText(text) {
  const keys = assignmentKeys(text);
  if (new Set(keys).size !== keys.length) {
    throw new Error("Credential file contains duplicate keys.");
  }

  let parsed;
  try {
    parsed = parseEnv(text);
  } catch {
    throw new Error("Credential file contains invalid environment syntax.");
  }

  if (keys.some((key) => !ADMIN_CREDENTIAL_KEYS.includes(key))) {
    throw new Error("Credential file contains unknown keys.");
  }
  if (ADMIN_CREDENTIAL_KEYS.some((key) => !Object.hasOwn(parsed, key))) {
    throw new Error("Credential file is missing required keys.");
  }
  if (ADMIN_CREDENTIAL_KEYS.some((key) => parsed[key].length === 0)) {
    throw new Error("Credential file contains blank values.");
  }

  return Object.fromEntries(
    ADMIN_CREDENTIAL_KEYS.map((key) => [key, parsed[key]]),
  );
}

export function mergeAdminCredentialSources(
  fileCredentials = {},
  environment = {},
) {
  return Object.fromEntries(
    ADMIN_CREDENTIAL_KEYS.flatMap((key) => {
      const environmentValue = environment[key];
      if (typeof environmentValue === "string" && environmentValue.length > 0) {
        return [[key, environmentValue]];
      }
      if (
        Object.hasOwn(fileCredentials, key) &&
        fileCredentials[key] !== undefined
      ) {
        return [[key, fileCredentials[key]]];
      }
      return [];
    }),
  );
}
