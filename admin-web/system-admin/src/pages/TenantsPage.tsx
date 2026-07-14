import React from "react";
import { DataTable, Drawer, RequestStateView, SectionHeader } from "../../../shared/components";
import type { JsonRecord } from "../../../shared/types";
import type { RequestState, TenantData } from "../system-types";
import { PaginationControls } from "./PaginationControls";

export function TenantsPage({ state, onTenantPageChange, onStorePageChange }: { state: RequestState<TenantData>; onTenantPageChange?: (page: number) => void; onStorePageChange?: (page: number) => void }) {
  const [selected, setSelected] = React.useState<{ title: string; record: JsonRecord } | null>(null);
  return <RequestStateView state={state}>{(data) => <>
    <SectionHeader label="TENANT OPERATIONS" title="租户与店铺" />
    <div className="twoColumns">
      <div>
        <p className="pageTotal">共 {data.tenants.page.total} 个租户</p>
        <DataTable title="租户" rows={data.tenants.items} fields={["organization_id", "name", "status", "created_at"]} onSelect={(record) => setSelected({ title: "租户详情", record })} emptyState={{ title: "暂无租户", description: "服务端未返回符合筛选条件的租户。" }} />
        <PaginationControls page={data.tenants.page} onPageChange={onTenantPageChange || (() => undefined)} />
      </div>
      <div>
        <p className="pageTotal">共 {data.stores.page.total} 家店铺</p>
        <DataTable title="店铺" rows={data.stores.items} fields={["store_id", "organization_id", "platform", "status"]} onSelect={(record) => setSelected({ title: "店铺详情", record })} emptyState={{ title: "暂无店铺", description: "服务端未返回符合筛选条件的店铺。" }} />
        <PaginationControls page={data.stores.page} onPageChange={onStorePageChange || (() => undefined)} />
      </div>
    </div>
    {selected ? <Drawer title={selected.title} record={selected.record} onClose={() => setSelected(null)} /> : null}
  </>}</RequestStateView>;
}
