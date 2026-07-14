import React from "react";
import { Activity, Bot, Building2, ClipboardCheck, HeartPulse, ListChecks, Rocket, Search, ShieldCheck } from "lucide-react";
import { EmptyState, Navigation, SystemUserSummary } from "../../shared/components";
import type { JsonRecord, NavItem, ToastState } from "../../shared/types";
import { requestFailure, systemApi } from "./system-api";
import type { AuditFilters, DashboardData, PageEnvelope, ReadinessRecord, RequestState, SystemHealth, SystemPage, TaskRecord, TenantData, TraceFilters } from "./system-types";
import { AuditPage } from "./pages/AuditPage";
import { DashboardPage } from "./pages/DashboardPage";
import { HealthPage } from "./pages/HealthPage";
import { ReadinessPage } from "./pages/ReadinessPage";
import { TasksPage } from "./pages/TasksPage";
import { TenantsPage } from "./pages/TenantsPage";
import { TracesPage } from "./pages/TracesPage";

export const RAIL_COLLAPSED_STORAGE_KEY = "system-admin:rail-collapsed";

export function readRailCollapsed(storage: Pick<Storage, "getItem">) {
  return storage.getItem(RAIL_COLLAPSED_STORAGE_KEY) === "true";
}

export function persistRailCollapsed(storage: Pick<Storage, "setItem">, collapsed: boolean) {
  storage.setItem(RAIL_COLLAPSED_STORAGE_KEY, String(collapsed));
}

export const systemNavigationItems: Array<NavItem<SystemPage>> = [
  { key: "dashboard", label: "系统总览", group: "平台运营", icon: <Activity size={18} /> },
  { key: "tenants", label: "租户与店铺", group: "平台运营", icon: <Building2 size={18} /> },
  { key: "readiness", label: "配置完成度", group: "平台运营", icon: <ClipboardCheck size={18} /> },
  { key: "llm", label: "LLM 治理", group: "模型与发布", icon: <Bot size={18} /> },
  { key: "releases", label: "评测与发布", group: "模型与发布", icon: <Rocket size={18} /> },
  { key: "traces", label: "决策追踪", group: "排障治理", icon: <Search size={18} /> },
  { key: "tasks", label: "任务中心", group: "排障治理", icon: <ListChecks size={18} /> },
  { key: "audit", label: "安全审计", group: "安全与运行", icon: <ShieldCheck size={18} /> },
  { key: "health", label: "系统健康", group: "安全与运行", icon: <HeartPulse size={18} /> }
];

export function SystemNavigation({ activePage, collapsed, onChange, onNavigate }: { activePage: SystemPage; collapsed: boolean; onChange: (page: SystemPage) => void; onNavigate?: () => void }) {
  return <div className={collapsed ? "systemNavigation collapsed" : "systemNavigation"}><Navigation items={systemNavigationItems} activeTab={activePage} onChange={onChange} onNavigate={onNavigate} ariaLabel="系统后台任务导航" showTooltips={collapsed} /></div>;
}

const loading = <T,>(): RequestState<T> => ({ kind: "loading" });
const emptyPage = (): PageEnvelope => ({ items: [], page: { page: 1, page_size: 20, total: 0 } });
const empty = <T,>(title: string, description: string): RequestState<T> => ({ kind: "empty", title, description });
const failed = <T,>(error: unknown): RequestState<T> => requestFailure(error);

export async function loadDashboardSupportingData(api: Pick<typeof systemApi, "readiness" | "tasks" | "traces">, now = new Date()) {
  const today = new Date(now);
  today.setUTCHours(0, 0, 0, 0);
  const results = await Promise.allSettled([
    api.readiness({ status: "blocked", page_size: 5 }),
    api.tasks({ page_size: 5 }),
    api.traces({ time_from: today.toISOString(), page_size: "5" })
  ]);
  const labels = ["配置完成度", "任务", "决策"];
  return {
    failures: results.flatMap((result, index) => result.status === "rejected" ? [`${labels[index]}数据暂不可用`] : []),
    pages: results.map((result) => result.status === "fulfilled" ? result.value : emptyPage())
  };
}

