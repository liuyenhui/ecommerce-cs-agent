# System Admin Tenant Store Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the separate tenant and store tables with one accessible tenant-first hierarchy whose store children stay with their tenant and whose only pagination control pages tenants.

**Architecture:** Keep the existing `/organizations` and `/stores` contracts. Add one focused loader that retrieves the complete store collection, retain the existing `TenantData` envelope, and render it through a purpose-built hierarchy component in `TenantsPage`; tenant paging remains server-side while store rows are grouped client-side by `organization_id`.

**Tech Stack:** React 18, TypeScript, Vitest, Testing Library, Vite, existing System Admin CSS tokens and shared request-state components.

---

## File map

- Modify `admin-web/system-admin/src/SystemWorkspace.tsx`: load all store pages once, preserve partial-failure behavior, and remove independent store-page state/actions.
- Modify `admin-web/system-admin/src/pages/TenantsPage.tsx`: render the unified accessible hierarchy, expansion state, totals, empty child state, and existing detail drawer.
- Modify `admin-web/system-admin/src/styles.css`: add scoped hierarchy table, indentation, long-ID, responsive, and focus styles.
- Modify `admin-web/system-admin/src/system-admin.test.tsx`: cover grouping, expansion, drawers, empty tenants, long IDs, totals, and multi-page store loading.
- Modify `docs/system-admin-design.md`: record the approved tenant-first list behavior in the System Admin source design.
- Modify `docs/development-handoff.md`: replace the planning-only note with implementation/verification orientation after completion.

### Task 1: Load the complete store collection

**Files:**
- Modify: `admin-web/system-admin/src/SystemWorkspace.tsx`
- Test: `admin-web/system-admin/src/system-admin.test.tsx`

- [ ] **Step 1: Write a failing multi-page loader test**

Export a `loadAllStores` helper and add a Vitest case using a real async fake API:

```tsx
it("loads every store page before building the tenant hierarchy", async () => {
  const calls: number[] = [];
  const api = {
    stores: async ({ page }: Record<string, number>) => {
      calls.push(page);
      return page === 1
        ? { items: [{ store_id: "store-1", organization_id: "org-1" }], page: { page: 1, page_size: 1, total: 2 } }
        : { items: [{ store_id: "store-2", organization_id: "org-2" }], page: { page: 2, page_size: 1, total: 2 } };
    }
  };

  const result = await loadAllStores(api as Pick<typeof systemApi, "stores">);

  expect(calls).toEqual([1, 2]);
  expect(result.items.map((item) => item.store_id)).toEqual(["store-1", "store-2"]);
  expect(result.page.total).toBe(2);
});
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd admin-web && npx vitest run --root . system-admin/src/system-admin.test.tsx -t "loads every store page"
```

Expected: FAIL because `loadAllStores` is not exported.

- [ ] **Step 3: Implement the minimal paginated loader**

Add a bounded page loop that preserves the server total and accepts an abort signal:

```tsx
export async function loadAllStores(
  api: Pick<typeof systemApi, "stores">,
  signal?: AbortSignal
): Promise<PageEnvelope> {
  const pageSize = 100;
  const first = await api.stores({ page: 1, page_size: pageSize }, signal);
  const items = [...first.items];
  const pageCount = Math.ceil(first.page.total / pageSize);
  for (let page = 2; page <= pageCount; page += 1) {
    const next = await api.stores({ page, page_size: pageSize }, signal);
    items.push(...next.items);
  }
  return { items, page: { page: 1, page_size: pageSize, total: first.page.total } };
}
```

Use it from `loadTenants`, keep `Promise.allSettled`, and retain the current `partial` state when only one data source fails. Reduce `tenantPages` to one tenant page and delete `loadStorePage`.

- [ ] **Step 4: Verify GREEN and existing partial-state tests**

Run:

```bash
cd admin-web && npx vitest run --root . system-admin/src/system-admin.test.tsx -t "store page|partial"
```

Expected: all selected tests PASS.

- [ ] **Step 5: Commit the loader change**

```bash
git add admin-web/system-admin/src/SystemWorkspace.tsx admin-web/system-admin/src/system-admin.test.tsx
git commit -m "feat: load stores for tenant hierarchy"
```

### Task 2: Render one tenant-first hierarchy

**Files:**
- Modify: `admin-web/system-admin/src/pages/TenantsPage.tsx`
- Modify: `admin-web/system-admin/src/SystemWorkspace.tsx`
- Test: `admin-web/system-admin/src/system-admin.test.tsx`

