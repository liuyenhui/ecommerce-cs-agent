import React from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  Bell,
  Boxes,
  CheckCircle2,
  ChevronRight,
  ClipboardCheck,
  ClipboardList,
  Database,
  FileSearch,
  FileText,
  Gauge,
  HeartPulse,
  KeyRound,
  Layers3,
  ListFilter,
  Loader2,
  LockKeyhole,
  LogOut,
  PackagePlus,
  PlayCircle,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Store,
  UploadCloud,
  Users,
  Workflow
} from "lucide-react";
import "./styles.css";

type JsonRecord = Record<string, unknown>;
type Surface = "public" | "customer-login" | "customer-admin" | "system-login" | "system-admin";
type ToastState = { tone: "success" | "error" | "info"; text: string } | null;
type Tone = "ok" | "warn" | "bad" | "info" | "neutral";
type CustomerPage = "overview" | "products" | "uploads" | "prices" | "knowledge" | "rules" | "actions" | "audit";
type SystemPage =
  | "home"
  | "tenants"
  | "readiness"
  | "knowledge"
  | "traces"
  | "tasks"
  | "rules"
  | "release"
  | "audit"
  | "health";

type NavItem<T extends string> = {
  key: T;
  label: string;
  group: string;
  icon: React.ReactNode;
};

type TableColumn = {
  key: string;
  label: string;
  mono?: boolean;
};

type Page<T = JsonRecord> = {
  items?: T[];
  organizations?: T[];
  stores?: T[];
};

const viteEnv = (import.meta as ImportMeta & { env?: { DEV?: boolean } }).env;
const isDevDemo = Boolean(viteEnv?.DEV) && new URL(window.location.href).searchParams.get("demo") === "1";

const apiPaths = {
  customerLogin: "/v1/admin/auth/login",
  customerMe: "/v1/admin/auth/me",
  customerLogout: "/v1/admin/auth/logout",
  systemLogin: "/v1/system-admin/auth/login",
  systemMe: "/v1/system-admin/auth/me",
  systemLogout: "/v1/system-admin/auth/logout",
  systemMessageTraces: "/v1/system-admin/message-traces"
} as const;

const customerNav: Array<NavItem<CustomerPage>> = [
  { key: "overview", label: "首页概览", group: "客户运营", icon: <Activity size={18} /> },
  { key: "products", label: "商品资料", group: "资料中心", icon: <Boxes size={18} /> },
  { key: "uploads", label: "资料上传", group: "资料中心", icon: <UploadCloud size={18} /> },
  { key: "prices", label: "价格快照", group: "资料中心", icon: <Database size={18} /> },
  { key: "knowledge", label: "知识审核", group: "审核与规则", icon: <FileText size={18} /> },
  { key: "rules", label: "规则配置", group: "审核与规则", icon: <Settings2 size={18} /> },
  { key: "actions", label: "动作能力", group: "审核与规则", icon: <Workflow size={18} /> },
  { key: "audit", label: "审计与追踪", group: "治理", icon: <ClipboardList size={18} /> }
];

const systemNav: Array<NavItem<SystemPage>> = [
  { key: "home", label: "系统首页", group: "平台运营", icon: <Activity size={18} /> },
  { key: "tenants", label: "租户与店铺", group: "平台运营", icon: <Store size={18} /> },
  { key: "readiness", label: "配置完成度", group: "平台运营", icon: <Gauge size={18} /> },
  { key: "knowledge", label: "资料与知识", group: "平台运营", icon: <FileSearch size={18} /> },
  { key: "traces", label: "决策追踪", group: "排障治理", icon: <Search size={18} /> },
  { key: "tasks", label: "异步任务", group: "排障治理", icon: <PlayCircle size={18} /> },
  { key: "rules", label: "规则与动作", group: "排障治理", icon: <Workflow size={18} /> },
  { key: "release", label: "评测与发布", group: "发布安全", icon: <ClipboardCheck size={18} /> },
  { key: "audit", label: "安全审计", group: "发布安全", icon: <ShieldCheck size={18} /> },
  { key: "health", label: "系统健康", group: "发布安全", icon: <HeartPulse size={18} /> }
];

const statusTone: Record<string, Tone> = {
  active: "ok",
  healthy: "ok",
  ok: "ok",
  passed: "ok",
  completed: "ok",
  approved: "ok",
  enabled: "ok",
  pending: "warn",
  waiting_context: "warn",
  needs_review: "warn",
  warning: "warn",
  degraded: "warn",
  blocked: "bad",
  failed: "bad",
  frozen: "bad",
  rejected: "bad",
  disabled: "bad",
  running: "info",
  draft: "info",
  info: "info"
};

const demoCustomerSession: JsonRecord = {
  user: { display_name: "客户运营管理员", email: "ops@example.test", roles: ["store_admin", "knowledge_reviewer"] },
  active_organization_id: "org-001",
  active_store_id: "store-pdd-01",
  organizations: [
    { organization_id: "org-001", name: "三人行电商", status: "active" },
    { organization_id: "org-002", name: "家居旗舰事业部", status: "active" }
  ],
  stores: [
    { store_id: "store-pdd-01", organization_id: "org-001", name: "拼多多旗舰店", platform: "pdd", status: "active" },
    { store_id: "store-tb-02", organization_id: "org-001", name: "淘宝企业店", platform: "taobao", status: "active" }
  ]
};

const demoSystemSession: JsonRecord = {
  user: { display_name: "平台值班", email: "system-admin@example.test", roles: ["system_admin", "release_manager"] }
};