export function SystemWorkspace({ activePage, session, setToast }: { activePage: SystemPage; session?: JsonRecord; setToast: (toast: ToastState) => void }) {
  const [dashboard, setDashboard] = React.useState<RequestState<DashboardData>>(loading);
  const [tenants, setTenants] = React.useState<RequestState<TenantData>>(loading);
  const [readiness, setReadiness] = React.useState<RequestState<PageEnvelope<ReadinessRecord>>>(loading);
  const [traces, setTraces] = React.useState<RequestState<PageEnvelope>>(empty("请设置查询范围", "请提供租户、店铺、Decision ID 或时间范围后查询。"));
  const [traceDetail, setTraceDetail] = React.useState<JsonRecord | null>(null);
  const [tasks, setTasks] = React.useState<RequestState<PageEnvelope<TaskRecord>>>(loading);
  const [audit, setAudit] = React.useState<RequestState<PageEnvelope>>(loading);
  const [health, setHealth] = React.useState<RequestState<SystemHealth>>(loading);

  async function loadDashboard() {
    setDashboard(loading());
    try {
      const summary = await systemApi.dashboardSummary();
      const { failures, pages } = await loadDashboardSupportingData(systemApi);
      const data: DashboardData = { summary, readiness: pages[0], tasks: pages[1], decisions: pages[2] };
      setDashboard(failures.length ? { kind: "partial", data, failures } : { kind: "success", data });
    } catch (error) { setDashboard(failed(error)); }
  }

  async function loadTenants() {
    setTenants(loading());
    const results = await Promise.allSettled([systemApi.tenants(), systemApi.stores()]);
    const failures = results.flatMap((result, index) => result.status === "rejected" ? [`${index ? "店铺" : "租户"}数据暂不可用`] : []);
    if (results.every((result) => result.status === "rejected")) {
      setTenants(failed((results[0] as PromiseRejectedResult).reason));
      return;
    }
    const data = { tenants: results[0].status === "fulfilled" ? results[0].value : emptyPage(), stores: results[1].status === "fulfilled" ? results[1].value : emptyPage() };
    setTenants(failures.length ? { kind: "partial", data, failures } : { kind: "success", data });
  }

  async function loadReadiness() {
    setReadiness(loading());
    try {
      const data = await systemApi.readiness() as PageEnvelope<ReadinessRecord>;
      setReadiness(data.page.total ? { kind: "success", data } : empty("暂无配置完成度记录", "服务端未返回店铺上线检查。"));
    } catch (error) { setReadiness(failed(error)); }
  }

  async function loadTasks() {
    setTasks(loading());
    try {
      const data = await systemApi.tasks() as PageEnvelope<TaskRecord>;
      setTasks(data.page.total ? { kind: "success", data } : empty("暂无后台任务", "服务端未返回任务记录。"));
    } catch (error) { setTasks(failed(error)); }
  }

  async function loadAudit(filters: AuditFilters | Record<string, string> = {}) {
    setAudit(loading());
    try {
      const data = await systemApi.audit(filters);
      setAudit(data.page.total ? { kind: "success", data } : empty("暂无审计记录", "服务端未返回符合条件的审计记录。"));
    } catch (error) { setAudit(failed(error)); }
  }

  async function loadHealth() {
    setHealth(loading());
    try { setHealth({ kind: "success", data: await systemApi.health() }); } catch (error) { setHealth(failed(error)); }
  }

  React.useEffect(() => {
    if (activePage === "dashboard") void loadDashboard();
    if (activePage === "tenants") void loadTenants();
    if (activePage === "readiness") void loadReadiness();
    if (activePage === "tasks") void loadTasks();
    if (activePage === "audit") void loadAudit();
    if (activePage === "health") void loadHealth();
  }, [activePage]);

  async function searchTraces(filters: TraceFilters) {
    setTraces(loading());
    try {
      const data = await systemApi.traces(filters);
      setTraces(data.page.total ? { kind: "success", data } : empty("暂无决策记录", "服务端未返回符合查询范围的决策记录。"));
    } catch (error) { setTraces(failed(error)); }
  }

  async function openTrace(decisionId: string) {
    if (!decisionId) return;
    try { setTraceDetail(await systemApi.trace(decisionId)); } catch (error) { setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) }); }
  }

  async function retryTask(task: TaskRecord) {
    if (task.retryable !== true) return;
    const reason = window.prompt("请输入任务重试原因");
    if (!reason?.trim()) return;
    try {
      await systemApi.retryTask(task.task_id, reason.trim());
      setToast({ tone: "success", text: "任务重试已提交" });
      await loadTasks();
    } catch (error) { setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) }); }
  }

  return <div className="systemWorkspace">
    <section className="contentPane">
      {activePage === "dashboard" ? <DashboardPage state={dashboard} /> : null}
      {activePage === "tenants" ? <TenantsPage state={tenants} /> : null}
      {activePage === "readiness" ? <ReadinessPage state={readiness} /> : null}
      {activePage === "llm" ? <Placeholder title="LLM 治理" description="Provider、路由、成本与配置版本的详细工作区由 Task 7 接入；本入口不展示示例数据。" /> : null}
      {activePage === "releases" ? <Placeholder title="评测与发布" description="评测门禁、发布和回滚的详细工作区由 Task 7 接入；本入口不展示示例数据。" /> : null}
      {activePage === "traces" ? <TracesPage state={traces} detail={traceDetail} onSearch={(filters) => void searchTraces(filters)} onOpen={(id) => void openTrace(id)} onClose={() => setTraceDetail(null)} /> : null}
      {activePage === "tasks" ? <TasksPage state={tasks} onRetry={(task) => void retryTask(task)} /> : null}
      {activePage === "audit" ? <AuditPage state={audit} onSearch={(filters) => void loadAudit(filters)} /> : null}
      {activePage === "health" ? <HealthPage state={health} /> : null}
    </section>
    {session ? <aside className="systemAccount"><SystemUserSummary user={(session.user as JsonRecord | undefined) || {}} /></aside> : null}
  </div>;
}

function Placeholder({ title, description }: { title: string; description: string }) {
  return <section className="tablePanel placeholderPage"><h2>{title}</h2><EmptyState title="工作区入口已就绪" description={description} /></section>;
}
