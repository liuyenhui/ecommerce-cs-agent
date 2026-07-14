import React from "react";
import { RequestStateView, SectionHeader } from "../../../shared/components";
import type { PageEnvelope, ReadinessCheck, ReadinessRecord, RequestState } from "../system-types";

const checkGuidance: Record<string, { impact: string; next: string }> = {
  product_content: { impact: "AI 无法可靠识别商品与回答商品问题。", next: "导入并确认商品资料。" },
  price_snapshot: { impact: "价格相关回答无法使用当前有效数据。", next: "同步有效价格快照。" },
  knowledge_review: { impact: "没有审核通过的知识可用于安全回复。", next: "完成知识审核并发布。" },
  rules: { impact: "业务规则可能无法约束决策。", next: "配置并启用店铺规则。" },
  action_capabilities: { impact: "需要外部操作时无法安全执行。", next: "配置允许的动作能力。" },
  api_integration: { impact: "系统无法补充实时外部上下文。", next: "完成 API 接入与连接验证。" }
};

function BlockedCheck({ check }: { check: ReadinessCheck }) {
  const guidance = checkGuidance[check.code] || { impact: "该检查会阻断店铺上线。", next: "按检查说明完成配置后重新检查。" };
  return <li className={`readinessCheck ${check.status}`}>
    <strong>{check.code}</strong>
    <dl>
      <div><dt>原因</dt><dd>{check.reason || check.message}</dd></div>
      <div><dt>影响</dt><dd>{check.impact || guidance.impact}</dd></div>
      <div><dt>下一步</dt><dd>{check.next_action || guidance.next}</dd></div>
    </dl>
  </li>;
}

export function ReadinessPage({ state }: { state: RequestState<PageEnvelope<ReadinessRecord>> }) {
  return <RequestStateView state={state}>{(data) => <>
    <SectionHeader label="READINESS" title="配置完成度" />
    <p className="pageTotal">共 {data.page.total} 家店铺</p>
    <div className="readinessList">
      {data.items.map((item) => <article className="readinessCard" key={item.store_id}>
        <header><div><strong>{item.store_id}</strong><span>{item.organization_id || item.tenant_id || "-"}</span></div><em className={item.status}>{item.status}</em></header>
        {item.checks.some((check) => check.status !== "pass")
          ? <ul>{item.checks.filter((check) => check.status !== "pass").map((check) => <BlockedCheck key={check.code} check={check} />)}</ul>
          : <p className="healthyNotice">所有上线检查均已通过。</p>}
      </article>)}
    </div>
  </>}</RequestStateView>;
}
