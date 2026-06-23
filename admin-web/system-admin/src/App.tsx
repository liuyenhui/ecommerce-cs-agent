import React from "react";
import {
  Activity,
  CheckCircle2,
  HeartPulse,
  ListFilter,
  Loader2,
  PlayCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  Store,
  Users
} from "lucide-react";
import { requestJson } from "../../shared/api";
import {
  AdminFrame,
  AuditTable,
  ContextPanel,
  DataTable,
  Drawer,
  Field,
  ListPanel,
  LoginPanelBase,
  Metric,
  Navigation,
  SectionHeader,
  SystemUserSummary,
  TopBar,
  useCloseOnEscape
} from "../../shared/components";
import { arrayFrom, buildQuery, readRecord, toneFor } from "../../shared/data";
import type { JsonRecord, NavItem, Page, ToastState } from "../../shared/types";

type SystemTab = "home" | "tenants" | "traces" | "tasks" | "audit" | "health";
type SystemFiltersState = { organization_id: string; store_id: string; status: string; trace_id: string };

const systemTabs: Array<NavItem<SystemTab>> = [
  { key: "home", label: "系统首页", group: "平台运营", icon: <Activity size={17} /> },
  { key: "tenants", label: "租户与店铺", group: "平台运营", icon: <Store size={17} /> },
  { key: "traces", label: "决策追踪", group: "排障治理", icon: <Search size={17} /> },
  { key: "tasks", label: "异步任务", group: "排障治理", icon: <PlayCircle size={17} /> },
  { key: "audit", label: "安全审计", group: "发布安全", icon: <ShieldCheck size={17} /> },
  { key: "health", label: "系统健康", group: "发布安全", icon: <HeartPulse size={17} /> }
];

