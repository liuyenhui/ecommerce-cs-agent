import React from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Drawer, RequestStateView, SectionHeader } from "../../../shared/components";
import { renderCell } from "../../../shared/data";
import type { JsonRecord } from "../../../shared/types";
import type { RequestState, TenantData } from "../system-types";
import { PaginationControls } from "./PaginationControls";

export function TenantsPage({ state, onTenantPageChange }: {
  state: RequestState<TenantData>;
  onTenantPageChange?: (page: number) => void;
}) {
  const [selected, setSelected] = React.useState<{ title: string; record: JsonRecord } | null>(null);
  const [collapsedTenantIds, setCollapsedTenantIds] = React.useState<Set<string>>(() => new Set());

  function toggleTenant(tenantId: string) {
    setCollapsedTenantIds((current) => {
      const next = new Set(current);
      if (next.has(tenantId)) next.delete(tenantId);
      else next.add(tenantId);
      return next;
    });
  }

  return <RequestStateView state={state}>{(data) => {
    const storesByTenant = new Map<string, JsonRecord[]>();
    data.stores.items.forEach((store) => {
      const tenantId = String(store.organization_id || "");
      storesByTenant.set(tenantId, [...(storesByTenant.get(tenantId) || []), store]);
    });

    return <>
      <SectionHeader label="TENANT OPERATIONS" title="租户与店铺" />
      <p className="pageTotal">共 {data.tenants.page.total} 个租户、{data.stores.page.total} 家店铺</p>
      <section className="tablePanel tenantStorePanel">
        <h3>租户与店铺</h3>
        <div className="tenantStoreTableWrap">
          <table className="tenantStoreTable" aria-label="租户与店铺">
            <thead><tr><th>名称 / ID</th><th>类型</th><th>平台</th><th>状态</th><th>创建时间</th></tr></thead>
            <tbody>
              {data.tenants.items.map((tenant) => {
                const tenantId = String(tenant.organization_id || tenant.id || "");
                const tenantName = String(tenant.name || tenantId || "未命名租户");
                const stores = storesByTenant.get(tenantId) || [];
                const expanded = !collapsedTenantIds.has(tenantId);
                const childRowsId = `tenant-stores-${tenantId.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
                return <React.Fragment key={tenantId}>
                  <tr className="tenantStoreRow tenantStoreTenantRow">
                    <td data-label="名称 / ID">
                      <div className="tenantStoreIdentity">
                        <button
                          type="button"
                          className="tenantStoreExpand"
                          aria-label={`${expanded ? "收起" : "展开"}${tenantName}的店铺`}
                          aria-expanded={expanded}
                          aria-controls={childRowsId}
                          onClick={() => toggleTenant(tenantId)}
                        >{expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</button>
                        <button type="button" className="tenantStoreAction tenantStorePrimary" title={tenantId} aria-label={`查看租户 ${tenantName} 详情`} onClick={() => setSelected({ title: "租户详情", record: tenant })}>
                          <strong>{tenantName}</strong><span>{tenantId} · {stores.length} 家店铺</span>
                        </button>
                      </div>
                    </td>
                    <td data-label="类型">租户</td>
                    <td data-label="平台">-</td>
                    <td data-label="状态">{renderCell(tenant.status)}</td>
                    <td data-label="创建时间">{renderCell(tenant.created_at)}</td>
                  </tr>
                  {expanded && stores.length ? stores.map((store, storeIndex) => {
                    const storeId = String(store.store_id || store.id || "");
                    return <tr className="tenantStoreRow tenantStoreChildRow" id={storeIndex === 0 ? childRowsId : undefined} key={storeId}>
                      <td data-label="名称 / ID"><button type="button" className="tenantStoreAction tenantStorePrimary" title={storeId} aria-label={`查看店铺 ${storeId} 详情`} onClick={() => setSelected({ title: "店铺详情", record: store })}>{storeId}</button></td>
                      <td data-label="类型">店铺</td>
                      <td data-label="平台">{renderCell(store.platform)}</td>
                      <td data-label="状态">{renderCell(store.status)}</td>
                      <td data-label="创建时间">{renderCell(store.created_at)}</td>
                    </tr>;
                  }) : null}
                  {expanded && !stores.length ? <tr className="tenantStoreRow tenantStoreEmptyRow" id={childRowsId}><td data-label="店铺" colSpan={5}>暂无店铺</td></tr> : null}
                </React.Fragment>;
              })}
            </tbody>
          </table>
        </div>
      </section>
      <PaginationControls page={data.tenants.page} onPageChange={onTenantPageChange || (() => undefined)} />
      {selected ? <Drawer title={selected.title} record={selected.record} onClose={() => setSelected(null)} /> : null}
    </>;
  }}</RequestStateView>;
}