- [ ] **Step 1: Replace the old totals test with failing hierarchy assertions**

Use Testing Library so expansion and detail behavior are observable:

```tsx
it("renders stores beneath their tenant in one hierarchy", () => {
  render(<TenantsPage state={{ kind: "success", data: {
    tenants: { items: [
      { organization_id: "org-1", name: "甲组织", status: "active" },
      { organization_id: "org-2", name: "乙组织", status: "active" }
    ], page: { page: 1, page_size: 20, total: 2 } },
    stores: { items: [
      { store_id: "store-1", organization_id: "org-1", platform: "pdd", status: "active" }
    ], page: { page: 1, page_size: 100, total: 1 } }
  } }} />);

  expect(screen.getByText("共 2 个租户、1 家店铺")).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "租户与店铺" })).toBeInTheDocument();
  expect(screen.getByText("store-1").closest("tr")?.previousElementSibling).toHaveTextContent("甲组织");
  expect(screen.getByText("乙组织").closest("tr")?.nextElementSibling).toHaveTextContent("暂无店铺");
  expect(screen.queryByRole("table", { name: "店铺" })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Add failing interaction tests**

Add separate tests proving:

```tsx
fireEvent.click(screen.getByRole("button", { name: "收起甲组织的店铺" }));
expect(screen.queryByText("store-1")).not.toBeInTheDocument();
expect(screen.getByRole("button", { name: "展开甲组织的店铺" })).toHaveAttribute("aria-expanded", "false");

fireEvent.click(screen.getByText("store-1"));
expect(screen.getByRole("heading", { name: "店铺详情" })).toBeInTheDocument();
```

Also assert clicking the expand button does not open the drawer, and clicking a tenant data cell opens “租户详情”.

- [ ] **Step 3: Run the hierarchy tests and verify RED**

Run:

```bash
cd admin-web && npx vitest run --root . system-admin/src/system-admin.test.tsx -t "hierarchy|beneath their tenant|收起"
```

Expected: FAIL because the page still renders two `DataTable` components.

- [ ] **Step 4: Implement the hierarchy component**

In `TenantsPage.tsx`, remove `DataTable` and `onStorePageChange`. Group stores by `organization_id`, initialize all visible tenant IDs as expanded, and render semantic rows:

```tsx
const storesByTenant = new Map<string, JsonRecord[]>();
data.stores.items.forEach((store) => {
  const tenantId = String(store.organization_id || "");
  storesByTenant.set(tenantId, [...(storesByTenant.get(tenantId) || []), store]);
});

<p className="pageTotal">共 {data.tenants.page.total} 个租户、{data.stores.page.total} 家店铺</p>
<section className="tablePanel tenantStorePanel">
  <h3>租户与店铺</h3>
  <div className="tenantStoreTableWrap">
    <table className="tenantStoreTable" aria-label="租户与店铺">
      <thead><tr><th>名称 / ID</th><th>类型</th><th>平台</th><th>状态</th><th>创建时间</th></tr></thead>
      <tbody>{/* tenant row followed by its expanded store rows or empty-store row */}</tbody>
    </table>
  </div>
</section>
```

Use a real `<button>` for expansion, `aria-expanded`, `aria-controls`, `stopPropagation()` on the control, and keyboard-usable buttons for the tenant/store detail targets. Keep the existing `Drawer` record unchanged.

- [ ] **Step 5: Remove independent store pagination wiring**

Change the workspace render call to:

```tsx
<TenantsPage state={tenants} onTenantPageChange={loadTenantPage} />
```

Only render `<PaginationControls page={data.tenants.page} ... />` in `TenantsPage`.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
cd admin-web && npx vitest run --root . system-admin/src/system-admin.test.tsx
```

Expected: System Admin component suite PASS.

- [ ] **Step 7: Commit the hierarchy behavior**

```bash
git add admin-web/system-admin/src/pages/TenantsPage.tsx admin-web/system-admin/src/SystemWorkspace.tsx admin-web/system-admin/src/system-admin.test.tsx
git commit -m "feat: unify tenant and store list"
```

### Task 3: Add dense responsive hierarchy styling

**Files:**
- Modify: `admin-web/system-admin/src/styles.css`
- Test: `admin-web/system-admin/src/system-admin.test.tsx`

- [ ] **Step 1: Add failing structural regression assertions**

