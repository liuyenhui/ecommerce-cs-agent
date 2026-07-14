import { requestJson } from "../../shared/api";
import type { JsonRecord } from "../../shared/types";
import type {
  AuditFilters,
  DashboardSummary,
  PageEnvelope,
  PageMeta,
  SystemHealth,
  TraceFilters
} from "./system-types";

export const SYSTEM_ADMIN_URLS = {
  login: "/v1/system-admin/auth/login",
  logout: "/v1/system-admin/auth/logout",
  me: "/v1/system-admin/auth/me",
  dashboardSummary: "/v1/system-admin/dashboard-summary",
  tenants: "/v1/system-admin/organizations",
  stores: "/v1/system-admin/stores",
  readiness: "/v1/system-admin/readiness/stores",
  traces: "/v1/system-admin/message-traces",
  tasks: "/v1/system-admin/tasks",
  audit: "/v1/system-admin/audit-logs",
  health: "/v1/system-admin/health",
  llmProviders: "/v1/system-admin/llm/providers",
  releases: "/v1/system-admin/llm/config-versions"
} as const;

export function traceDetailPath(decisionId: string) {
  return `${SYSTEM_ADMIN_URLS.traces}/${encodeURIComponent(decisionId)}`;
}

export function taskRetryPath(taskId: string) {
  return `${SYSTEM_ADMIN_URLS.tasks}/${encodeURIComponent(taskId)}/retry`;
}

export function systemAdminPaths(decisionId: string, taskId: string) {
  return [traceDetailPath(decisionId), taskRetryPath(taskId)];
}

function queryPath(path: string, filters: Record<string, string | number | boolean | undefined>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== "" && value !== undefined) params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

type RawPage<T> = { items?: T[]; page_info?: Partial<PageMeta> };

function normalizePage<T extends JsonRecord>(response: RawPage<T>): PageEnvelope<T> {
  return {
    items: response.items || [],
    page: {
      page: Number(response.page_info?.page || 1),
      page_size: Number(response.page_info?.page_size || 20),
      total: Number(response.page_info?.total || 0)
    }
  };
}

async function pageRequest<T extends JsonRecord>(path: string, filters: Record<string, string | number | boolean | undefined> = {}, signal?: AbortSignal) {
  return normalizePage(await requestJson<RawPage<T>>(queryPath(path, filters), { signal }));
}

export const systemApi = {
  login: async (email: string, password: string, signal?: AbortSignal) => {
    await requestJson(SYSTEM_ADMIN_URLS.login, { method: "POST", body: JSON.stringify({ email, password }), signal });
    return requestJson<JsonRecord>(SYSTEM_ADMIN_URLS.me, { signal });
  },
  me: (signal?: AbortSignal) => requestJson<JsonRecord>(SYSTEM_ADMIN_URLS.me, { signal }),
  logout: (signal?: AbortSignal) => requestJson(SYSTEM_ADMIN_URLS.logout, { method: "POST", signal }),
  dashboardSummary: (signal?: AbortSignal) => requestJson<DashboardSummary>(SYSTEM_ADMIN_URLS.dashboardSummary, { signal }),
  tenants: (filters: Record<string, string | number | boolean | undefined> = {}, signal?: AbortSignal) => pageRequest(SYSTEM_ADMIN_URLS.tenants, filters, signal),
  stores: (filters: Record<string, string | number | boolean | undefined> = {}, signal?: AbortSignal) => pageRequest(SYSTEM_ADMIN_URLS.stores, filters, signal),
  readiness: (filters: Record<string, string | number | boolean | undefined> = {}, signal?: AbortSignal) => pageRequest(SYSTEM_ADMIN_URLS.readiness, filters, signal),
  traces: (filters: TraceFilters | Record<string, string | number>, signal?: AbortSignal) => pageRequest(SYSTEM_ADMIN_URLS.traces, filters, signal),
  trace: (decisionId: string, signal?: AbortSignal) => requestJson<JsonRecord>(traceDetailPath(decisionId), { signal }),
  tasks: (filters: Record<string, string | number | boolean | undefined> = {}, signal?: AbortSignal) => pageRequest(SYSTEM_ADMIN_URLS.tasks, filters, signal),
  retryTask: (taskId: string, reason: string) => requestJson(taskRetryPath(taskId), {
    method: "POST",
    body: JSON.stringify({ idempotency_key: `system-admin-${crypto.randomUUID()}`, reason })
  }),
  audit: (filters: AuditFilters | Record<string, string | number>, signal?: AbortSignal) => pageRequest(SYSTEM_ADMIN_URLS.audit, filters, signal),
  health: (signal?: AbortSignal) => requestJson<SystemHealth>(SYSTEM_ADMIN_URLS.health, { signal }),
  releases: (filters: Record<string, string | number | boolean | undefined> = {}, signal?: AbortSignal) => pageRequest(SYSTEM_ADMIN_URLS.releases, filters, signal)
};

export function requestFailure(error: unknown): { kind: "forbidden"; message: string } | { kind: "error"; message: string } {
  const message = error instanceof Error ? error.message : String(error);
  return message.startsWith("403 ")
    ? { kind: "forbidden", message: "当前系统后台角色无权访问此数据。" }
    : { kind: "error", message: message || "系统数据加载失败，请稍后重试。" };
}