const demoData = {
  users: [
    { user_id: "usr-001", display_name: "商品资料员", roles: "content_editor", store_ids: "store-pdd-01", status: "active" },
    { user_id: "usr-002", display_name: "知识审核员", roles: "knowledge_reviewer", store_ids: "store-pdd-01", status: "active" }
  ],
  productGaps: [
    { product_id: "prd-1024", title: "便携式热敏标签机", status: "needs_review", reason: "说明书已上传，Markdown 待审核" },
    { product_id: "prd-2048", title: "智能恒温杯垫", status: "warning", reason: "价格快照 36 小时未更新" }
  ],
  uploads: [
    { asset_id: "asset-8891", product_id: "prd-1024", asset_type: "manual", conversion_status: "completed", version: "v3" },
    { asset_id: "asset-8892", product_id: "prd-2048", asset_type: "image", conversion_status: "running", version: "v1" }
  ],
  knowledge: [
    { candidate_id: "kn-701", product_id: "prd-1024", status: "pending", source: "manual", risk: "low" },
    { candidate_id: "kn-702", product_id: "prd-2048", status: "needs_review", source: "human_reply", risk: "medium" }
  ],
  prices: [
    { product_id: "prd-1024", current_price: "129.00", currency: "CNY", status: "active", effective_at: "2026-06-20 08:00" },
    { product_id: "prd-2048", current_price: "89.00", currency: "CNY", status: "warning", effective_at: "2026-06-18 20:30" }
  ],
  rules: [
    { rule_id: "rule-101", name: "高风险售后转人工", priority: 10, status: "enabled", updated_at: "2026-06-19 21:20" },
    { rule_id: "rule-102", name: "价格缺失禁止自动回复", priority: 20, status: "enabled", updated_at: "2026-06-19 19:12" }
  ],
  actions: [
    { action_type: "order_note", risk_level: "medium", confirm_required: "true", status: "enabled" },
    { action_type: "address_change", risk_level: "high", confirm_required: "true", status: "disabled" }
  ],
  customerAudit: [
    { audit_log_id: "aud-3001", action: "review", object_type: "knowledge_candidate", reason: "确认说明书来源", created_at: "2026-06-20 08:40" },
    { audit_log_id: "aud-3002", action: "update", object_type: "rule_set", reason: "上线前规则校准", created_at: "2026-06-19 22:10" }
  ],
  organizations: [
    { organization_id: "org-001", name: "三人行电商", status: "active", readiness: "82%", blocked_items: 2 },
    { organization_id: "org-002", name: "家居旗舰事业部", status: "active", readiness: "74%", blocked_items: 4 },
    { organization_id: "org-003", name: "数码配件事业部", status: "frozen", readiness: "41%", blocked_items: 9 }
  ],
  stores: [
    { store_id: "store-pdd-01", organization_id: "org-001", platform: "pdd", status: "active", readiness: "88%" },
    { store_id: "store-tb-02", organization_id: "org-001", platform: "taobao", status: "warning", readiness: "71%" },
    { store_id: "store-jd-03", organization_id: "org-002", platform: "jd", status: "blocked", readiness: "54%" }
  ],
  readiness: [
    { store_id: "store-jd-03", check: "知识审核", status: "blocked", reason: "12 条候选知识未审核" },
    { store_id: "store-tb-02", check: "动作能力", status: "warning", reason: "地址变更动作未配置回调" },
    { store_id: "store-pdd-01", check: "价格快照", status: "warning", reason: "2 个重点 SKU 接近过期" }
  ],
  traces: [
    { decision_id: "dec-20260620-001", organization_id: "org-001", store_id: "store-pdd-01", status: "waiting_context", risk_level: "medium", created_at: "09:34" },
    { decision_id: "dec-20260620-002", organization_id: "org-002", store_id: "store-jd-03", status: "blocked", risk_level: "high", created_at: "09:28" },
    { decision_id: "dec-20260620-003", organization_id: "org-001", store_id: "store-tb-02", status: "approved", risk_level: "low", created_at: "09:11" }
  ],
  tasks: [
    { task_id: "job-881", task_type: "embedding_refresh", status: "running", retryable: "false", updated_at: "09:30" },
    { task_id: "job-882", task_type: "asset_markdown_parse", status: "failed", retryable: "true", updated_at: "09:18" }
  ],
  release: [
    { suite: "quick-live", status: "passed", failed_cases: 0, updated_at: "08:58" },
    { suite: "redline", status: "blocked", failed_cases: 2, updated_at: "08:42" }
  ],
  systemAudit: [
    { audit_log_id: "sys-aud-9001", actor: "system-admin@example.test", action: "sensitive_read", object_type: "trace", reason: "排查高风险拒答", created_at: "09:12" },
    { audit_log_id: "sys-aud-9002", actor: "release@example.test", action: "freeze", object_type: "api_credential", reason: "疑似泄露", created_at: "08:50" }
  ],
  health: [
    { name: "API", status: "healthy", message: "p95 182ms" },
    { name: "PostgreSQL", status: "healthy", message: "连接池正常" },
    { name: "Object Storage", status: "degraded", message: "上传队列积压 6" },
    { name: "LLM Provider", status: "healthy", message: "主供应商可用" }
  ]
};

