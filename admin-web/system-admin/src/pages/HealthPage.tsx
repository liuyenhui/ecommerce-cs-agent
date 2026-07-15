import React from "react";
import { RequestStateView, SectionHeader } from "../../../shared/components";
import type { HealthDependency, RequestState, SystemHealth } from "../system-types";

const groupNames = { application: "应用", dependency: "依赖", deployment: "部署" } as const;

function groupFor(name: string): keyof typeof groupNames {
  if (["api", "worker"].includes(name)) return "application";
  if (["k8s_deployment", "ingress"].includes(name)) return "deployment";
  return "dependency";
}

function effectiveStatus(health: SystemHealth) {
  if (health.dependencies.some((item) => item.status === "unhealthy")) return "unhealthy";
  if (health.dependencies.some((item) => item.status !== "healthy")) return "degraded";
  return health.status;
}

function DependencyRow({ item }: { item: HealthDependency }) {
  return <li><div><strong>{item.name}</strong><span>{item.message || "未提供附加说明"}</span></div><em className={item.status}>{item.status}</em></li>;
}

export function HealthPage({ state }: { state: RequestState<SystemHealth> }) {
  return <RequestStateView state={state}>{(health) => <>
    <SectionHeader label="HEALTH" title="系统健康" />
    <div className={`healthSummary ${effectiveStatus(health)}`}><span>整体状态</span><strong>{effectiveStatus(health)}</strong><small>检查时间：{health.checked_at}</small></div>
    <div className="healthGroups">
      {(Object.keys(groupNames) as Array<keyof typeof groupNames>).map((group) => <section key={group}><h3>{groupNames[group]}</h3><ul>{health.dependencies.filter((item) => groupFor(item.name) === group).map((item) => <DependencyRow key={item.name} item={item} />)}</ul>{health.dependencies.some((item) => groupFor(item.name) === group) ? null : <p className="emptyText">服务端未返回此类检查项。</p>}</section>)}
    </div>
  </>}</RequestStateView>;
}
