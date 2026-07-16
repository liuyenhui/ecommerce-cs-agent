import {
  chmodSync,
  closeSync,
  constants,
  fstatSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  realpathSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import {
  basename,
  dirname,
  isAbsolute,
  join,
  relative,
  resolve,
  sep,
} from "node:path";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";

const MODULE_REPOSITORY_ROOT = fileURLToPath(new URL("..", import.meta.url));

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

function defaultExpectedUid() {
  return typeof process.getuid === "function" ? process.getuid() : undefined;
}

function lstatEntry(filePath) {
  try {
    return lstatSync(filePath);
  } catch (error) {
    if (error?.code === "ENOENT") {
      return undefined;
    }
    throw error;
  }
}

function isPathContainedBy(parentPath, candidatePath) {
  const relativePath = relative(parentPath, candidatePath);
  return (
    relativePath === "" ||
    (relativePath !== ".." &&
      !relativePath.startsWith(`..${sep}`) &&
      !isAbsolute(relativePath))
  );
}

function repositoryPaths(repositoryRoot) {
  return {
    lexical: resolve(repositoryRoot),
    real: realpathSync(repositoryRoot),
  };
}

function assertOutsideRepository(candidatePath, repositories) {
  if (
    isPathContainedBy(repositories.lexical, candidatePath) ||
    isPathContainedBy(repositories.real, candidatePath)
  ) {
    throw new Error("Credential file must be outside the repository.");
  }
}

function predictedRealPath(targetPath) {
  const missingComponents = [];
  let existingAncestor = targetPath;

  while (lstatEntry(existingAncestor) === undefined) {
    const ancestorParent = dirname(existingAncestor);
    if (ancestorParent === existingAncestor) {
      throw new Error("Credential file parent has no existing ancestor.");
    }
    missingComponents.unshift(basename(existingAncestor));
    existingAncestor = ancestorParent;
  }

  return resolve(realpathSync(existingAncestor), ...missingComponents);
}

function assertSecureParent(parentPath, expectedUid, checkMode = true) {
  const parentInfo = lstatSync(parentPath);
  if (parentInfo.isSymbolicLink()) {
    throw new Error("Credential file parent must not be a symbolic link.");
  }
  if (!parentInfo.isDirectory()) {
    throw new Error("Credential file parent must be a directory.");
  }
  if (expectedUid !== undefined && parentInfo.uid !== expectedUid) {
    throw new Error("Credential file parent must be owned by the expected user.");
  }
  if (checkMode && (parentInfo.mode & 0o777) !== 0o700) {
    throw new Error("Credential file parent must have mode 0700.");
  }
}

function assertSecureFileInfo(fileInfo, expectedUid) {
  if (!fileInfo.isFile()) {
    throw new Error("Credential file must be a regular file.");
  }
  if (expectedUid !== undefined && fileInfo.uid !== expectedUid) {
    throw new Error("Credential file must be owned by the expected user.");
  }
  if ((fileInfo.mode & 0o777) !== 0o600) {
    throw new Error("Credential file must have mode 0600.");
  }
}

function assertSecureFile(filePath, expectedUid) {
  const fileInfo = lstatSync(filePath);
  if (fileInfo.isSymbolicLink()) {
    throw new Error("Credential file must not be a symbolic link.");
  }
  assertSecureFileInfo(fileInfo, expectedUid);
}

function secureCredentialContext({
  filePath = defaultAdminCredentialsFile(),
  repositoryRoot = MODULE_REPOSITORY_ROOT,
  expectedUid = defaultExpectedUid(),
} = {}) {
  const resolvedFilePath = resolve(filePath);
  const repositories = repositoryPaths(repositoryRoot);
  assertOutsideRepository(resolvedFilePath, repositories);

  const parentPath = dirname(resolvedFilePath);
  assertSecureParent(parentPath, expectedUid);
  assertOutsideRepository(realpathSync(parentPath), repositories);

  return { expectedUid, resolvedFilePath };
}

export function assertSecureAdminCredentialFile({
  filePath = defaultAdminCredentialsFile(),
  repositoryRoot = MODULE_REPOSITORY_ROOT,
  expectedUid = defaultExpectedUid(),
} = {}) {
  const context = secureCredentialContext({
    filePath,
    repositoryRoot,
    expectedUid,
  });
  const { resolvedFilePath } = context;
  assertSecureFile(resolvedFilePath, expectedUid);

  return resolvedFilePath;
}

export function initializeAdminCredentialFile({
  filePath = defaultAdminCredentialsFile(),
  repositoryRoot = MODULE_REPOSITORY_ROOT,
  expectedUid = defaultExpectedUid(),
} = {}) {
  const resolvedFilePath = resolve(filePath);
  const repositories = repositoryPaths(repositoryRoot);
  assertOutsideRepository(resolvedFilePath, repositories);

  if (lstatEntry(resolvedFilePath) !== undefined) {
    throw new Error("Credential file already exists.");
  }

  const parentPath = dirname(resolvedFilePath);
  assertOutsideRepository(predictedRealPath(parentPath), repositories);
  mkdirSync(parentPath, { recursive: true, mode: 0o700 });
  assertSecureParent(parentPath, expectedUid, false);
  chmodSync(parentPath, 0o700);
  assertOutsideRepository(realpathSync(parentPath), repositories);

  try {
    writeFileSync(resolvedFilePath, ADMIN_CREDENTIAL_TEMPLATE, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
  } catch (error) {
    if (error?.code === "EEXIST") {
      throw new Error("Credential file already exists.");
    }
    throw error;
  }
  chmodSync(resolvedFilePath, 0o600);
  return assertSecureAdminCredentialFile({
    filePath: resolvedFilePath,
    repositoryRoot,
    expectedUid,
  });
}

export function loadAdminCredentialFile(options = {}) {
  const { expectedUid, resolvedFilePath } = secureCredentialContext(options);
  if (typeof constants.O_NOFOLLOW !== "number") {
    throw new Error(
      "Secure credential loading requires O_NOFOLLOW filesystem support.",
    );
  }

  let fileDescriptor;
  try {
    fileDescriptor = openSync(
      resolvedFilePath,
      constants.O_RDONLY | constants.O_NOFOLLOW,
    );
    assertSecureFileInfo(fstatSync(fileDescriptor), expectedUid);
    return parseAdminCredentialText(readFileSync(fileDescriptor, "utf8"));
  } catch (error) {
    if (error?.code === "ELOOP") {
      throw new Error("Credential file must not be a symbolic link.");
    }
    throw error;
  } finally {
    if (fileDescriptor !== undefined) {
      closeSync(fileDescriptor);
    }
  }
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