async function submitSystemLogin(email: string, password: string) {
  await requestJson("/v1/system-admin/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
  return requestJson("/v1/system-admin/auth/me");
}

export function App() {
  const [systemTab, setSystemTab] = React.useState<SystemTab>("home");
  const [systemSession, setSystemSession] = React.useState<JsonRecord | null>(null);
  const [toast, setToast] = React.useState<ToastState>(null);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const isAuthenticated = Boolean(systemSession);
  const closeNav = React.useCallback(() => setMobileNavOpen(false), []);
  useCloseOnEscape(mobileNavOpen, closeNav);

  async function refreshSession() {
    const me = await requestJson("/v1/system-admin/auth/me");
    setSystemSession(me);
  }

  async function logout() {
    try {
      await requestJson("/v1/system-admin/auth/logout", { method: "POST" });
    } catch {
      // Session may already be gone; local state still needs clearing.
    }
    setSystemSession(null);
    setToast({ tone: "info", text: "已退出当前后台" });
  }

  React.useEffect(() => {
    void refreshSession().catch(() => undefined);
  }, []);

  return (
    <AdminFrame
      isAuthenticated={isAuthenticated}
      mobileNavOpen={mobileNavOpen}
      brand="Ecommerce CS System Admin"
      navigation={
        <Navigation
          items={systemTabs}
          activeTab={systemTab}
          onChange={setSystemTab}
          ariaLabel="系统后台导航"
          onNavigate={closeNav}
        />
      }
      topBar={
        <TopBar
          eyebrow="SYSTEM ADMIN"
          title="平台运维与发布治理"
          subtitle="租户开通、决策追踪、任务、健康和安全审计"
          showNavButton={isAuthenticated}
          navOpen={mobileNavOpen}
          onToggleNav={() => setMobileNavOpen((open) => !open)}
          onLogout={() => void logout()}
        />
      }
      toast={toast}
      onCloseNav={closeNav}
      onCloseToast={() => setToast(null)}
    >
      {systemSession ? (
        <SystemWorkspace
          session={systemSession}
          activeTab={systemTab}
          setActiveTab={setSystemTab}
          setToast={setToast}
        />
      ) : (
        <LoginPanelBase
          title="系统后台登录"
          onSubmit={submitSystemLogin}
          onLoggedIn={(session) => setSystemSession(session)}
          setToast={setToast}
        />
      )}
    </AdminFrame>
  );
}

function SystemWorkspace({ session, activeTab, setActiveTab, setToast }: {
  session: JsonRecord;
  activeTab: SystemTab;
  setActiveTab: (tab: SystemTab) => void;
  setToast: (toast: ToastState) => void;
}) {
  const [filters, setFilters] = React.useState<SystemFiltersState>({ organization_id: "", store_id: "", status: "", trace_id: "" });
  const [data, setData] = React.useState<Record<string, unknown>>({});
  const [selected, setSelected] = React.useState<JsonRecord | null>(null);
  const [modal, setModal] = React.useState<"organization" | "store" | null>(null);

  async function refresh() {
    try {
      const query = buildQuery(filters);
      const [health, organizations, stores, readiness, tasks, audit] = await Promise.all([
        requestJson("/v1/system-admin/health"),
        requestJson<Page>(`/v1/system-admin/organizations${query}`),
        requestJson<Page>(`/v1/system-admin/stores${query}`),
        requestJson<Page>(`/v1/system-admin/readiness/stores${query}`),
        requestJson<Page>(`/v1/system-admin/tasks${query}`),
        requestJson<Page>(`/v1/system-admin/audit-logs${query}`)
      ]);
      const traces = filters.organization_id && filters.store_id
        ? await requestJson<Page>(`/v1/system-admin/message-traces${query}`)
        : { items: [] };
      setData({
        health,
        organizations: organizations.items || [],
        stores: stores.items || [],
        readiness: readiness.items || [],
        traces: traces.items || [],
        tasks: tasks.items || [],
        audit: audit.items || []
      });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  React.useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="workGrid">
      <section className="contentPane">
        <SystemFilters filters={filters} setFilters={setFilters} refresh={refresh} />
        {activeTab === "home" ? <SystemHome data={data} setActiveTab={setActiveTab} /> : null}
        {activeTab === "tenants" ? <TenantManagement data={data} setModal={setModal} setSelected={setSelected} /> : null}
        {activeTab === "traces" ? <TraceTable rows={arrayFrom(data.traces)} filters={filters} setSelected={setSelected} /> : null}
        {activeTab === "tasks" ? <TaskCenter rows={arrayFrom(data.tasks)} setToast={setToast} refresh={refresh} setSelected={setSelected} /> : null}
        {activeTab === "audit" ? <AuditTable title="系统审计" rows={arrayFrom(data.audit)} onSelect={setSelected} /> : null}
        {activeTab === "health" ? <HealthPanel health={readRecord(data, "health")} /> : null}
      </section>
      <ContextPanel title="运行摘要">
        <Metric label="组织" value={String(arrayFrom(data.organizations).length)} tone="ok" />
        <Metric label="店铺" value={String(arrayFrom(data.stores).length)} tone="info" />
        <Metric label="Trace" value={String(arrayFrom(data.traces).length)} tone="warn" />
        <Metric label="任务" value={String(arrayFrom(data.tasks).length)} tone="bad" />
        <SystemUserSummary user={readRecord(session, "user")} />
      </ContextPanel>
      {selected ? <Drawer title="详情" record={selected} onClose={() => setSelected(null)} /> : null}
      {modal ? <SystemCreateModal type={modal} onClose={() => setModal(null)} setToast={setToast} refresh={refresh} /> : null}
    </div>
  );
}

function SystemHome({ data, setActiveTab }: { data: Record<string, unknown>; setActiveTab: (tab: SystemTab) => void }) {
  return (
    <>
      <SectionHeader label="SYSTEM" title="系统首页" action={<button onClick={() => setActiveTab("traces")}><Search size={16} />定位决策</button>} />
      <div className="metricGrid">
        <Metric label="活跃组织" value={String(arrayFrom(data.organizations).length)} tone="ok" />
        <Metric label="活跃店铺" value={String(arrayFrom(data.stores).length)} tone="info" />
        <Metric label="上线检查" value={String(arrayFrom(data.readiness).length)} tone="warn" />
        <Metric label="待处理任务" value={String(arrayFrom(data.tasks).length)} tone="bad" />
      </div>
      <div className="twoColumns">
        <ListPanel title="上线阻断队列" rows={arrayFrom(data.readiness)} fields={["organization_id", "store_id", "status", "reason"]} emptyState={{ title: "未发现上线阻断", description: "当前筛选范围内没有阻断项；如需排查特定租户，请填写组织 ID 或店铺 ID 后查询。" }} />
        <ListPanel title="最近消息决策" rows={arrayFrom(data.traces)} fields={["decision_id", "status", "risk_level", "created_at"]} emptyState={{ title: "暂无消息决策", description: "当前筛选范围内还没有决策记录；有新消息进入决策流程后会显示在这里。" }} />
      </div>
    </>
  );
}

function TenantManagement({ data, setModal, setSelected }: { data: Record<string, unknown>; setModal: (modal: "organization" | "store") => void; setSelected: (record: JsonRecord) => void }) {
  return (
    <>
      <SectionHeader
        label="TENANTS"
        title="租户与店铺"
        action={<div className="buttonRow"><button onClick={() => setModal("organization")}><Users size={16} />创建组织</button><button onClick={() => setModal("store")}><Store size={16} />创建店铺</button></div>}
      />
      <div className="twoColumns">
        <DataTable title="组织" rows={arrayFrom(data.organizations)} fields={["id", "name", "status", "created_at"]} onSelect={setSelected} />
        <DataTable title="店铺" rows={arrayFrom(data.stores)} fields={["id", "organization_id", "platform", "status"]} onSelect={setSelected} />
      </div>
    </>
  );
}

function TraceTable({ rows, filters, setSelected }: { rows: JsonRecord[]; filters: Record<string, string>; setSelected: (record: JsonRecord) => void }) {
  const filtered = filters.trace_id ? rows.filter((row) => String(row.decision_id || "").includes(filters.trace_id)) : rows;
  return (
    <>
      <SectionHeader label="TRACE" title="决策追踪" />
      <DataTable title="消息决策" rows={filtered} fields={["decision_id", "organization_id", "store_id", "status", "risk_level", "created_at"]} onSelect={setSelected} emptyState={{ title: filters.trace_id ? "未找到匹配决策" : "暂无消息决策", description: filters.trace_id ? "当前 Decision ID 没有匹配记录；请检查 ID 是否完整，或清空筛选后重新查询。" : "填写组织 ID、店铺 ID 或 Decision ID 后查询决策追踪记录。" }} />
    </>
  );
}

function TaskCenter({ rows, setToast, refresh, setSelected }: {
  rows: JsonRecord[];
  setToast: (toast: ToastState) => void;
  refresh: () => Promise<void>;
  setSelected: (record: JsonRecord) => void;
}) {
  async function retry(task: JsonRecord) {
    const reason = window.prompt("请输入重试原因");
    if (!reason) return;
    try {
      await requestJson(`/v1/system-admin/tasks/${task.task_id}/retry`, {
        method: "POST",
        body: JSON.stringify({ idempotency_key: `admin-web-${Date.now()}`, reason })
      });
      setToast({ tone: "success", text: "重试已提交" });
      await refresh();
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  return (
    <>
      <SectionHeader label="TASKS" title="异步任务" />
      <DataTable title="任务" rows={rows} fields={["task_id", "task_type", "status", "retryable", "updated_at"]} onSelect={setSelected} action={(row) => <button onClick={() => retry(row)}><RefreshCw size={15} />重试</button>} />
    </>
  );
}

function HealthPanel({ health }: { health: JsonRecord }) {
  const checks = arrayFrom(health.checks);
  return (
    <>
      <SectionHeader label="HEALTH" title="系统健康" />
      <div className="metricGrid">
        <Metric label="整体状态" value={String(health.status || "-")} tone={toneFor(String(health.status || "")) || "info"} />
        <Metric label="检查项" value={String(checks.length)} tone="info" />
        <Metric label="数据库" value={String(health.database || "unknown")} tone={toneFor(String(health.database || "")) || "info"} />
        <Metric label="pgvector" value={String(health.pgvector || "unknown")} tone={toneFor(String(health.pgvector || "")) || "info"} />
      </div>
      <ListPanel title="组件检查" rows={checks} fields={["name", "status", "message"]} />
    </>
  );
}

function SystemCreateModal({ type, onClose, setToast, refresh }: {
  type: "organization" | "store";
  onClose: () => void;
  setToast: (toast: ToastState) => void;
  refresh: () => Promise<void>;
}) {
  const [form, setForm] = React.useState({
    name: "",
    status: "active",
    external_ref: "",
    organization_id: "",
    platform: "pdd",
    external_store_id: "",
    reason: ""
  });
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    try {
      const path = type === "organization" ? "/v1/system-admin/organizations" : "/v1/system-admin/stores";
      const body = type === "organization"
        ? { name: form.name, status: form.status, external_ref: form.external_ref, reason: form.reason }
        : { organization_id: form.organization_id, name: form.name, platform: form.platform, external_store_id: form.external_store_id, status: form.status, reason: form.reason };
      await requestJson(path, { method: "POST", body: JSON.stringify(body) });
      setToast({ tone: "success", text: type === "organization" ? "组织已创建" : "店铺已创建" });
      onClose();
      await refresh();
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  return (
    <div className="modalBackdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <h2>{type === "organization" ? "创建组织" : "创建店铺"}</h2>
        <Field label="名称" value={form.name} onChange={(value) => setForm({ ...form, name: value })} />
        {type === "organization" ? (
          <Field label="外部组织引用" value={form.external_ref} onChange={(value) => setForm({ ...form, external_ref: value })} />
        ) : (
          <>
            <Field label="组织 ID" value={form.organization_id} onChange={(value) => setForm({ ...form, organization_id: value })} />
            <Field label="平台" value={form.platform} onChange={(value) => setForm({ ...form, platform: value })} />
            <Field label="外部店铺 ID" value={form.external_store_id} onChange={(value) => setForm({ ...form, external_store_id: value })} />
          </>
        )}
        <Field label="原因" value={form.reason} onChange={(value) => setForm({ ...form, reason: value })} />
        <div className="buttonRow end">
          <button type="button" onClick={onClose}>取消</button>
          <button className="primaryButton"><CheckCircle2 size={16} />提交</button>
        </div>
      </form>
    </div>
  );
}

function SystemFilters({ filters, setFilters, refresh }: {
  filters: SystemFiltersState;
  setFilters: React.Dispatch<React.SetStateAction<SystemFiltersState>>;
  refresh: () => Promise<void>;
}) {
  return (
    <section className="filterBar">
      <ListFilter size={17} />
      <input placeholder="组织 ID" value={filters.organization_id} onChange={(event) => setFilters({ ...filters, organization_id: event.target.value })} />
      <input placeholder="店铺 ID" value={filters.store_id} onChange={(event) => setFilters({ ...filters, store_id: event.target.value })} />
      <input placeholder="状态" value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })} />
      <input placeholder="Decision ID" value={filters.trace_id} onChange={(event) => setFilters({ ...filters, trace_id: event.target.value })} />
      <button onClick={() => refresh()}><Search size={16} />查询</button>
    </section>
  );
}
