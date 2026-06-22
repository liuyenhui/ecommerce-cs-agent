import React from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  Boxes,
  CheckCircle2,
  ClipboardList,
  Database,
  FileText,
  HeartPulse,
  KeyRound,
  Layers3,
  ListFilter,
  Loader2,
  LogOut,
  MessageSquareText,
  PackagePlus,
  PlayCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Store,
  UploadCloud,
  Users
} from "lucide-react";
import "./styles.css";

type JsonRecord = Record<string, unknown>;
type Workspace = "customer" | "system";
type CustomerTab = "overview" | "products" | "knowledge" | "audit";
type SystemTab = "home" | "tenants" | "traces" | "tasks" | "audit" | "health";
type ToastState = { tone: "success" | "error" | "info"; text: string } | null;
type SystemFiltersState = { organization_id: string; store_id: string; status: string; trace_id: string };
type EmptyStateProps = { title?: string; description?: string; action?: React.ReactNode };

type Page<T = JsonRecord> = {
  items?: T[];
  organizations?: T[];
  stores?: T[];
  page_info?: JsonRecord;
};

const customerTabs: Array<{ key: CustomerTab; label: string; icon: React.ReactNode }> = [
  { key: "overview", label: "首页概览", icon: <Activity size={17} /> },
  { key: "products", label: "商品资料", icon: <Boxes size={17} /> },
  { key: "knowledge", label: "知识审核", icon: <FileText size={17} /> },
  { key: "audit", label: "审计查询", icon: <ClipboardList size={17} /> }
];

const systemTabs: Array<{ key: SystemTab; label: string; group: string; icon: React.ReactNode }> = [
  { key: "home", label: "系统首页", group: "平台运营", icon: <Activity size={17} /> },
  { key: "tenants", label: "租户与店铺", group: "平台运营", icon: <Store size={17} /> },
  { key: "traces", label: "决策追踪", group: "排障治理", icon: <Search size={17} /> },
  { key: "tasks", label: "异步任务", group: "排障治理", icon: <PlayCircle size={17} /> },
  { key: "audit", label: "安全审计", group: "发布安全", icon: <ShieldCheck size={17} /> },
  { key: "health", label: "系统健康", group: "发布安全", icon: <HeartPulse size={17} /> }
];

const CUSTOMER_ADMIN_HOST = "admin.ecommerce-cs-agent-dev.fcihome.com";
const SYSTEM_ADMIN_HOST = "system-admin.ecommerce-cs-agent-dev.fcihome.com";

export function detectWorkspaceFromLocation(location: Pick<Location, "hostname" | "pathname">): Workspace {
  if (location.hostname === SYSTEM_ADMIN_HOST || location.hostname.startsWith("system-admin.")) return "system";
  if (location.hostname === CUSTOMER_ADMIN_HOST || location.hostname.startsWith("admin.")) return "customer";
  return location.pathname.startsWith("/system-admin") ? "system" : "customer";
}

const statusTone: Record<string, "ok" | "warn" | "bad" | "info"> = {
  active: "ok",
  healthy: "ok",
  ok: "ok",
  completed: "ok",
  accepted: "ok",
  pending: "warn",
  waiting_context: "warn",
  failed: "bad",
  blocked: "bad",
  error: "bad",
  frozen: "bad"
};

const statusLabel: Record<string, string> = {
  active: "启用",
  healthy: "健康",
  ok: "正常",
  completed: "已完成",
  accepted: "已受理",
  pending: "待处理",
  waiting_context: "等待补充上下文",
  failed: "失败",
  blocked: "阻断",
  error: "异常",
  frozen: "冻结"
};

const fieldLabels: Record<string, string> = {
  id: "ID",
  name: "名称",
  organization_id: "组织 ID",
  store_id: "店铺 ID",
  status: "状态",
  reason: "原因",
  platform: "平台",
  created_at: "创建时间",
  updated_at: "更新时间",
  decision_id: "决策 ID",
  risk_level: "风险等级",
  task_id: "任务 ID",
  task_type: "任务类型",
  retryable: "可重试",
  audit_log_id: "审计 ID",
  action: "动作",
  object_type: "对象类型",
  message: "消息"
};

const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");

function normalizePath() {
  if (typeof window === "undefined") return "/";
  const path = window.location.pathname || "/";
  return path.endsWith("/") && path !== "/" ? path.slice(0, -1) : path;
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
  const [workspace] = React.useState<Workspace>(() => detectWorkspaceFromLocation(window.location));
  const [path, setPath] = React.useState(() => normalizePath());

  React.useEffect(() => {
    const syncPath = () => setPath(normalizePath());
    window.addEventListener("popstate", syncPath);
    return () => window.removeEventListener("popstate", syncPath);
  }, []);

  function navigate(nextPath: string) {
    window.history.pushState({}, "", nextPath);
    setPath(normalizePath());
  }

  return workspace === "system" ? <SystemSite /> : <CustomerSite path={path} navigate={navigate} />;
}

