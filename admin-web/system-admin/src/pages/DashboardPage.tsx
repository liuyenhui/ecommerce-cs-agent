import React from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { DataTable, EmptyState, Metric, RequestStateView, SectionHeader } from "../../../shared/components";
import type { DashboardData, RequestState } from "../system-types";

const readinessTooltip = "未满足上线条件包括：缺少商品资料、缺少价格配置、缺少已审核知识、API 未完成接入等情况。";

function rate(value: number | null) {
  return value === null ? "暂无可计算数据" : `${(value * 100).toFixed(1)}%`;
}

export function DashboardPage({ state, onNavigate }: { state: RequestState<DashboardData>; onNavigate: (page: "readiness") => void }) {
  return <RequestStateView state={state}>{(data) => {
    const { summary } = data;
    return <>
      <SectionHeader label="OPERATIONS" title="系统总览" />
      <div className="metricGrid systemMetricGrid">
        <Metric label="活跃租户" value={String(summary.active_organizations)} tone="ok" />
        <Metric label="活跃店铺" value={String(summary.active_stores)} tone="info" />
        <Metric label="今日决策" value={String(summary.decisions_today)} tone="info" />
        <Metric label="自动回复率" value={rate(summary.auto_reply_rate)} tone="ok" />
        <Metric label="转人工率" value={rate(summary.handoff_rate)} tone="warn" />
        <Metric label="错误率" value={rate(summary.error_rate)} tone="bad" />
        <Metric label="未满足上线条件" value={String(summary.readiness_blockers)} tone="warn" title={readinessTooltip} />
        <Metric label="待处理任务" value={String(summary.pending_tasks)} tone="bad" />
      </div>
      <section className="priorityPanel">
        <h3><AlertTriangle size={17} />优先工作</h3>
        <div className="priorityGrid">
          <article><strong>{summary.critical_alerts}</strong><span>关键告警</span></article>
          <article><strong>{summary.readiness_blockers}</strong><span>未满足上线条件</span></article>
          <article><strong>{summary.pending_tasks}</strong><span>待处理任务</span></article>
        </div>
        {!summary.critical_alerts && !summary.readiness_blockers && !summary.pending_tasks
          ? <p className="healthyNotice"><CheckCircle2 size={16} />当前没有高优先级运营事项</p>
          : null}
      </section>
      <div className="twoColumns dashboardLists">
        <DataTable title="最近任务" rows={data.tasks.items} fields={["task_id", "task_type", "status", "updated_at"]} emptyState={{ title: "暂无最近任务", description: "服务端没有返回最近任务记录。" }} />
        {summary.recent_releases_status === "unavailable"
          ? <section className="tablePanel"><h3>最近发布</h3><EmptyState title="发布数据暂不可用" description="聚合指标仍可使用，请稍后重试发布记录查询。" /></section>
          : <DataTable title="最近发布" rows={summary.recent_releases} fields={["release_id", "organization_id", "version_number", "status", "published_at"]} emptyState={{ title: "暂无最近发布", description: "服务端没有返回发布记录。" }} />}
        <DataTable title="最近决策" rows={data.decisions.items} fields={["decision_id", "action", "status", "created_at"]} emptyState={{ title: "暂无最近决策", description: "当前时间范围内没有决策记录。" }} />
        <div className="dashboardReadinessSummary">
          <p className="panelDescription">以下店铺因缺少必要配置，暂时无法上线。</p>
          {data.readiness.items.length
            ? <DataTable title="缺少商品资料的店铺" rows={data.readiness.items} fields={["organization_id", "store_id", "status", "updated_at"]} />
            : <section className="tablePanel"><h3>缺少商品资料的店铺</h3><EmptyState title="暂无缺少商品资料的店铺" description="当前摘要中没有缺少商品资料的店铺。" /></section>}
          <div className="panelFooterAction"><button type="button" onClick={() => onNavigate("readiness")}>查看全部未满足上线条件的店铺</button></div>
        </div>
      </div>
      <p className="dataTimestamp">聚合生成时间：{summary.generated_at}</p>
    </>;
  }}</RequestStateView>;
}
