import type { JsonRecord, RequestState as SharedRequestState } from "../../shared/types";

export type SystemPage = "dashboard" | "tenants" | "readiness" | "llm" | "releases" | "traces" | "tasks" | "audit" | "health";

export type PageMeta = { page: number; page_size: number; total: number };
export type PageEnvelope<T extends JsonRecord = JsonRecord> = { items: T[]; page: PageMeta };

export type RequestState<T> = SharedRequestState<T>;

export type SystemRecentRelease = JsonRecord & {
  release_id: string;
  organization_id: string;
  config_version_id: string;
  version_number: number;
  status: string;
  published_at: string | null;
  submitted_at: string;
};

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
  recent_releases: SystemRecentRelease[];
  recent_releases_status: "available" | "unavailable";
  recent_releases_error: "release_data_unavailable" | null;
  generated_at: string;
};

export type DashboardData = {
  summary: DashboardSummary;
  readiness: PageEnvelope;
  tasks: PageEnvelope;
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

export type LlmSecretReference = { namespace: string; name: string; key: string };
export type LlmProvider = {
  provider_id: string; name: string; provider_type: "openai" | "openai_compatible" | "anthropic" | "azure_openai";
  base_url: string; secret_ref: LlmSecretReference; enabled: boolean; status: string; revision: number;
  last_connection_test_status?: "passed" | "failed" | null; last_connection_test_latency_ms?: number | null;
  last_connection_test_error_code?: string | null; last_connection_tested_at?: string | null; created_at: string; updated_at: string;
};
export type LlmRoute = {
  route_id?: string; scenario: string; primary_provider_config_id: string; primary_model: string;
  fallback_provider_config_id: string | null; fallback_model: string | null; enabled: boolean; temperature: number;
  max_output_tokens: number; timeout_seconds: number; max_retries: number; circuit_breaker_threshold: number;
  recovery_probe_seconds: number; revision?: number;
};
export type LlmVersion = {
  version_id: string; organization_id: string; version_number: number;
  status: "draft" | "validated" | "pending_publish" | "running" | "superseded" | "rolled_back";
  revision: number; description?: string | null; configuration_hash: string; created_by_system_admin_user_id: string;
  created_at: string; published_by_system_admin_user_id: string | null; published_at: string | null;
  rollback_of_version_id: string | null; release_record_id: string | null; release_status: string | null;
  evaluation_run_id: string | null; routes: LlmRoute[]; release_record: JsonRecord | null; evaluation: { evaluation_run_id: string } | null;
};
export type CursorEnvelope<T> = { items: T[]; page_info: { limit: number; has_more: boolean; next_cursor: string | null } };
export type LlmUsageFilters = {
  start_at?: string; end_at?: string; provider_config_id?: string; model?: string; scenario?: string;
  organization_id?: string; store_id?: string; currency?: "CNY" | "USD"; status?: string; route_role?: string;
};
export type LlmUsageSummary = { calls: number; input_tokens: number; output_tokens: number; total_tokens: number; estimated_cost_micros: number | null; cost_by_currency: Record<string, number>; p95_latency_ms: number | null; error_rate: number | null; fallback_rate: number | null };
export type LlmUsagePoint = { bucket: string; currency: string; calls: number; input_tokens: number; output_tokens: number; estimated_cost_micros: number; errors: number };
export type LlmBreakdown = { key: string; currency: string; calls: number; total_tokens: number; estimated_cost_micros: number };
export type LlmInvocation = JsonRecord & { invocation_id: string; occurred_at: string; provider_config_id: string; provider_name: string; model: string; scenario: string; organization_id: string; store_id: string | null; route_role: string; input_tokens: number; output_tokens: number; latency_ms: number; status: string; error_code?: string | null; estimated_cost_micros: number; currency: string };
