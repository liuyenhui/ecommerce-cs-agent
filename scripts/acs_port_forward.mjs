#!/usr/bin/env node
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";

const namespace = process.env.ACS_DEV_NAMESPACE || "ecommerce-cs-agent-dev";
const kubeconfig = expandHome(process.env.ACS_DEV_KUBECONFIG || "~/.kube/bpg-debian12-master-public.yaml");

function expandHome(value) {
  if (value === "~") return os.homedir();
  if (value.startsWith("~/")) return path.join(os.homedir(), value.slice(2));
  return value;
}

const forwards = [
  { name: "postgres", resource: "svc/postgres", mapping: "15432:5432" },
  { name: "minio", resource: "svc/minio", mapping: "19000:9000" }
];

const children = forwards.map((forward) => {
  const child = spawn(
    "kubectl",
    ["--kubeconfig", kubeconfig, "-n", namespace, "port-forward", forward.resource, forward.mapping],
    { stdio: ["ignore", "pipe", "pipe"] }
  );
  child.stdout.on("data", (chunk) => process.stdout.write(`[${forward.name}] ${chunk}`));
  child.stderr.on("data", (chunk) => process.stderr.write(`[${forward.name}] ${chunk}`));
  child.on("exit", (code, signal) => {
    if (!shuttingDown) {
      console.error(`[${forward.name}] port-forward exited code=${code ?? ""} signal=${signal ?? ""}`);
      shutdown(1);
    }
  });
  return child;
});

let shuttingDown = false;

function shutdown(exitCode = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) child.kill("SIGTERM");
  }
  setTimeout(() => process.exit(exitCode), 250).unref();
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

console.log(`Forwarding K3s dev services from namespace ${namespace}`);
console.log("PostgreSQL: 127.0.0.1:15432 -> svc/postgres:5432");
console.log("MinIO:      127.0.0.1:19000 -> svc/minio:9000");
