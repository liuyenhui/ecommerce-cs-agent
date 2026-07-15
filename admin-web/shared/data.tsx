import type { EmptyStateProps, JsonRecord } from "./types";

const statusTone: Record<string, "ok" | "warn" | "bad" | "info"> = {
  active: "ok",
  healthy: "ok",
  ok: "ok",
  completed: "ok",
  accepted: "ok",
  pending: "warn",
  waiting_context: "warn",
  failed: "bad",
  blocked: "bad",
  error: "bad",
  frozen: "bad"
};

const statusLabel: Record<string, string> = {
  active: "启用",
  healthy: "健康",
  ok: "正常",
  completed: "已完成",
  accepted: "已受理",
  pending: "待处理",
  waiting_context: "等待补充上下文",
  failed: "失败",
  blocked: "阻断",
  error: "异常",
  frozen: "冻结"
};

const fieldLabels: Record<string, string> = {
  id: "ID",
  name: "名称",
  organization_id: "客户 ID",
  store_id: "店铺 ID",
  external_product_id: "外部商品 ID",
  title: "商品名称",
  health_status: "资料健康",
  status: "状态",
  reason: "原因",
  platform: "平台",
  created_at: "创建时间",
  updated_at: "更新时间",
  decision_id: "决策 ID",
  risk_level: "风险等级",
  task_id: "任务 ID",
  task_type: "任务类型",
  retryable: "可重试",
  audit_log_id: "审计 ID",
  release_id: "发布 ID",
  version_number: "版本号",
  published_at: "发布时间",
  actor_system_user_id: "操作者 ID",
  sensitive_access: "敏感访问",
  action: "动作",
  object_type: "对象类型",
  message: "消息"
};

export type SummaryItem = { label: string; value: string };

export function renderCell(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string") {
    const tone = toneFor(value);
    return tone ? <span className={`status ${tone}`} title={value}>{statusLabel[value] || value}</span> : <span>{value}</span>;
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return <code>{JSON.stringify(value)}</code>;
  return String(value);
}

export function fieldLabel(field: string) {
  return fieldLabels[field] || field.split("_").filter(Boolean).map((part) => `${part[0]?.toUpperCase() || ""}${part.slice(1)}`).join(" ");
}

export function tableEmptyState(title: string): EmptyStateProps {
  if (title.includes("审计")) {
    return { title: "暂无审计记录", description: "当前筛选范围内还没有审计事件；执行管理操作或调整组织、店铺筛选后再查看。" };
  }
  if (title.includes("任务")) {
    return { title: "暂无任务", description: "当前没有异步任务需要处理；失败或待重试任务出现后会在这里显示。" };
  }
  if (title.includes("组件检查")) {
    return { title: "暂无检查项", description: "当前健康接口没有返回组件检查明细；请刷新系统健康数据后再查看。" };
  }
  return { title: `暂无${title}`, description: "当前没有可展示的数据；调整筛选条件或完成配置后再查看。" };
}

export function arrayFrom(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.filter((item): item is JsonRecord => Boolean(item) && typeof item === "object") : [];
}

export function readRecord(source: unknown, key: string): JsonRecord {
  if (!source || typeof source !== "object") return {};
  const value = (source as JsonRecord)[key];
  return value && typeof value === "object" ? value as JsonRecord : {};
}

export function safeText(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

export function firstText(...values: unknown[]) {
  for (const value of values) {
    const list = stringList(value);
    if (list.length) return list[0];
    const text = safeText(value);
    if (text) return text;
  }
  return "";
}

export function stringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => safeText(item)).filter(Boolean);
  const text = safeText(value);
  return text ? [text] : [];
}

export function countCapabilities(value: unknown) {
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === "object") return Object.keys(value).length;
  return 0;
}

export function firstId(value: unknown, fallback: string) {
  const first = arrayFrom(value)[0];
  return String(first?.id || first?.organization_id || first?.store_id || fallback);
}

export function toneFor(value: string): "ok" | "warn" | "bad" | "info" | "" {
  return statusTone[value.toLowerCase()] || "";
}

export function buildQuery(filters: Record<string, string>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value && key !== "trace_id") params.set(key, value);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function buildSystemUserSummary(user: JsonRecord): SummaryItem[] {
  const items: SummaryItem[] = [];
  const displayName = safeText(user.display_name) || safeText(user.name);
  const roles = stringList(user.roles || user.role);
  const status = safeText(user.status);
  const capabilitiesCount = countCapabilities(user.capabilities);
  const lastLoginAt = safeText(user.last_login_at);

  if (displayName) items.push({ label: "名称", value: displayName });
  if (roles.length) items.push({ label: "角色", value: roles.join(", ") });
  if (status) items.push({ label: "状态", value: status });
  if (capabilitiesCount > 0) items.push({ label: "能力", value: `${capabilitiesCount} 项` });
  if (lastLoginAt) items.push({ label: "最近登录", value: lastLoginAt });

  return items;
}