Assert the rendered hierarchy contains the scoped hooks required for responsive behavior and long IDs:

```tsx
expect(container.querySelector(".tenantStoreTableWrap")).not.toBeNull();
expect(screen.getByText("tenant-with-an-extremely-long-identifier")).toHaveClass("tenantStorePrimary");
expect(screen.getByText("store-with-an-extremely-long-identifier")).toHaveClass("tenantStorePrimary");
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd admin-web && npx vitest run --root . system-admin/src/system-admin.test.tsx -t "long identifier"
```

Expected: FAIL because hierarchy-specific classes do not exist.

- [ ] **Step 3: Add scoped desktop and mobile CSS**

Implement styles equivalent to:

```css
.tenantStoreTableWrap { min-width: 0; overflow: hidden; }
.tenantStoreTable { width: 100%; table-layout: fixed; border-collapse: collapse; }
.tenantStoreTable th, .tenantStoreTable td { border-bottom: 1px solid #e0e0e0; padding: 10px 12px; text-align: left; vertical-align: top; }
.tenantStoreRow { background: #ffffff; }
.tenantStoreChildRow { background: #f7f9fb; }
.tenantStorePrimary { min-width: 0; overflow-wrap: anywhere; word-break: break-word; }
.tenantStoreChildRow .tenantStorePrimary { padding-left: 28px; }
.tenantStoreAction { appearance: none; border: 0; background: transparent; color: inherit; text-align: left; cursor: pointer; }

@media (max-width: 640px) {
  .tenantStoreTable th:nth-child(3), .tenantStoreTable td:nth-child(3),
  .tenantStoreTable th:nth-child(5), .tenantStoreTable td:nth-child(5) { display: none; }
  .tenantStoreTable th, .tenantStoreTable td { padding: 9px 8px; }
}
```

Keep these colors aligned with the existing System Admin palette. Ensure focus-visible outlines remain visible and no wrapper uses horizontal scrolling.

- [ ] **Step 4: Verify GREEN and build**

Run:

```bash
cd admin-web && npx vitest run --root . system-admin/src/system-admin.test.tsx && npm run build:system
```

Expected: tests PASS and Vite build exits 0.

- [ ] **Step 5: Commit responsive styling**

```bash
git add admin-web/system-admin/src/styles.css admin-web/system-admin/src/system-admin.test.tsx
git commit -m "style: polish tenant store hierarchy"
```

### Task 4: Align source design and complete verification

**Files:**
- Modify: `docs/system-admin-design.md`
- Modify: `docs/development-handoff.md`

- [ ] **Step 1: Update System Admin design truth**

In the “租户与店铺” section, state that the page uses one tenant-first expandable table, store rows remain under their tenant, only tenant pagination is visible, and row selection opens the corresponding detail drawer. Do not duplicate implementation code in the design document.

- [ ] **Step 2: Update the handoff entry**

Revise the 2026-07-17 entry to list the implemented files and verification commands, preserving the link to the approved specification.

- [ ] **Step 3: Run the full Admin Web verification suite**

Run:

```bash
cd admin-web && npm test && npm run build:system
```

Expected: TypeScript, Vitest, boundary checks, UI regression scripts, and System Admin build all exit 0.

- [ ] **Step 4: Run repository hygiene and secret checks**

Run:

```bash
git diff --check
git diff --cached
rg -n "sk-|ghp_|gho_|BEGIN .*PRIVATE KEY|SMTP_PASSWORD|DATABASE_URL=.*:|LLM_API_KEY=|SECRET_ACCESS_KEY|JWT_SECRET|SESSION_SECRET" admin-web/system-admin docs/system-admin-design.md docs/development-handoff.md
```

Expected: no whitespace errors, only scoped changes, and no credential value introduced. Matches that only name approved secret keys are reviewed manually and are not treated as leaked values.

- [ ] **Step 5: Verify the live-shaped page at both required viewports**

Serve the built Admin Web locally or use the deployed host after rollout. At `1440x900` and `390x844`, verify:

- one unified hierarchy table is visible;
- each store is underneath its owning tenant;
- expand/collapse and both detail drawers work;
- long IDs do not create horizontal overflow;
- the System Admin host requests only `/v1/system-admin/auth/me` for its route guard.

- [ ] **Step 6: Commit documentation alignment**

```bash
git add docs/system-admin-design.md docs/development-handoff.md
git commit -m "docs: align tenant store hierarchy"
```
