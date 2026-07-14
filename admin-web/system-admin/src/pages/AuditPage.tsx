import React from "react";
import { Search } from "lucide-react";
import { DataTable, RequestStateView, SectionHeader } from "../../../shared/components";
import type { AuditFilters, PageEnvelope, RequestState } from "../system-types";

const emptyFilters: AuditFilters = { actor_user_id: "", organization_id: "", store_id: "", action: "", sensitive_access: "", time_from: "", time_to: "" };

export function AuditPage({ state, onSearch }: { state: RequestState<PageEnvelope>; onSearch: (filters: AuditFilters) => void }) {
  const [filters, setFilters] = React.useState(emptyFilters);
  return <>
    <SectionHeader label="SECURITY" title="安全审计" />
    <section className="auditFilters">
      {(["actor_user_id", "organization_id", "store_id", "action"] as const).map((key) => <input key={key} aria-label={key} placeholder={key} value={filters[key]} onChange={(event) => setFilters({ ...filters, [key]: event.target.value })} />)}
      <select aria-label="sensitive_access" value={filters.sensitive_access} onChange={(event) => setFilters({ ...filters, sensitive_access: event.target.value })}><option value="">敏感访问：全部</option><option value="true">仅敏感访问</option><option value="false">非敏感访问</option></select>
      <input type="datetime-local" aria-label="time_from" value={filters.time_from} onChange={(event) => setFilters({ ...filters, time_from: event.target.value })} />
      <input type="datetime-local" aria-label="time_to" value={filters.time_to} onChange={(event) => setFilters({ ...filters, time_to: event.target.value })} />
      <button type="button" onClick={() => onSearch(filters)}><Search size={16} />查询</button>
    </section>
    <RequestStateView state={state}>{(data) => <DataTable title={`审计记录（共 ${data.page.total} 条）`} rows={data.items} fields={["audit_log_id", "actor_system_user_id", "organization_id", "store_id", "action", "sensitive_access", "created_at"]} emptyState={{ title: "暂无审计记录", description: "服务端未返回符合筛选条件的审计记录。" }} />}</RequestStateView>
  </>;
}
