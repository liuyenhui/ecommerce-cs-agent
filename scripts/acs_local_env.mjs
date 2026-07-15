#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const namespace = process.env.ACS_DEV_NAMESPACE || "ecommerce-cs-agent-dev";
const secretName = process.env.ACS_DEV_SECRET || "ecommerce-cs-agent-runtime";
const cursorSecretName = process.env.ACS_DEV_LLM_CURSOR_SECRET || "ecommerce-cs-agent-llm-cursor";
const cursorSecretKey = process.env.ACS_DEV_LLM_CURSOR_SECRET_KEY || "signing-key";
const kubeconfig = expandHome(process.env.ACS_DEV_KUBECONFIG || "~/.kube/bpg-debian12-master-public.yaml");
const outputFile = path.resolve(root, process.env.ACS_LOCAL_ENV_FILE || ".local/acs-runtime.env");
const postgresHost = process.env.ACS_LOCAL_POSTGRES_HOST || "127.0.0.1";
const postgresPort = process.env.ACS_LOCAL_POSTGRES_PORT || "15432";
const objectStorageEndpoint = process.env.ACS_LOCAL_OBJECT_STORAGE_ENDPOINT || "http://127.0.0.1:19000";

function expandHome(value) {
  if (value === "~") return os.homedir();
  if (value.startsWith("~/")) return path.join(os.homedir(), value.slice(2));
  return value;
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", "'\"'\"'")}'`;
}

function rewriteDatabaseUrl(value) {
  if (!value) return value;
  const url = new URL(value);
  url.hostname = postgresHost;
  url.port = postgresPort;
  url.searchParams.set("sslmode", "disable");
  return url.toString();
}

function readSecret(name) {
  return JSON.parse(
    execFileSync(
      "kubectl",
      ["--kubeconfig", kubeconfig, "-n", namespace, "get", "secret", name, "-o", "json"],
      { encoding: "utf8" }
    )
  );
}

const secret = readSecret(secretName);
const values = Object.fromEntries(
  Object.entries(secret.data || {}).map(([key, encoded]) => [key, Buffer.from(String(encoded), "base64").toString("utf8")])
);
const skippedKeys = Object.keys(values).filter((key) => !/^[A-Za-z_][A-Za-z0-9_]*$/.test(key));
const cursorSecret = readSecret(cursorSecretName);
const cursorSigningKey = Buffer.from(String(cursorSecret.data?.[cursorSecretKey] || ""), "base64").toString("utf8");

if (!values.DATABASE_URL) {
  throw new Error(`${secretName} is missing DATABASE_URL`);
}
if (Buffer.byteLength(cursorSigningKey, "utf8") < 32) {
  throw new Error(`${cursorSecretName}/${cursorSecretKey} must contain at least 32 bytes`);
}

values.DATABASE_URL = rewriteDatabaseUrl(values.DATABASE_URL);
values.OBJECT_STORAGE_ENDPOINT = objectStorageEndpoint;
values.LLM_CURSOR_SIGNING_KEY = cursorSigningKey;

fs.mkdirSync(path.dirname(outputFile), { recursive: true, mode: 0o700 });
const envText = Object.keys(values)
  .filter((key) => /^[A-Za-z_][A-Za-z0-9_]*$/.test(key))
  .sort()
  .map((key) => `export ${key}=${shellQuote(values[key])}`)
  .join("\n");
fs.writeFileSync(outputFile, `${envText}\n`, { mode: 0o600 });
fs.chmodSync(outputFile, 0o600);

console.log(`Wrote local ACS env file: ${outputFile}`);
console.log(`Loaded ${Object.keys(values).length} local runtime settings from the configured Kubernetes Secrets`);
if (skippedKeys.length > 0) {
  console.log(`Skipped ${skippedKeys.length} non-shell-compatible secret keys`);
}
console.log(`DATABASE_URL host rewritten to ${postgresHost}:${postgresPort}`);
console.log(`OBJECT_STORAGE_ENDPOINT rewritten to ${objectStorageEndpoint}`);