function resolveAdminSurface(location: Location): Surface {
  const host = location.hostname.toLowerCase();
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const querySurface = new URLSearchParams(location.search).get("surface");
  const systemRouteAllowed = isSystemAdminRouteAllowed(host);

  if (systemRouteAllowed && querySurface === "system-login") return "system-login";
  if (systemRouteAllowed && querySurface === "system") return "system-admin";
  if (querySurface === "customer-login") return "customer-login";
  if (querySurface === "customer") return "customer-admin";

  if (isSystemAdminHost(host)) {
    return path === "/login" ? "system-login" : "system-admin";
  }
  if (systemRouteAllowed && path === "/system-admin/login") return "system-login";
  if (systemRouteAllowed && path === "/system-admin") return "system-admin";
  if (path === "/login") return "customer-login";
  if (path === "/admin") return "customer-admin";
  return "public";
}

function isSystemAdminHost(host: string): boolean {
  return host.startsWith("system-admin.") || host.startsWith("ops-admin.");
}

function isSystemAdminRouteAllowed(host: string): boolean {
  return isSystemAdminHost(host) || host === "localhost" || host === "127.0.0.1" || host === "::1";
}

async function requestJson<T = JsonRecord>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch(path, {
    credentials: "include",
    ...options,
    headers
  });
  if (response.status === 204) return null as T;
  const contentType = response.headers.get("Content-Type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === "object" && payload && "error" in payload
      ? String(((payload as JsonRecord).error as JsonRecord | undefined)?.message || response.statusText)
      : String(payload || response.statusText);
    throw new Error(`${response.status} ${message}`);
  }
  return payload as T;
}

function App() {
  const [surface, setSurface] = React.useState<Surface>(() => resolveAdminSurface(window.location));
  const [customerSession, setCustomerSession] = React.useState<JsonRecord | null>(isDevDemo ? demoCustomerSession : null);
  const [systemSession, setSystemSession] = React.useState<JsonRecord | null>(isDevDemo ? demoSystemSession : null);
  const [toast, setToast] = React.useState<ToastState>(null);

  const navigate = React.useCallback((path: string) => {
    const next = isDevDemo && !path.includes("?") ? `${path}?demo=1` : path;
    window.history.pushState({}, "", next);
    setSurface(resolveAdminSurface(window.location));
  }, []);

  React.useEffect(() => {
    const listener = () => setSurface(resolveAdminSurface(window.location));
    window.addEventListener("popstate", listener);
    return () => window.removeEventListener("popstate", listener);
  }, []);

  React.useEffect(() => {
    if (isDevDemo) return;
    if (surface === "customer-admin") {
      void requestJson(apiPaths.customerMe).then(setCustomerSession).catch(() => setCustomerSession(null));
    }
    if (surface === "system-admin") {
      void requestJson(apiPaths.systemMe).then(setSystemSession).catch(() => setSystemSession(null));
    }
  }, [surface]);

  async function logout(target: "customer" | "system") {
    try {
      await requestJson(target === "customer" ? apiPaths.customerLogout : apiPaths.systemLogout, { method: "POST" });
    } catch {
      // Session may already be gone; clear local state either way.
    }
    if (target === "customer") {
      setCustomerSession(null);
      navigate("/login");
    } else {
      setSystemSession(null);
      navigate("/system-admin/login");
    }
    setToast({ tone: "info", text: "已退出当前后台" });
  }

  let content: React.ReactNode;
  if (surface === "public") {
    content = <PublicLanding onNavigate={navigate} />;
  } else if (surface === "customer-login") {
    content = <LoginPage target="customer" onLoggedIn={(session) => { setCustomerSession(session); navigate("/admin"); }} setToast={setToast} />;
  } else if (surface === "system-login") {
    content = <LoginPage target="system" onLoggedIn={(session) => { setSystemSession(session); navigate("/system-admin"); }} setToast={setToast} />;
  } else if (surface === "customer-admin") {
    content = customerSession ? (
      <CustomerAdminShell session={customerSession} onLogout={() => logout("customer")} setToast={setToast} />
    ) : (
      <LoginPage target="customer" onLoggedIn={(session) => { setCustomerSession(session); navigate("/admin"); }} setToast={setToast} />
    );
  } else {
    content = systemSession ? (
      <SystemAdminShell session={systemSession} onLogout={() => logout("system")} setToast={setToast} />
    ) : (
      <LoginPage target="system" onLoggedIn={(session) => { setSystemSession(session); navigate("/system-admin"); }} setToast={setToast} />
    );
  }

  return (
    <>
      {content}
      {toast ? <Toast toast={toast} onClose={() => setToast(null)} /> : null}
    </>
  );
}

