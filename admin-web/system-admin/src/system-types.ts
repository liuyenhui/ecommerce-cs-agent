import type { JsonRecord } from "../../shared/types";

export type SystemPage = "dashboard" | "tenants" | "readiness" | "llm" | "releases" | "traces" | "tasks" | "audit" | "health";

export type PageMeta = { page: number; page_size: number; total: number };
export type PageEnvelope<T extends JsonRecord = JsonRecord> = { items: T[]; page: PageMeta };

export type RequestState<T> =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; data: T }
  | { kind: "empty"; title: string; description: string }
  | { kind: "forbidden"; message: string }
  | { kind: "partial"; data: T; failures: string[] }
  | { kind: "error"; message: string };

export type DashboardSummary = {
  active_organizations: number;
  active_stores: number;
  decisions_today: number;
  auto_reply_rate: number | null;
  handoff_rate: number | null;
  error_rate: number | null;
  readiness_blockers: number;
  pending_tasks: number;
  critical_alerts: number;
  generated_at: string;
};

export type DashboardData = {
  summary: DashboardSummary;
  readiness: PageEnvelope;
  tasks: PageEnvelope;
  releases: PageEnvelope;
  decisions: PageEnvelope;
};

export type TenantData = { tenants: PageEnvelope; stores: PageEnvelope };

export type ReadinessCheck = JsonRecord & {
  code: string;
  status: "pass" | "warning" | "blocked";
  message: string;
  reason?: string;
  impact?: string;
  next_action?: string;
};

export type ReadinessRecord = JsonRecord & {
  organization_id?: string;
  tenant_id?: string;
  store_id: string;
  status: "ready" | "warning" | "blocked";
  checks: ReadinessCheck[];
  updated_at: string;
};

export type TaskRecord = JsonRecord & {
  task_id: string;
  task_type?: string;
  status?: string;
  retryable?: boolean;
};

export type HealthDependency = JsonRecord & {
  name: string;
  status: "healthy" | "degraded" | "unhealthy" | "not_configured";
  message?: string;
  checked_at: string;
};

export type SystemHealth = {
  status: "healthy" | "degraded" | "unhealthy";
  checked_at: string;
  dependencies: HealthDependency[];
};

export type AuditFilters = {
  actor_user_id: string;
  organization_id: string;
  store_id: string;
  action: string;
  sensitive_access: string;
  time_from: string;
  time_to: string;
};

export type TraceFilters = {
  organization_id: string;
  store_id: string;
  decision_id: string;
  time_from: string;
  time_to: string;
};
