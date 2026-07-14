import React from "react";
import { Search } from "lucide-react";
import { DataTable, RequestStateView, SectionHeader } from "../../../shared/components";
import { readRecord } from "../../../shared/data";
import { DecisionTraceReplay } from "../../../shared/trace-replay";
import type { JsonRecord } from "../../../shared/types";
import type { PageEnvelope, RequestState, TraceFilters } from "../system-types";

const emptyFilters: TraceFilters = { organization_id: "", store_id: "", decision_id: "", time_from: "", time_to: "" };

export function TracesPage({ state, detail, onSearch, onOpen, onClose }: {
  state: RequestState<PageEnvelope>;
  detail: JsonRecord | null;
  onSearch: (filters: TraceFilters) => void;
  onOpen: (decisionId: string) => void;
  onClose: () => void;
}) {
  const [filters, setFilters] = React.useState(emptyFilters);
  const trace = detail ? readRecord(detail, "trace") : {};
  return <>
    <SectionHeader label="TRACE" title="决策追踪" />
    <section className="filterBar systemFilterBar">
      {(["organization_id", "store_id", "decision_id", "time_from", "time_to"] as const).map((key) => <input key={key} aria-label={key} placeholder={key} type={key.startsWith("time_") ? "datetime-local" : "text"} value={filters[key]} onChange={(event) => setFilters({ ...filters, [key]: event.target.value })} />)}
      <button type="button" onClick={() => onSearch(filters)}><Search size={16} />查询</button>
    </section>
    <RequestStateView state={state}>{(data) => <><p className="pageTotal">共 {data.page.total} 条决策</p><DataTable title="消息决策" rows={data.items} fields={["decision_id", "organization_id", "store_id", "action", "status", "created_at"]} action={(row) => <button type="button" onClick={() => onOpen(String(row.decision_id || ""))}>运行回放</button>} emptyState={{ title: "暂无决策记录", description: "请提供租户、店铺、Decision ID 或时间范围查询真实记录。" }} /></>}</RequestStateView>
    {detail ? <aside className="drawer messageTraceDrawer"><div className="drawerHeader"><h2>决策运行回放</h2><button type="button" onClick={onClose}>关闭</button></div><DecisionTraceReplay trace={readRecord(trace, "trace")} action={trace.action} status={trace.status || trace.decision_status} risk={trace.risk_level} /></aside> : null}
  </>;
}