function PublicLanding({ onNavigate }: { onNavigate: (path: string) => void }) {
  return (
    <main className="publicPage">
      <header className="publicNav">
        <div className="publicBrand"><ShieldCheck size={22} />Ecommerce CS Agent</div>
        <button className="ghostDarkButton" onClick={() => onNavigate("/login")}>客户登录</button>
      </header>
      <section className="heroBand">
        <div className="heroCopy">
          <p className="heroEyebrow">客服 Agent 后台</p>
          <h1>让商品资料、知识审核和自动回复规则形成可追踪闭环</h1>
          <p>公开页面只负责产品介绍和客户登录入口；租户业务数据在登录后的客户后台维护，平台治理在独立系统后台处理。</p>
          <div className="heroActions">
            <button className="blackButton" onClick={() => onNavigate("/login")}>进入客户后台</button>
            <button className="textButton" onClick={() => onNavigate("/admin")}>查看后台入口</button>
          </div>
        </div>
        <div className="productPreview" aria-label="客户后台产品预览">
          <div className="previewTop"><span />商品资料中心</div>
          <div className="previewMetrics">
            <PreviewMetric label="待审核知识" value="24" />
            <PreviewMetric label="价格预警" value="7" />
            <PreviewMetric label="规则生效" value="18" />
          </div>
          <div className="previewTable">
            {demoData.productGaps.map((row) => (
              <div key={String(row.product_id)}>
                <strong>{row.title}</strong>
                <span>{row.reason}</span>
              </div>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}

function LoginPage({
  target,
  onLoggedIn,
  setToast
}: {
  target: "customer" | "system";
  onLoggedIn: (session: JsonRecord) => void;
  setToast: (toast: ToastState) => void;
}) {
  const [email, setEmail] = React.useState(target === "customer" ? "admin@example.test" : "system-admin@example.test");
  const [password, setPassword] = React.useState("");
  const [organizationId, setOrganizationId] = React.useState("org-001");
  const [loading, setLoading] = React.useState(false);
  const isSystem = target === "system";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (isDevDemo) {
      onLoggedIn(isSystem ? demoSystemSession : demoCustomerSession);
      setToast({ tone: "success", text: "本地预览已进入后台" });
      return;
    }
    setLoading(true);
    try {
      const path = isSystem ? apiPaths.systemLogin : apiPaths.customerLogin;
      const body = isSystem ? { email, password } : { email, password, organization_id: organizationId };
      await requestJson(path, { method: "POST", body: JSON.stringify(body) });
      const session = await requestJson(isSystem ? apiPaths.systemMe : apiPaths.customerMe);
      onLoggedIn(session);
      setToast({ tone: "success", text: "登录成功" });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className={isSystem ? "loginPage systemLogin" : "loginPage customerLogin"}>
      <form className="loginPanel" onSubmit={submit}>
        <div className="loginMark">{isSystem ? <LockKeyhole size={24} /> : <KeyRound size={24} />}</div>
        <p className="eyebrow">{isSystem ? "SYSTEM ADMIN" : "CUSTOMER ADMIN"}</p>
        <h1>{isSystem ? "系统后台登录" : "客户后台登录"}</h1>
        <p className="mutedText">
          {isSystem ? "只接受系统后台专用 session，不复用客户后台登录态。" : "使用 Agent 自有客户后台账号，进入组织和店铺运营控制台。"}
        </p>
        <label>邮箱<input value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" /></label>
        <label>密码<input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" /></label>
        {!isSystem ? <label>组织 ID<input value={organizationId} onChange={(event) => setOrganizationId(event.target.value)} /></label> : null}
        <button className="primaryButton" type="submit" disabled={loading}>
          {loading ? <Loader2 size={16} className="spin" /> : <ShieldCheck size={16} />}
          登录
        </button>
      </form>
    </main>
  );
}

function CustomerAdminShell({ session, onLogout, setToast }: { session: JsonRecord; onLogout: () => void; setToast: (toast: ToastState) => void }) {
  const [page, setPage] = React.useState<CustomerPage>("overview");
  const [selected, setSelected] = React.useState<JsonRecord | null>(null);
  const [modal, setModal] = React.useState<"product" | "rule" | "action" | null>(null);
  const [organizationId, setOrganizationId] = React.useState(String(session.active_organization_id || firstId(session.organizations, "org-001")));
  const [storeId, setStoreId] = React.useState(String(session.active_store_id || firstId(session.stores, "store-pdd-01")));
  const organizations = arrayFrom(session.organizations);
  const stores = arrayFrom(session.stores).filter((store) => String(store.organization_id || organizationId) === organizationId);

  return (
    <main className="adminShell customerShell">
      <Topbar
        brand="Agent Customer Admin"
        scope={<ScopeControls organizationId={organizationId} storeId={storeId} organizations={organizations} stores={stores} setOrganizationId={setOrganizationId} setStoreId={setStoreId} />}
        user={readRecord(session, "user")}
        onLogout={onLogout}
      />
      <div className="shellGrid">
        <SideNav items={customerNav} active={page} onChange={setPage} />
        <section className="mainCanvas">
          {page === "overview" ? <CustomerOverview setPage={setPage} setModal={setModal} /> : null}
          {page === "products" ? <DataPage label="PRODUCT CONTENT" title="商品资料" description="维护商品、SKU、属性、适用范围和资料体检结果。" action={<button className="primaryButton" onClick={() => setModal("product")}><PackagePlus size={16} />新增商品</button>} rows={demoData.productGaps} columns={[col("product_id", "商品 ID", true), col("title", "商品标题"), col("status", "状态"), col("reason", "缺口原因")]} onSelect={setSelected} /> : null}
          {page === "uploads" ? <DataPage label="ASSETS" title="资料上传" description="登记说明书、照片、视频和 Markdown 审稿稿件版本。" action={<button className="secondaryButton"><UploadCloud size={16} />登记资产</button>} rows={demoData.uploads} columns={[col("asset_id", "资产 ID", true), col("product_id", "商品 ID", true), col("asset_type", "类型"), col("conversion_status", "转换状态"), col("version", "版本")]} onSelect={setSelected} /> : null}
          {page === "prices" ? <DataPage label="PRICE SNAPSHOTS" title="价格快照" description="查看当前有效价格、活动价、生效时间、来源和冲突提示。" rows={demoData.prices} columns={[col("product_id", "商品 ID", true), col("current_price", "当前价格"), col("currency", "币种"), col("status", "状态"), col("effective_at", "生效时间")]} onSelect={setSelected} /> : null}
          {page === "knowledge" ? <KnowledgeReviewPanel setToast={setToast} /> : null}
          {page === "rules" ? <DataPage label="RULES" title="规则配置" description="维护店铺规则、优先级、条件、启用状态、版本和生效时间。" action={<button className="primaryButton" onClick={() => setModal("rule")}><Plus size={16} />新增规则</button>} rows={demoData.rules} columns={[col("rule_id", "规则 ID", true), col("name", "规则名称"), col("priority", "优先级"), col("status", "状态"), col("updated_at", "更新时间")]} onSelect={setSelected} /> : null}
          {page === "actions" ? <DataPage label="ACTION CAPABILITY" title="动作能力" description="维护外部动作能力清单、风险级别、人工确认要求和回调地址。" action={<button className="primaryButton" onClick={() => setModal("action")}><Plus size={16} />新增动作</button>} rows={demoData.actions} columns={[col("action_type", "动作类型", true), col("risk_level", "风险"), col("confirm_required", "人工确认"), col("status", "状态")]} onSelect={setSelected} /> : null}
          {page === "audit" ? <DataPage label="AUDIT" title="审计与追踪" description="查询客户后台配置变更日志，并跳转消息决策追踪。" rows={demoData.customerAudit} columns={[col("audit_log_id", "审计 ID", true), col("action", "动作"), col("object_type", "对象"), col("reason", "原因"), col("created_at", "时间")]} onSelect={setSelected} /> : null}
        </section>
        <aside className="systemContextPanel">
          <h2>客户上下文</h2>
          <Metric label="当前组织" value={organizationId} tone="info" />
          <Metric label="当前店铺" value={storeId} tone="info" />
          <Metric label="资料缺口" value="2" tone="warn" />
          <Metric label="待审核知识" value="24" tone="bad" />
          <CompactList title="最近变更" rows={demoData.customerAudit} fields={["action", "object_type", "created_at"]} />
        </aside>
      </div>
      {selected ? <Drawer title="记录详情" record={selected} onClose={() => setSelected(null)} /> : null}
      {modal ? <ActionModal title={modalTitle(modal)} onClose={() => setModal(null)} setToast={setToast} /> : null}
    </main>
  );
}

function SystemAdminShell({ session, onLogout, setToast }: { session: JsonRecord; onLogout: () => void; setToast: (toast: ToastState) => void }) {
  const [page, setPage] = React.useState<SystemPage>("home");
  const [selected, setSelected] = React.useState<JsonRecord | null>(null);
  const [modal, setModal] = React.useState<"organization" | "store" | "freeze" | "release" | null>(null);
  const [scope, setScope] = React.useState("全平台");
  const [query, setQuery] = React.useState("");

  function runSearch(event: React.FormEvent) {
    event.preventDefault();
    setToast({ tone: "info", text: query ? `已按 ${query} 定位排障上下文` : "请输入 decision_id、请求 ID、组织或店铺" });
  }

  return (
    <main className="adminShell systemShell">
      <header className="systemTopbar">
        <div className="topbarBrand"><span className="brandTile">A</span><span>Agent System Admin</span></div>
        <form className="topbarSearch" onSubmit={runSearch}>
          <select value={scope} onChange={(event) => setScope(event.target.value)} aria-label="租户范围">
            <option>全平台</option>
            <option>org-001 / 三人行电商</option>
            <option>org-002 / 家居旗舰事业部</option>
          </select>
          <div className="searchBox"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="decision_id / 请求 ID / 外部消息 ID / 组织 / 店铺" /></div>
        </form>
        <div className="topbarIconGroup">
          <button className="topIconButton" title="告警"><Bell size={18} /></button>
          <button className="topIconButton" title="刷新" onClick={() => setToast({ tone: "success", text: "系统后台数据已刷新" })}><RefreshCw size={18} /></button>
          <UserPill user={readRecord(session, "user")} onLogout={onLogout} />
        </div>
      </header>
      <div className="shellGrid">
        <SideNav items={systemNav} active={page} onChange={setPage} />
        <section className="mainCanvas">
          {page === "home" ? <SystemHome setPage={setPage} /> : null}
          {page === "tenants" ? <TenantPage setModal={setModal} setSelected={setSelected} /> : null}
          {page === "readiness" ? <DataPage label="READINESS" title="配置完成度" description="按租户和店铺查看上线阻断、资料、知识、规则和动作能力完成度。" rows={demoData.readiness} columns={[col("store_id", "店铺 ID", true), col("check", "检查项"), col("status", "状态"), col("reason", "原因")]} onSelect={setSelected} /> : null}
          {page === "knowledge" ? <DataPage label="CONTENT GOVERNANCE" title="资料与知识" description="跨租户查看资料解析、知识抽取、embedding 和审核阻断摘要。" rows={demoData.knowledge} columns={[col("candidate_id", "候选 ID", true), col("product_id", "商品 ID", true), col("status", "状态"), col("source", "来源"), col("risk", "风险")]} onSelect={setSelected} /> : null}
          {page === "traces" ? <DataPage label="TRACE" title="决策追踪" description={`按 decision_id、请求 ID 或外部消息 ID 定位消息决策摘要，数据源 ${apiPaths.systemMessageTraces}。`} action={<button className="primaryButton"><Search size={16} />定位决策</button>} rows={demoData.traces} columns={[col("decision_id", "决策 ID", true), col("organization_id", "组织", true), col("store_id", "店铺", true), col("status", "状态"), col("risk_level", "风险"), col("created_at", "时间")]} onSelect={setSelected} /> : null}
          {page === "tasks" ? <TaskPage setSelected={setSelected} setToast={setToast} /> : null}
          {page === "rules" ? <DataPage label="RULES AND ACTIONS" title="规则与动作" description="查看平台强制规则、店铺规则状态和动作能力风险摘要。" rows={[...demoData.rules, ...demoData.actions]} columns={[col("rule_id", "规则 ID", true), col("action_type", "动作类型", true), col("name", "名称"), col("risk_level", "风险"), col("status", "状态")]} onSelect={setSelected} /> : null}
          {page === "release" ? <DataPage label="EVAL AND RELEASE" title="评测与发布" description="查看 quick live eval、红线集、发布门禁和阻断原因。" action={<button className="primaryButton" onClick={() => setModal("release")}><PlayCircle size={16} />创建发布检查</button>} rows={demoData.release} columns={[col("suite", "套件", true), col("status", "状态"), col("failed_cases", "失败数"), col("updated_at", "更新时间")]} onSelect={setSelected} /> : null}
          {page === "audit" ? <DataPage label="SECURITY AUDIT" title="安全审计" description="跨租户查询、敏感数据查看、高风险操作和代客户操作都必须留痕。" action={<button className="dangerButton" onClick={() => setModal("freeze")}><ShieldAlert size={16} />冻结凭据</button>} rows={demoData.systemAudit} columns={[col("audit_log_id", "审计 ID", true), col("actor", "操作者"), col("action", "动作"), col("object_type", "对象"), col("reason", "原因"), col("created_at", "时间")]} onSelect={setSelected} /> : null}
          {page === "health" ? <DataPage label="HEALTH" title="系统健康" description="查看 API、数据库、对象存储、队列、LLM provider 和 K8s health。" rows={demoData.health} columns={[col("name", "组件"), col("status", "状态"), col("message", "信息")]} onSelect={setSelected} /> : null}
        </section>
        <aside className="systemContextPanel">
          <h2>运行摘要</h2>
          <Metric label="租户范围" value={scope} tone="info" />
          <Metric label="上线阻断" value="3" tone="bad" />
          <Metric label="运行任务" value="1" tone="warn" />
          <Metric label="健康异常" value="1" tone="warn" />
          <CompactList title="高优先级告警" rows={demoData.readiness} fields={["store_id", "status", "reason"]} />
        </aside>
      </div>
      {selected ? <Drawer title="系统记录详情" record={selected} onClose={() => setSelected(null)} /> : null}
      {modal ? <ActionModal title={modalTitle(modal)} onClose={() => setModal(null)} setToast={setToast} danger={modal === "freeze"} /> : null}
    </main>
  );
}

function SystemHome({ setPage }: { setPage: (page: SystemPage) => void }) {
  return (
    <>
      <PageHeader
        label="SYSTEM OVERVIEW"
        title="系统首页"
        description="面向平台运营和技术支持的一屏判断：上线阻断、配置完成度、最近决策、运行任务和高优先级告警。"
        action={<button className="primaryButton" onClick={() => setPage("traces")}><Search size={16} />定位决策</button>}
      />
      <div className="metricGrid">
        <Metric label="活跃组织" value="3" tone="ok" />
        <Metric label="今日决策量" value="18,426" tone="info" />
        <Metric label="转人工率" value="12.4%" tone="warn" />
        <Metric label="上线阻断" value="3" tone="bad" />
      </div>
      <div className="contentGrid two">
        <DataTable title="上线阻断队列" rows={demoData.readiness} columns={[col("store_id", "店铺", true), col("check", "检查项"), col("status", "状态"), col("reason", "原因")]} />
        <DataTable title="最近消息决策" rows={demoData.traces} columns={[col("decision_id", "决策 ID", true), col("status", "状态"), col("risk_level", "风险"), col("created_at", "时间")]} />
      </div>
    </>
  );
}

function CustomerOverview({ setPage, setModal }: { setPage: (page: CustomerPage) => void; setModal: (modal: "product" | "rule" | "action") => void }) {
  return (
    <>
      <PageHeader
        label="CUSTOMER OPERATIONS"
        title="首页概览"
        description="围绕客户自己的资料缺口、待审核知识、价格过期、规则状态和动作能力异常展开。"
        action={<button className="primaryButton" onClick={() => setModal("product")}><PackagePlus size={16} />新增商品</button>}
      />
      <div className="metricGrid">
        <Metric label="资料缺口" value="2" tone="warn" />
        <Metric label="待审核知识" value="24" tone="bad" />
        <Metric label="规则生效" value="18" tone="ok" />
        <Metric label="动作异常" value="1" tone="warn" />
      </div>
      <div className="contentGrid two">
        <DataTable title="资料缺口" rows={demoData.productGaps} columns={[col("product_id", "商品 ID", true), col("title", "商品"), col("status", "状态"), col("reason", "原因")]} />
        <WorkflowPanel
          title="配置闭环"
          steps={[
            ["商品资料", "上传说明书、图片和 SKU 属性", () => setPage("products")],
            ["知识审核", "批准后才进入自动回复知识源", () => setPage("knowledge")],
            ["规则与动作", "高风险动作必须人工确认", () => setPage("rules")]
          ]}
        />
      </div>
    </>
  );
}

function TenantPage({ setModal, setSelected }: { setModal: (modal: "organization" | "store") => void; setSelected: (record: JsonRecord) => void }) {
  return (
    <>
      <PageHeader
        label="TENANTS"
        title="租户与店铺"
        description="创建组织、店铺和客户后台初始管理员邀请，查看跨租户 readiness。"
        action={<div className="buttonRow"><button className="primaryButton" onClick={() => setModal("organization")}><Users size={16} />创建组织</button><button className="secondaryButton" onClick={() => setModal("store")}><Store size={16} />创建店铺</button></div>}
      />
      <div className="contentGrid two">
        <DataTable title="组织" rows={demoData.organizations} columns={[col("organization_id", "组织 ID", true), col("name", "名称"), col("status", "状态"), col("readiness", "完成度"), col("blocked_items", "阻断项")]} onSelect={setSelected} />
        <DataTable title="店铺" rows={demoData.stores} columns={[col("store_id", "店铺 ID", true), col("organization_id", "组织", true), col("platform", "平台"), col("status", "状态"), col("readiness", "完成度")]} onSelect={setSelected} />
      </div>
    </>
  );
}

function TaskPage({ setSelected, setToast }: { setSelected: (record: JsonRecord) => void; setToast: (toast: ToastState) => void }) {
  return (
    <DataPage
      label="TASKS"
      title="异步任务"
      description="查看资料解析、知识抽取、embedding、批量导入和评测任务状态；重试必须记录原因。"
      rows={demoData.tasks}
      columns={[col("task_id", "任务 ID", true), col("task_type", "类型"), col("status", "状态"), col("retryable", "可重试"), col("updated_at", "更新时间")]}
      onSelect={setSelected}
      action={<button className="secondaryButton" onClick={() => setToast({ tone: "info", text: "重试动作需要填写原因并写入系统审计" })}><RefreshCw size={16} />重试所选</button>}
    />
  );
}

function KnowledgeReviewPanel({ setToast }: { setToast: (toast: ToastState) => void }) {
  const [candidate, setCandidate] = React.useState("kn-701");
  const [reason, setReason] = React.useState("对照说明书原文，删除营销夸张表达");
  return (
    <>
      <PageHeader label="KNOWLEDGE REVIEW" title="知识审核" description="对照原始资料审核候选知识，批准后才写入可召回知识和 embedding。" />
      <div className="contentGrid two">
        <section className="operationPanel">
          <h2>审核动作</h2>
          <label>候选 ID<input value={candidate} onChange={(event) => setCandidate(event.target.value)} /></label>
          <label>审核原因<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label>
          <div className="buttonRow">
            <button className="primaryButton" onClick={() => setToast({ tone: "success", text: `${candidate} 已批准` })}><CheckCircle2 size={16} />批准</button>
            <button className="dangerButton" onClick={() => setToast({ tone: "error", text: `${candidate} 已拒绝` })}><AlertTriangle size={16} />拒绝</button>
          </div>
        </section>
        <DataTable title="待审核候选" rows={demoData.knowledge} columns={[col("candidate_id", "候选 ID", true), col("product_id", "商品 ID", true), col("status", "状态"), col("source", "来源"), col("risk", "风险")]} />
      </div>
    </>
  );
}

function DataPage({
  label,
  title,
  description,
  rows,
  columns,
  action,
  onSelect
}: {
  label: string;
  title: string;
  description: string;
  rows: JsonRecord[];
  columns: TableColumn[];
  action?: React.ReactNode;
  onSelect?: (record: JsonRecord) => void;
}) {
  return (
    <>
      <PageHeader label={label} title={title} description={description} action={action} />
      <FilterBar />
      <DataTable title={title} rows={rows} columns={columns} onSelect={onSelect} />
    </>
  );
}

function Topbar({ brand, scope, user, onLogout }: { brand: string; scope: React.ReactNode; user: JsonRecord; onLogout: () => void }) {
  return (
    <header className="systemTopbar">
      <div className="topbarBrand"><span className="brandTile">A</span><span>{brand}</span></div>
      <div className="customerScope">{scope}</div>
      <div className="topbarIconGroup">
        <button className="topIconButton" title="刷新"><RefreshCw size={18} /></button>
        <UserPill user={user} onLogout={onLogout} />
      </div>
    </header>
  );
}

function ScopeControls({
  organizationId,
  storeId,
  organizations,
  stores,
  setOrganizationId,
  setStoreId
}: {
  organizationId: string;
  storeId: string;
  organizations: JsonRecord[];
  stores: JsonRecord[];
  setOrganizationId: (value: string) => void;
  setStoreId: (value: string) => void;
}) {
  return (
    <>
      <select value={organizationId} onChange={(event) => setOrganizationId(event.target.value)} aria-label="组织">
        {organizations.map((item) => <option key={String(item.organization_id)} value={String(item.organization_id)}>{String(item.name)}</option>)}
      </select>
      <select value={storeId} onChange={(event) => setStoreId(event.target.value)} aria-label="店铺">
        {stores.map((item) => <option key={String(item.store_id)} value={String(item.store_id)}>{String(item.name)}</option>)}
      </select>
    </>
  );
}

function SideNav<T extends string>({ items, active, onChange }: { items: Array<NavItem<T>>; active: T; onChange: (key: T) => void }) {
  const groups = Array.from(new Set(items.map((item) => item.group)));
  return (
    <nav className="sidebar" aria-label="后台导航">
      {groups.map((group) => (
        <div className="navGroup" key={group}>
          <div className="navLabel">{group}</div>
          {items.filter((item) => item.group === group).map((item) => (
            <button key={item.key} className={active === item.key ? "navItem active" : "navItem"} onClick={() => onChange(item.key)}>
              {item.icon}<span>{item.label}</span>
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}

function PageHeader({ label, title, description, action }: { label: string; title: string; description: string; action?: React.ReactNode }) {
  return (
    <header className="pageHead">
      <div>
        <p className="eyebrow">{label}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action ? <div className="pageActions">{action}</div> : null}
    </header>
  );
}

function FilterBar() {
  return (
    <section className="filterBar">
      <ListFilter size={17} />
      <input placeholder="组织 ID" />
      <input placeholder="店铺 ID" />
      <select defaultValue=""><option value="">全部状态</option><option>active</option><option>pending</option><option>blocked</option></select>
      <button className="secondaryButton"><Search size={16} />筛选</button>
    </section>
  );
}

function DataTable({ title, rows, columns, onSelect }: { title: string; rows: JsonRecord[]; columns: TableColumn[]; onSelect?: (record: JsonRecord) => void }) {
  return (
    <section className="tablePanel">
      <div className="tableHeader">
        <h2>{title}</h2>
        <span>{rows.length} 条</span>
      </div>
      {rows.length ? (
        <div className="tableWrap">
          <table>
            <thead>
              <tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={String(row.id || row.audit_log_id || row.decision_id || row.task_id || row.product_id || index)} onClick={() => onSelect?.(row)}>
                  {columns.map((column) => (
                    <td key={column.key} data-label={column.label} className={column.mono ? "monoCell" : ""}>{renderCell(row[column.key])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <EmptyState />}
    </section>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  return (
    <div className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value || "-"}</strong>
    </div>
  );
}

function CompactList({ title, rows, fields }: { title: string; rows: JsonRecord[]; fields: string[] }) {
  return (
    <section className="compactList">
      <h3>{title}</h3>
      {rows.slice(0, 4).map((row, index) => (
        <div className="compactRow" key={index}>
          {fields.map((field) => <span key={field}>{String(row[field] ?? "-")}</span>)}
        </div>
      ))}
    </section>
  );
}

function WorkflowPanel({ title, steps }: { title: string; steps: Array<[string, string, () => void]> }) {
  return (
    <section className="operationPanel">
      <h2>{title}</h2>
      <div className="workflowList">
        {steps.map(([name, description, action]) => (
          <button key={name} className="workflowStep" onClick={action}>
            <span><strong>{name}</strong><em>{description}</em></span><ChevronRight size={16} />
          </button>
        ))}
      </div>
    </section>
  );
}

function Drawer({ title, record, onClose }: { title: string; record: JsonRecord; onClose: () => void }) {
  return (
    <aside className="drawer" aria-label={title}>
      <div className="drawerHeader">
        <div><p className="eyebrow">DETAIL</p><h2>{title}</h2></div>
        <button className="secondaryButton" onClick={onClose}>关闭</button>
      </div>
      <pre>{JSON.stringify(record, null, 2)}</pre>
    </aside>
  );
}

function ActionModal({ title, onClose, setToast, danger }: { title: string; onClose: () => void; setToast: (toast: ToastState) => void; danger?: boolean }) {
  const [reason, setReason] = React.useState("");
  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!reason.trim()) {
      setToast({ tone: "error", text: "高风险或写操作必须填写原因" });
      return;
    }
    setToast({ tone: danger ? "error" : "success", text: `${title} 已记录，审计原因：${reason}` });
    onClose();
  }
  return (
    <div className="modalBackdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <p className="eyebrow">CONFIRM ACTION</p>
        <h2>{title}</h2>
        <label>操作原因<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        <div className="buttonRow end">
          <button type="button" className="secondaryButton" onClick={onClose}>取消</button>
          <button className={danger ? "dangerButton" : "primaryButton"}>{danger ? <ShieldAlert size={16} /> : <CheckCircle2 size={16} />}提交</button>
        </div>
      </form>
    </div>
  );
}

function UserPill({ user, onLogout }: { user: JsonRecord; onLogout: () => void }) {
  return (
    <div className="userPill">
      <span>{String(user.display_name || user.email || "已登录").slice(0, 10)}</span>
      <button title="退出登录" onClick={onLogout}><LogOut size={16} /></button>
    </div>
  );
}

function PreviewMetric({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
}

function Toast({ toast, onClose }: { toast: NonNullable<ToastState>; onClose: () => void }) {
  React.useEffect(() => {
    const timer = window.setTimeout(onClose, 3200);
    return () => window.clearTimeout(timer);
  }, [onClose]);
  return <div className={`toast ${toast.tone}`}>{toast.text}</div>;
}

function EmptyState() {
  return <p className="emptyText">暂无记录</p>;
}

function renderCell(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string") {
    const tone = toneFor(value);
    return tone ? <span className={`status ${tone}`}>{value}</span> : <span>{value}</span>;
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return <code>{JSON.stringify(value)}</code>;
  return String(value);
}

function toneFor(value: string): Tone | "" {
  return statusTone[value.toLowerCase()] || "";
}

function arrayFrom(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.filter((item): item is JsonRecord => Boolean(item) && typeof item === "object") : [];
}

function readRecord(source: unknown, key: string): JsonRecord {
  if (!source || typeof source !== "object") return {};
  const value = (source as JsonRecord)[key];
  return value && typeof value === "object" ? value as JsonRecord : {};
}

function firstId(value: unknown, fallback: string) {
  const first = arrayFrom(value)[0];
  return String(first?.organization_id || first?.store_id || first?.id || fallback);
}

function col(key: string, label: string, mono = false): TableColumn {
  return { key, label, mono };
}

function modalTitle(modal: string) {
  const titles: Record<string, string> = {
    product: "新增商品",
    rule: "新增规则",
    action: "新增动作能力",
    organization: "创建组织",
    store: "创建店铺",
    freeze: "冻结凭据",
    release: "创建发布检查"
  };
  return titles[modal] || modal;
}

createRoot(document.getElementById("root")!).render(<App />);