function CustomerSite({ path, navigate }: { path: string; navigate: (path: string) => void }) {
  const [customerTab, setCustomerTab] = React.useState<CustomerTab>("overview");
  const [customerSession, setCustomerSession] = React.useState<JsonRecord | null>(null);
  const [toast, setToast] = React.useState<ToastState>(null);
  const demoSlides = [
    {
      title: "商品信息统一管理",
      text: "说明书、SKU、价格、常见问题和适用范围统一维护，避免客服和 AI 各看各的资料。",
      icon: <UploadCloud size={20} />
    },
    {
      title: "AI 自动学习商品知识",
      text: "资料先转成可审核的知识和模拟问答，让 AI 学习前后都有依据可查。",
      icon: <Bot size={20} />
    },
    {
      title: "AI 客服回复可控",
      text: "自动回复前经过规则、风险、上下文完整性和模拟问答检查，高风险场景先转人工。",
      icon: <SlidersHorizontal size={20} />
    }
  ];
  const flowSteps = ["上传商品说明书", "AI 学习", "模拟问答", "AI 自动回复"];

  const customerAuthed = Boolean(customerSession);

  async function refreshSession() {
    const me = await requestJson("/v1/admin/auth/me");
    setCustomerSession(me);
  }

  async function logout() {
    try {
      await requestJson("/v1/admin/auth/logout", { method: "POST" });
    } catch {
      // Session may already be gone; local state still needs clearing.
    }
    setCustomerSession(null);
    setToast({ tone: "info", text: "已退出当前后台" });
    navigate("/login");
  }

  React.useEffect(() => {
    void refreshSession().catch(() => undefined);
  }, []);

  if (path === "/login") {
    return (
      <main className="customerLoginShell">
        <button className="textButton" onClick={() => navigate("/")}>
          <ArrowRight size={15} className="flipIcon" />返回首页
        </button>
        <LoginPanel key="customer-login" target="customer" onLoggedIn={(session) => {
          setCustomerSession(session);
          navigate("/admin");
        }} setToast={setToast} />
        {toast ? <Toast toast={toast} onClose={() => setToast(null)} /> : null}
      </main>
    );
  }

  if (path.startsWith("/admin")) {
    return (
      <CustomerAdminShell
        customerSession={customerSession}
        customerTab={customerTab}
        setCustomerTab={setCustomerTab}
        refreshSession={refreshSession}
        logout={logout}
        setToast={setToast}
        toast={toast}
      />
    );
  }

  return (
    <main className="landingPage">
      <header className="landingHeader">
        <button className="landingBrand" onClick={() => navigate("/")} aria-label="回到首页">
          <MessageSquareText size={18} />
          <span>AI 客服资料中台</span>
        </button>
        <nav aria-label="公开页导航">
          <button className="textButton" onClick={() => document.getElementById("demo-flow")?.scrollIntoView({ behavior: "smooth" })}>
            查看演示流程
          </button>
          <button className="darkButton" onClick={() => navigate(customerAuthed ? "/admin" : "/login")}>
            客户登录
          </button>
        </nav>
      </header>

      <section className="heroSection">
        <div className="heroCopy">
          <p className="landingEyebrow">AI 客服上线前，先把商品资料管好</p>
          <h1>商品信息管好了，AI 客服才答得准。</h1>
          <p className="heroSubtitle">
            上传商品说明书、价格和常见问题，让 AI 先学习，再通过模拟问答检查效果。真正自动回复前，还能用规则控制范围和风险。
          </p>
          <div className="heroActions">
            <button className="darkButton" onClick={() => navigate(customerAuthed ? "/admin" : "/login")}>
              进入客户后台 <ArrowRight size={16} />
            </button>
            <button className="textButton" onClick={() => document.getElementById("demo-flow")?.scrollIntoView({ behavior: "smooth" })}>
              查看演示流程
            </button>
          </div>
        </div>
        <div className="heroPreview" aria-label="客户后台产品预览">
          <div className="previewTopbar">
            <span />
            <span />
            <span />
          </div>
          <div className="previewGrid">
            <div className="previewNav" />
            <div className="previewContent">
              <div className="previewLine wide" />
              <div className="previewLine" />
              <div className="previewTable">
                <span />
                <span />
                <span />
                <span />
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="demoCarousel" aria-label="产品演示轮播">
        <div className="sectionIntro">
          <p className="landingEyebrow">产品演示</p>
          <h2>从资料到回复，一条线看清楚。</h2>
        </div>
        <div className="demoViewport">
          <div className="demoTrack">
            {demoSlides.map((slide) => (
              <article className="demoSlide" key={slide.title}>
                <div className="slideIcon">{slide.icon}</div>
                <h3>{slide.title}</h3>
                <p>{slide.text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="flowSection" id="demo-flow">
        <div className="sectionIntro">
          <p className="landingEyebrow">怎么工作</p>
          <h2>上传商品说明书 → AI 学习 → 模拟问答 → AI 自动回复</h2>
        </div>
        <ol className="flowRail" aria-label="上传商品说明书到 AI 自动回复流程">
          {flowSteps.map((step, index) => (
            <li key={step}>
              <span className="flowIndex">{index + 1}</span>
              <strong>{step}</strong>
              {index < flowSteps.length - 1 ? <ChevronConnector /> : null}
            </li>
          ))}
        </ol>
      </section>

      <section className="controlSection">
        <div>
          <p className="landingEyebrow">可控自动化</p>
          <h2>AI 先学习，规则再放行。</h2>
          <p>
            商品知识通过审核后才进入可用资料；模拟问答先检查效果；自动回复还要经过规则、风险和上下文完整性判断。
          </p>
        </div>
        <div className="controlList">
          <span>资料缺口提醒</span>
          <span>知识审核状态</span>
          <span>价格过期提示</span>
          <span>高风险转人工</span>
        </div>
      </section>

      <section className="finalCta">
        <h2>先管好商品资料，再让 AI 自动回复。</h2>
        <button className="darkButton" onClick={() => navigate(customerAuthed ? "/admin" : "/login")}>
          进入客户后台 <ArrowRight size={16} />
        </button>
      </section>
    </main>
  );
}

function CustomerAdminShell({
  customerSession,
  customerTab,
  setCustomerTab,
  refreshSession,
  logout,
  setToast,
  toast
}: {
  customerSession: JsonRecord | null;
  customerTab: CustomerTab;
  setCustomerTab: (tab: CustomerTab) => void;
  refreshSession: () => Promise<void>;
  logout: () => Promise<void>;
  setToast: (toast: ToastState) => void;
  toast: ToastState;
}) {
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const isAuthenticated = Boolean(customerSession);

  React.useEffect(() => {
    if (!mobileNavOpen) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileNavOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileNavOpen]);

  return (
    <main className={`appShell ${isAuthenticated ? "isAuthed" : "isGuest"} ${mobileNavOpen ? "navOpen" : ""}`}>
      {isAuthenticated ? (
        <aside className="rail">
          <div className="brandMark">
            <ShieldCheck size={22} />
            <span>AI 客服客户后台</span>
          </div>
          <Navigation
            workspace="customer"
            customerTab={customerTab}
            systemTab="home"
            setCustomerTab={setCustomerTab}
            setSystemTab={() => undefined}
            onNavigate={() => setMobileNavOpen(false)}
          />
        </aside>
      ) : null}
      {isAuthenticated ? <button className="navBackdrop" aria-label="关闭导航" onClick={() => setMobileNavOpen(false)} /> : null}

      <section className="mainPane">
        <TopBar
          workspace="customer"
          session={customerSession}
          onRefresh={() => refreshSession().then(() => setToast({ tone: "success", text: "会话已刷新" })).catch((error) => setToast({ tone: "error", text: error.message }))}
          onLogout={() => void logout()}
          onToggleNav={() => setMobileNavOpen((open) => !open)}
          navOpen={mobileNavOpen}
        />

        {customerSession ? (
          <CustomerWorkspace
            session={customerSession}
            activeTab={customerTab}
            setActiveTab={setCustomerTab}
            setToast={setToast}
          />
        ) : (
          <LoginPanel key="customer-login" target="customer" onLoggedIn={() => void refreshSession()} setToast={setToast} />
        )}
      </section>

      {toast ? <Toast toast={toast} onClose={() => setToast(null)} /> : null}
    </main>
  );
}

function SystemSite() {
  const [systemTab, setSystemTab] = React.useState<SystemTab>("home");
  const [systemSession, setSystemSession] = React.useState<JsonRecord | null>(null);
  const [toast, setToast] = React.useState<ToastState>(null);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const isAuthenticated = Boolean(systemSession);

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

  React.useEffect(() => {
    if (!mobileNavOpen) return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMobileNavOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [mobileNavOpen]);

  return (
    <main className={`appShell ${isAuthenticated ? "isAuthed" : "isGuest"} ${mobileNavOpen ? "navOpen" : ""}`}>
      {isAuthenticated ? (
        <aside className="rail">
          <div className="brandMark">
            <ShieldCheck size={22} />
            <span>Ecommerce CS System Admin</span>
          </div>
          <Navigation
            workspace="system"
            customerTab="overview"
            systemTab={systemTab}
            setCustomerTab={() => undefined}
            setSystemTab={setSystemTab}
            onNavigate={() => setMobileNavOpen(false)}
          />
        </aside>
      ) : null}
      {isAuthenticated ? <button className="navBackdrop" aria-label="关闭导航" onClick={() => setMobileNavOpen(false)} /> : null}

      <section className="mainPane">
        <TopBar
          workspace="system"
          session={systemSession}
          onRefresh={() => refreshSession().then(() => setToast({ tone: "success", text: "会话已刷新" })).catch((error) => setToast({ tone: "error", text: error.message }))}
          onLogout={() => void logout()}
          onToggleNav={() => setMobileNavOpen((open) => !open)}
          navOpen={mobileNavOpen}
        />

        {systemSession ? (
          <SystemWorkspace
            session={systemSession}
            activeTab={systemTab}
            setActiveTab={setSystemTab}
            setToast={setToast}
          />
        ) : (
          <LoginPanel key="system-login" target="system" onLoggedIn={(session) => setSystemSession(session)} setToast={setToast} />
        )}
      </section>

      {toast ? <Toast toast={toast} onClose={() => setToast(null)} /> : null}
    </main>
  );
}

function ChevronConnector() {
  return <ArrowRight className="flowArrow" size={18} aria-hidden="true" />;
}

function Navigation(props: {
  workspace: Workspace;
  customerTab: CustomerTab;
  systemTab: SystemTab;
  setCustomerTab: (tab: CustomerTab) => void;
  setSystemTab: (tab: SystemTab) => void;
  onNavigate?: () => void;
}) {
  if (props.workspace === "customer") {
    return (
      <nav className="navList" aria-label="客户后台导航">
        <span className="navGroup">客户运营</span>
        {customerTabs.map((tab) => (
          <button key={tab.key} className={props.customerTab === tab.key ? "active" : ""} onClick={() => {
            props.setCustomerTab(tab.key);
            props.onNavigate?.();
          }}>
            {tab.icon}<span>{tab.label}</span>
          </button>
        ))}
      </nav>
    );
  }

  const groups = Array.from(new Set(systemTabs.map((tab) => tab.group)));
  return (
    <nav className="navList" aria-label="系统后台导航">
      {groups.map((group) => (
        <React.Fragment key={group}>
          <span className="navGroup">{group}</span>
          {systemTabs.filter((tab) => tab.group === group).map((tab) => (
            <button key={tab.key} className={props.systemTab === tab.key ? "active" : ""} onClick={() => {
              props.setSystemTab(tab.key);
              props.onNavigate?.();
            }}>
              {tab.icon}<span>{tab.label}</span>
            </button>
          ))}
        </React.Fragment>
      ))}
    </nav>
  );
}

function TopBar({ workspace, session, onRefresh, onLogout, onToggleNav, navOpen }: {
  workspace: Workspace;
  session: JsonRecord | null;
  onRefresh: () => void;
  onLogout: () => void;
  onToggleNav: () => void;
  navOpen: boolean;
}) {
  const user = readRecord(session, "user") || {};
  const userBadge = formatUserBadge(workspace, user);
  const title = workspace === "customer" ? "客户资料与知识运营" : "平台运维与发布治理";
  const subtitle = workspace === "customer" ? "组织、店铺、商品资料、知识审核和审计" : "租户开通、决策追踪、任务、健康和安全审计";
  return (
    <header className="topBar">
      <div className="topTitle">
        {session ? (
          <button className="mobileNavButton" type="button" onClick={onToggleNav} aria-label={navOpen ? "关闭后台导航" : "打开后台导航"} aria-expanded={navOpen}>
            <ListFilter size={17} />
          </button>
        ) : null}
        <div>
          <p className="eyebrow">{workspace === "customer" ? "CUSTOMER ADMIN" : "SYSTEM ADMIN"}</p>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
      </div>
      {session ? (
        <div className="topActions">
          <button className="iconButton" onClick={onRefresh} title="刷新">
            <RefreshCw size={16} />刷新
          </button>
            <span className="userBadge">{userBadge}</span>
            <button className="iconButton" onClick={onLogout} title="退出登录">
              <LogOut size={16} />退出
            </button>
        </div>
      ) : null}
    </header>
  );
}

function LoginPanel({ target, onLoggedIn, setToast }: { target: Workspace; onLoggedIn: (session: JsonRecord) => void; setToast: (toast: ToastState) => void }) {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [loginError, setLoginError] = React.useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = React.useState<Partial<Record<"email" | "password", boolean>>>({});
  const [loading, setLoading] = React.useState(false);
  const loginErrorId = `${target}-login-error`;
  const authErrorText = "邮箱或密码不正确，请检查后重试。";

  function clearLoginError() {
    if (loginError) setLoginError(null);
    if (Object.keys(fieldErrors).length) setFieldErrors({});
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoginError(null);
    const nextFieldErrors = {
      email: !email.trim(),
      password: !password
    };
    if (nextFieldErrors.email || nextFieldErrors.password) {
      setFieldErrors(nextFieldErrors);
      setLoginError("请填写邮箱和密码");
      return;
    }
    setFieldErrors({});
    setLoading(true);
    try {
      const path = target === "customer" ? "/v1/admin/auth/login" : "/v1/system-admin/auth/login";
      const body = { email: email.trim(), password };
      await requestJson(path, { method: "POST", body: JSON.stringify(body) });
      const session = await requestJson(target === "customer" ? "/v1/admin/auth/me" : "/v1/system-admin/auth/me");
      onLoggedIn(session);
      setToast({ tone: "success", text: "登录成功" });
    } catch (error) {
      setLoginError(loginFailureMessage(error, authErrorText));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="loginSurface">
      <form className="loginPanel" onSubmit={submit}>
        <KeyRound size={24} />
        <h2>{target === "customer" ? "客户后台登录" : "系统后台登录"}</h2>
        <label>
          邮箱
          <input
            value={email}
            onChange={(event) => {
              setEmail(event.target.value);
              clearLoginError();
            }}
            autoComplete="username"
            inputMode="email"
            placeholder="name@example.com"
            aria-invalid={Boolean(fieldErrors.email)}
            aria-describedby={loginError && fieldErrors.email ? loginErrorId : undefined}
          />
        </label>
        <label>
          密码
          <input
            value={password}
            onChange={(event) => {
              setPassword(event.target.value);
              clearLoginError();
            }}
            type="password"
            autoComplete="current-password"
            aria-invalid={Boolean(fieldErrors.password)}
            aria-describedby={loginError && fieldErrors.password ? loginErrorId : undefined}
          />
        </label>
        {loginError ? (
          <div className="loginError" id={loginErrorId} role="alert">
            <AlertTriangle size={16} />
            <span>{loginError}</span>
          </div>
        ) : null}
        <button className="primaryButton" type="submit" disabled={loading}>
          {loading ? <Loader2 size={16} className="spin" /> : <ShieldCheck size={16} />}
          登录
        </button>
      </form>
    </section>
  );
}

function loginFailureMessage(error: unknown, authErrorText: string): string {
  const message = error instanceof Error ? error.message : String(error || "");
  if (message.startsWith("401 ")) return authErrorText;
  return "登录失败，请稍后重试。";
}

function CustomerWorkspace({ session, activeTab, setActiveTab, setToast }: {
  session: JsonRecord;
  activeTab: CustomerTab;
  setActiveTab: (tab: CustomerTab) => void;
  setToast: (toast: ToastState) => void;
}) {
  const activeOrg = String(session.active_organization_id || firstId(session.organizations, "org-001"));
  const activeStore = String(session.active_store_id || firstId(session.stores, "store-001"));
  const [organizationId, setOrganizationId] = React.useState(activeOrg);
  const [storeId, setStoreId] = React.useState(activeStore);
  const [data, setData] = React.useState<Record<string, unknown>>({});
  const [loading, setLoading] = React.useState(false);
  const [selected, setSelected] = React.useState<JsonRecord | null>(null);

  const organizations = arrayFrom(session.organizations);
  const stores = arrayFrom(session.stores).filter((store) => !organizationId || String(store.organization_id || store.id).includes(organizationId) || store.organization_id === organizationId);

  async function refresh() {
    setLoading(true);
    try {
      const [users, audit] = await Promise.all([
        requestJson<Page>(`/v1/admin/users?organization_id=${encodeURIComponent(organizationId)}`),
        requestJson<Page>(`/v1/admin/audit-logs?organization_id=${encodeURIComponent(organizationId)}&store_id=${encodeURIComponent(storeId)}`)
      ]);
      setData({ users: users.items || [], audit: audit.items || [] });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    void refresh();
  }, [organizationId, storeId]);

  return (
    <div className="workGrid">
      <section className="contentPane">
        <ContextStrip
          organizationId={organizationId}
          storeId={storeId}
          organizations={organizations}
          stores={stores}
          setOrganizationId={setOrganizationId}
          setStoreId={setStoreId}
          onRefresh={refresh}
          loading={loading}
        />
        {activeTab === "overview" ? (
          <CustomerOverview session={session} data={data} setActiveTab={setActiveTab} />
        ) : null}
        {activeTab === "products" ? (
          <ProductContent organizationId={organizationId} storeId={storeId} setToast={setToast} setSelected={setSelected} />
        ) : null}
        {activeTab === "knowledge" ? (
          <KnowledgeReview storeId={storeId} setToast={setToast} />
        ) : null}
        {activeTab === "audit" ? (
          <AuditTable title="客户后台审计" rows={arrayFrom(data.audit)} onSelect={setSelected} />
        ) : null}
      </section>
      <ContextPanel title="客户上下文">
        <Metric label="组织" value={organizationId} tone="info" />
        <Metric label="店铺" value={storeId} tone="info" />
        <Metric label="成员" value={String(arrayFrom(data.users).length)} tone="ok" />
        <Metric label="审计" value={String(arrayFrom(data.audit).length)} tone="warn" />
      </ContextPanel>
      {selected ? <Drawer title="记录详情" record={selected} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}

function CustomerOverview({ session, data, setActiveTab }: { session: JsonRecord; data: Record<string, unknown>; setActiveTab: (tab: CustomerTab) => void }) {
  return (
    <>
      <SectionHeader label="CUSTOMER" title="首页概览" action={<button onClick={() => setActiveTab("products")}><PackagePlus size={16} />维护商品</button>} />
      <div className="metricGrid">
        <Metric label="可访问组织" value={String(arrayFrom(session.organizations).length)} tone="ok" />
        <Metric label="可访问店铺" value={String(arrayFrom(session.stores).length)} tone="ok" />
        <Metric label="成员记录" value={String(arrayFrom(data.users).length)} tone="info" />
        <Metric label="审计记录" value={String(arrayFrom(data.audit).length)} tone="warn" />
      </div>
      <div className="twoColumns">
        <ListPanel title="组织" rows={arrayFrom(session.organizations)} fields={["id", "name", "status"]} emptyState={{ title: "暂无可访问组织", description: "当前账号还没有可访问组织；请确认租户授权或联系系统管理员开通权限。" }} />
        <ListPanel title="店铺" rows={arrayFrom(session.stores)} fields={["id", "platform", "status"]} emptyState={{ title: "暂无可访问店铺", description: "当前账号还没有可访问店铺；选择其他组织或完成店铺授权后会显示在这里。" }} />
      </div>
    </>
  );
}

function ProductContent({ organizationId, storeId, setToast, setSelected }: {
  organizationId: string;
  storeId: string;
  setToast: (toast: ToastState) => void;
  setSelected: (record: JsonRecord) => void;
}) {
  const [product, setProduct] = React.useState<JsonRecord | null>(null);
  const [asset, setAsset] = React.useState<JsonRecord | null>(null);
  const [markdown, setMarkdown] = React.useState<JsonRecord | null>(null);
  const [health, setHealth] = React.useState<JsonRecord | null>(null);
  const [form, setForm] = React.useState({
    external_product_id: "",
    title: "",
    asset_type: "manual",
    file_ref: "",
    file_hash: "",
    markdown_text: "",
    current_price: ""
  });

  async function saveProduct(event: React.FormEvent) {
    event.preventDefault();
    try {
      const response = await requestJson("/v1/product-content/products", {
        method: "POST",
        body: JSON.stringify({
          organization_id: organizationId,
          store_id: storeId,
          external_product_id: form.external_product_id,
          title: form.title
        })
      });
      setProduct(response);
      setToast({ tone: "success", text: "商品资料已保存" });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  async function saveAsset(event: React.FormEvent) {
    event.preventDefault();
    if (!product?.product_id) return setToast({ tone: "error", text: "请先保存商品资料" });
    try {
      const response = await requestJson("/v1/product-content/assets", {
        method: "POST",
        body: JSON.stringify({
          product_id: product.product_id,
          asset_type: form.asset_type,
          file_ref: form.file_ref,
          file_hash: form.file_hash,
          version: "v1"
        })
      });
      setAsset(response);
      setToast({ tone: "success", text: "资料资产已登记" });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  async function convertMarkdown(event: React.FormEvent) {
    event.preventDefault();
    if (!asset?.asset_id) return setToast({ tone: "error", text: "请先登记资料资产" });
    try {
      const response = await requestJson(`/v1/product-content/assets/${asset.asset_id}/markdown`, {
        method: "POST",
        body: JSON.stringify({
          markdown_text: form.markdown_text,
          conversion_status: "converted",
          source_map: { source: "admin-web" }
        })
      });
      setMarkdown(response);
      setToast({ tone: "success", text: "Markdown 已转换并生成候选" });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  async function savePrice() {
    if (!product?.product_id) return setToast({ tone: "error", text: "请先保存商品资料" });
    try {
      await requestJson("/v1/product-content/price-snapshots", {
        method: "POST",
        body: JSON.stringify({
          product_id: product.product_id,
          store_id: storeId,
          source: "admin-web",
          current_price: Number(form.current_price),
          currency: "CNY",
          effective_at: nowIso(),
          status: "active"
        })
      });
      const nextHealth = await requestJson(`/v1/product-content/products/${product.product_id}/health`);
      setHealth(nextHealth);
      setToast({ tone: "success", text: "价格快照已保存" });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  return (
    <>
      <SectionHeader label="PRODUCT CONTENT" title="商品资料" action={<button onClick={() => product && setSelected(product)}><Search size={16} />查看当前商品</button>} />
      <div className="formGrid">
        <form className="operationPanel" onSubmit={saveProduct}>
          <h3><Boxes size={16} />商品</h3>
          <Field label="外部商品 ID" value={form.external_product_id} onChange={(value) => setForm({ ...form, external_product_id: value })} />
          <Field label="标题" value={form.title} onChange={(value) => setForm({ ...form, title: value })} />
          <button className="primaryButton"><CheckCircle2 size={16} />保存商品</button>
        </form>
        <form className="operationPanel" onSubmit={saveAsset}>
          <h3><Layers3 size={16} />资产</h3>
          <Field label="资料类型" value={form.asset_type} onChange={(value) => setForm({ ...form, asset_type: value })} />
          <Field label="对象 Key / 引用" value={form.file_ref} onChange={(value) => setForm({ ...form, file_ref: value })} />
          <Field label="文件 Hash" value={form.file_hash} onChange={(value) => setForm({ ...form, file_hash: value })} />
          <button><PackagePlus size={16} />登记资产</button>
        </form>
        <form className="operationPanel" onSubmit={convertMarkdown}>
          <h3><FileText size={16} />Markdown</h3>
          <label>
            审稿稿件
            <textarea value={form.markdown_text} onChange={(event) => setForm({ ...form, markdown_text: event.target.value })} />
          </label>
          <button><FileText size={16} />转换并抽取</button>
        </form>
        <div className="operationPanel">
          <h3><HeartPulse size={16} />价格与健康</h3>
          <Field label="当前价格" value={form.current_price} onChange={(value) => setForm({ ...form, current_price: value })} />
          <button onClick={savePrice}><Database size={16} />保存价格快照</button>
          <RecordSummary record={health || markdown || asset || product} />
        </div>
      </div>
    </>
  );
}

function KnowledgeReview({ storeId, setToast }: { storeId: string; setToast: (toast: ToastState) => void }) {
  const [candidateId, setCandidateId] = React.useState("");
  const [content, setContent] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [result, setResult] = React.useState<JsonRecord | null>(null);

  async function review(action: "approve" | "reject") {
    try {
      const response = await requestJson(`/v1/product-content/knowledge-candidates/${candidateId}/reviews`, {
        method: "POST",
        body: JSON.stringify({ action, reviewed_content: content, reason, tags: [storeId] })
      });
      setResult(response);
      setToast({ tone: "success", text: action === "approve" ? "候选已批准" : "候选已拒绝" });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  return (
    <>
      <SectionHeader label="KNOWLEDGE" title="知识审核" />
      <div className="operationPanel widePanel">
        <div className="formGrid compact">
          <Field label="候选 ID" value={candidateId} onChange={setCandidateId} />
          <Field label="审核原因" value={reason} onChange={setReason} />
        </div>
        <label>
          审核后内容
          <textarea value={content} onChange={(event) => setContent(event.target.value)} />
        </label>
        <div className="buttonRow">
          <button className="primaryButton" onClick={() => review("approve")}><CheckCircle2 size={16} />批准</button>
          <button className="dangerButton" onClick={() => review("reject")}><AlertTriangle size={16} />拒绝</button>
        </div>
        <RecordSummary record={result} />
      </div>
    </>
  );
}

function SystemWorkspace({ session, activeTab, setActiveTab, setToast }: {
  session: JsonRecord;
  activeTab: SystemTab;
  setActiveTab: (tab: SystemTab) => void;
  setToast: (toast: ToastState) => void;
}) {
  const [filters, setFilters] = React.useState({ organization_id: "", store_id: "", status: "", trace_id: "" });
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

function ContextStrip({ organizationId, storeId, organizations, stores, setOrganizationId, setStoreId, onRefresh, loading }: {
  organizationId: string;
  storeId: string;
  organizations: JsonRecord[];
  stores: JsonRecord[];
  setOrganizationId: (value: string) => void;
  setStoreId: (value: string) => void;
  onRefresh: () => void;
  loading: boolean;
}) {
  return (
    <section className="filterBar">
      <Store size={17} />
      <select value={organizationId} onChange={(event) => setOrganizationId(event.target.value)}>
        {organizations.map((item) => <option key={String(item.id || item.organization_id)} value={String(item.id || item.organization_id)}>{String(item.name || item.id || item.organization_id)}</option>)}
      </select>
      <select value={storeId} onChange={(event) => setStoreId(event.target.value)}>
        {stores.map((item) => <option key={String(item.id || item.store_id)} value={String(item.id || item.store_id)}>{String(item.name || item.id || item.store_id)}</option>)}
      </select>
      <button onClick={onRefresh}>{loading ? <Loader2 size={16} className="spin" /> : <RefreshCw size={16} />}刷新</button>
    </section>
  );
}

function SectionHeader({ label, title, action }: { label: string; title: string; action?: React.ReactNode }) {
  return (
    <div className="sectionHeader">
      <div>
        <p className="eyebrow">{label}</p>
        <h2>{title}</h2>
      </div>
      {action ? <div className="sectionActions">{action}</div> : null}
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone: "ok" | "warn" | "bad" | "info" }) {
  return (
    <div className={`metric ${tone}`}>
      <span>{label}</span>
      <strong>{value || "-"}</strong>
    </div>
  );
}

function DataTable({ title, rows, fields, onSelect, action, emptyState }: {
  title: string;
  rows: JsonRecord[];
  fields: string[];
  onSelect?: (record: JsonRecord) => void;
  action?: (record: JsonRecord) => React.ReactNode;
  emptyState?: EmptyStateProps;
}) {
  return (
    <section className="tablePanel">
      <h3>{title}</h3>
      {rows.length ? (
        <div className="tableWrap">
          <table>
            <thead>
              <tr>{fields.map((field) => <th key={field}>{fieldLabel(field)}</th>)}{action ? <th>操作</th> : null}</tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={String(row.id || row.decision_id || row.task_id || index)} onClick={() => onSelect?.(row)}>
                  {fields.map((field) => <td key={field} data-label={fieldLabel(field)}>{renderCell(row[field])}</td>)}
                  {action ? <td data-label="操作" onClick={(event) => event.stopPropagation()}>{action(row)}</td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <EmptyState {...(emptyState || tableEmptyState(title))} />}
    </section>
  );
}

function AuditTable({ title, rows, onSelect }: { title: string; rows: JsonRecord[]; onSelect: (record: JsonRecord) => void }) {
  return <DataTable title={title} rows={rows} fields={["audit_log_id", "action", "object_type", "reason", "created_at"]} onSelect={onSelect} />;
}

function ListPanel({ title, rows, fields, emptyState }: { title: string; rows: JsonRecord[]; fields: string[]; emptyState?: EmptyStateProps }) {
  return <DataTable title={title} rows={rows} fields={fields} emptyState={emptyState} />;
}

function ContextPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <aside className="contextPanel">
      <h2>{title}</h2>
      {children}
    </aside>
  );
}

type SummaryItem = { label: string; value: string };

function SystemUserSummary({ user }: { user: JsonRecord }) {
  const items = buildSystemUserSummary(user);
  if (!items.length) return <p className="emptyText">暂无账号摘要</p>;
  return (
    <section className="userSummary" aria-label="当前系统账号摘要">
      <h3>当前账号</h3>
      <dl>
        {items.map((item) => (
          <div key={item.label}>
            <dt>{item.label}</dt>
            <dd>{item.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function Drawer({ title, record, onClose }: { title: string; record: JsonRecord; onClose: () => void }) {
  return (
    <aside className="drawer">
      <div className="drawerHeader">
        <h2>{title}</h2>
        <button onClick={onClose}>关闭</button>
      </div>
      <pre>{JSON.stringify(record, null, 2)}</pre>
    </aside>
  );
}

function Toast({ toast, onClose }: { toast: NonNullable<ToastState>; onClose: () => void }) {
  React.useEffect(() => {
    const timer = window.setTimeout(onClose, 3200);
    return () => window.clearTimeout(timer);
  }, [onClose]);
  return <div className={`toast ${toast.tone}`}>{toast.text}</div>;
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label>
      {label}
      <input value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function RecordSummary({ record }: { record: unknown }) {
  if (!record) return <p className="emptyText">暂无记录</p>;
  return <pre className="recordSummary">{JSON.stringify(record, null, 2)}</pre>;
}

function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="emptyState">
      <strong>{title || "暂无记录"}</strong>
      <p>{description || "当前没有可展示的数据；调整筛选条件或完成配置后再查看。"}</p>
      {action ? <div className="emptyAction">{action}</div> : null}
    </div>
  );
}

function renderCell(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string") {
    const tone = toneFor(value);
    return tone ? <span className={`status ${tone}`} title={value}>{statusLabel[value] || value}</span> : <span>{value}</span>;
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return <code>{JSON.stringify(value)}</code>;
  return String(value);
}

function fieldLabel(field: string) {
  return fieldLabels[field] || field;
}

function tableEmptyState(title: string): EmptyStateProps {
  if (title.includes("审计")) {
    return { title: "暂无审计记录", description: "当前筛选范围内还没有审计事件；执行管理操作或调整组织、店铺筛选后再查看。" };
  }
  if (title.includes("任务")) {
    return { title: "暂无任务", description: "当前没有异步任务需要处理；失败或待重试任务出现后会在这里显示。" };
  }
  if (title.includes("组件检查")) {
    return { title: "暂无检查项", description: "当前健康接口没有返回组件检查明细；请刷新系统健康数据后再查看。" };
  }
  return { title: `暂无${title}`, description: "当前没有可展示的数据；调整筛选条件或完成配置后再查看。" };
}

function arrayFrom(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.filter((item): item is JsonRecord => Boolean(item) && typeof item === "object") : [];
}

function readRecord(source: unknown, key: string): JsonRecord {
  if (!source || typeof source !== "object") return {};
  const value = (source as JsonRecord)[key];
  return value && typeof value === "object" ? value as JsonRecord : {};
}

function formatUserBadge(workspace: Workspace, user: JsonRecord) {
  const displayName = safeText(user.display_name) || safeText(user.name);
  if (displayName) return displayName;
  if (workspace === "customer") return safeText(user.email) || "已登录";
  return firstText(user.role, user.roles) || "系统账号";
}

export function buildSystemUserSummary(user: JsonRecord): SummaryItem[] {
  const items: SummaryItem[] = [];
  const displayName = safeText(user.display_name) || safeText(user.name);
  const roles = stringList(user.roles || user.role);
  const status = safeText(user.status);
  const capabilitiesCount = countCapabilities(user.capabilities);
  const lastLoginAt = safeText(user.last_login_at);

  if (displayName) items.push({ label: "名称", value: displayName });
  if (roles.length) items.push({ label: "角色", value: roles.join(", ") });
  if (status) items.push({ label: "状态", value: status });
  if (capabilitiesCount > 0) items.push({ label: "能力", value: `${capabilitiesCount} 项` });
  if (lastLoginAt) items.push({ label: "最近登录", value: lastLoginAt });

  return items;
}

function safeText(value: unknown) {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function firstText(...values: unknown[]) {
  for (const value of values) {
    const list = stringList(value);
    if (list.length) return list[0];
    const text = safeText(value);
    if (text) return text;
  }
  return "";
}

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => safeText(item)).filter(Boolean);
  const text = safeText(value);
  return text ? [text] : [];
}

function countCapabilities(value: unknown) {
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === "object") return Object.keys(value).length;
  return 0;
}

function firstId(value: unknown, fallback: string) {
  const first = arrayFrom(value)[0];
  return String(first?.id || first?.organization_id || first?.store_id || fallback);
}

function toneFor(value: string): "ok" | "warn" | "bad" | "info" | "" {
  return statusTone[value.toLowerCase()] || "";
}

function buildQuery(filters: Record<string, string>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value && key !== "trace_id") params.set(key, value);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

createRoot(document.getElementById("root")!).render(<App />);
