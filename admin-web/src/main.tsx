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
  PackagePlus,
  PlayCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  Store,
  Users
} from "lucide-react";
import {
  authMePathForWorkspace,
  detectWorkspaceFromLocation,
  resolveAdminRoute,
  shouldRefreshAuth,
  type Workspace
} from "./routing";
import "./styles.css";

type JsonRecord = Record<string, unknown>;
type CustomerTab = "overview" | "products" | "knowledge" | "audit";
type SystemTab = "home" | "tenants" | "traces" | "tasks" | "audit" | "health";
type ToastState = { tone: "success" | "error" | "info"; text: string } | null;
type SystemFiltersState = { organization_id: string; store_id: string; status: string; trace_id: string };

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

const nowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");

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
  const [path, setPath] = React.useState(() => window.location.pathname || "/");
  const [customerTab, setCustomerTab] = React.useState<CustomerTab>("overview");
  const [systemTab, setSystemTab] = React.useState<SystemTab>("home");
  const [customerSession, setCustomerSession] = React.useState<JsonRecord | null>(null);
  const [systemSession, setSystemSession] = React.useState<JsonRecord | null>(null);
  const [authChecked, setAuthChecked] = React.useState(false);
  const [toast, setToast] = React.useState<ToastState>(null);

  const customerAuthed = Boolean(customerSession);
  const systemAuthed = Boolean(systemSession);
  const activeAuthed = workspace === "customer" ? customerAuthed : systemAuthed;
  const route = resolveAdminRoute({ workspace, pathname: path, authed: activeAuthed });
  const checkingProtectedRoute = shouldRefreshAuth(workspace, path) && !authChecked;

  function navigate(nextPath: string, replace = false) {
    if (window.location.pathname !== nextPath) {
      const method = replace ? "replaceState" : "pushState";
      window.history[method](null, "", nextPath);
    }
    setPath(nextPath);
  }

  async function refreshSession(target: Workspace) {
    const me = await requestJson(authMePathForWorkspace(target));
    if (target === "customer") setCustomerSession(me);
    if (target === "system") setSystemSession(me);
  }

  async function logout(target: Workspace) {
    try {
      await requestJson(target === "customer" ? "/v1/admin/auth/logout" : "/v1/system-admin/auth/logout", { method: "POST" });
    } catch {
      // Session may already be gone; local state still needs clearing.
    }
    if (target === "customer") setCustomerSession(null);
    if (target === "system") setSystemSession(null);
    setToast({ tone: "info", text: "已退出当前后台" });
  }

  React.useEffect(() => {
    const handlePopState = () => setPath(window.location.pathname || "/");
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  React.useEffect(() => {
    if (!shouldRefreshAuth(workspace, path)) {
      setAuthChecked(true);
      return;
    }

    let cancelled = false;
    setAuthChecked(false);
    void refreshSession(workspace)
      .catch(() => {
        if (workspace === "customer") setCustomerSession(null);
        if (workspace === "system") setSystemSession(null);
      })
      .finally(() => {
        if (!cancelled) setAuthChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [workspace, path]);

  React.useEffect(() => {
    if (!checkingProtectedRoute && route.redirectTo) navigate(route.redirectTo, true);
  }, [checkingProtectedRoute, route.redirectTo]);

  if (workspace === "customer") {
    if (checkingProtectedRoute) {
      return (
        <main className="publicShell">
          <PublicHeader onNavigate={navigate} />
          <section className="authCheck">
            <Loader2 size={18} className="spin" />
            <span>正在校验客户后台会话</span>
          </section>
        </main>
      );
    }

    if (route.surface === "customer-landing") {
      return (
        <>
          <CustomerLanding onNavigate={navigate} />
          {toast ? <Toast toast={toast} onClose={() => setToast(null)} /> : null}
        </>
      );
    }

    if (route.surface === "customer-login") {
      return (
        <>
          <CustomerLoginPage
            onNavigate={navigate}
            onLoggedIn={(session) => {
              setCustomerSession(session);
              setAuthChecked(true);
              navigate("/admin");
            }}
            setToast={setToast}
          />
          {toast ? <Toast toast={toast} onClose={() => setToast(null)} /> : null}
        </>
      );
    }
  }

  return (
    <main className="appShell">
      <aside className="rail">
        <div className="brandMark">
          <ShieldCheck size={22} />
          <span>Ecommerce CS Agent</span>
        </div>
        <Navigation
          workspace={workspace}
          customerTab={customerTab}
          systemTab={systemTab}
          setCustomerTab={setCustomerTab}
          setSystemTab={setSystemTab}
        />
      </aside>

      <section className="mainPane">
        <TopBar
          workspace={workspace}
          session={workspace === "customer" ? customerSession : systemSession}
          onRefresh={() => refreshSession(workspace).then(() => setToast({ tone: "success", text: "会话已刷新" })).catch((error) => setToast({ tone: "error", text: error.message }))}
          onLogout={() => logout(workspace)}
        />

        {workspace === "customer" ? (
          customerAuthed ? (
            <CustomerWorkspace
              session={customerSession!}
              activeTab={customerTab}
              setActiveTab={setCustomerTab}
              setToast={setToast}
            />
          ) : (
            <LoginPanel key="customer-login" target="customer" onLoggedIn={(session) => setCustomerSession(session)} setToast={setToast} />
          )
        ) : route.surface === "system-admin" ? (
          <SystemWorkspace
            session={systemSession!}
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

function CustomerLanding({ onNavigate }: { onNavigate: (path: string) => void }) {
  return (
    <main className="publicShell">
      <PublicHeader onNavigate={onNavigate} />
      <section className="landingHero">
        <div className="heroCopy">
          <p className="publicEyebrow">CUSTOMER SERVICE AI AGENT</p>
          <h1>把商品资料、审核知识和回复规则放进一个客户后台</h1>
          <p>
            Ecommerce CS Agent 为外部客服系统提供独立的 AI 回复决策服务。客户团队在这里维护长期资料、规则和动作能力，前台系统继续负责接待和真实发送。
          </p>
          <div className="heroActions">
            <button className="publicPrimaryButton" onClick={() => onNavigate("/login")}>
              进入客户登录 <ArrowRight size={17} />
            </button>
            <button className="publicSecondaryButton" onClick={() => document.getElementById("capabilities")?.scrollIntoView({ behavior: "smooth" })}>
              查看能力模块
            </button>
          </div>
        </div>
        <div className="productPreview" aria-label="客户后台产品预览">
          <div className="previewHeader">
            <span>客户后台概览</span>
            <strong>资料就绪度 84%</strong>
          </div>
          <div className="previewGrid">
            <div>
              <span>待审核知识</span>
              <strong>18</strong>
            </div>
            <div>
              <span>价格过期</span>
              <strong>6</strong>
            </div>
            <div>
              <span>规则版本</span>
              <strong>v12</strong>
            </div>
          </div>
          <div className="previewList">
            <p><CheckCircle2 size={15} /> 商品说明书已生成 Markdown 审稿稿件</p>
            <p><ClipboardList size={15} /> 高风险动作需要人工确认</p>
            <p><Search size={15} /> 每条回复决策可追踪到知识和规则来源</p>
          </div>
        </div>
      </section>

      <section className="publicBand" id="capabilities">
        <div className="publicSectionHeader">
          <p className="publicEyebrow">OPERATING LOOP</p>
          <h2>客户团队真正需要维护的四类能力</h2>
        </div>
        <div className="capabilityGrid">
          <CapabilityCard icon={<Boxes size={20} />} title="商品资料中心" text="维护商品、SKU、说明书、图片、视频和价格快照，让 Agent 有稳定的业务上下文。" />
          <CapabilityCard icon={<FileText size={20} />} title="知识审核队列" text="从资料和人工反馈中沉淀候选知识，审核、脱敏、改写后才进入可召回知识库。" />
          <CapabilityCard icon={<ListFilter size={20} />} title="规则与风险边界" text="配置店铺规则、自动回复边界、转人工条件和版本生效范围。" />
          <CapabilityCard icon={<Bot size={20} />} title="动作能力配置" text="定义可触发动作、参数 schema、风险级别和外部系统回调方式。" />
        </div>
      </section>

      <section className="trustBand">
        <div>
          <p className="publicEyebrow">TRUST BOUNDARY</p>
          <h2>独立系统，清晰边界</h2>
          <p>客户后台只服务本租户资料和规则维护，不读取平台运维域，也不依赖 ERP 或电商平台登录态。</p>
        </div>
        <div className="trustStats">
          <Metric label="公开页租户数据" value="0" tone="ok" />
          <Metric label="客户鉴权接口" value="/v1/admin/auth/me" tone="info" />
          <Metric label="跨站入口" value="无" tone="warn" />
        </div>
      </section>
    </main>
  );
}

function PublicHeader({ onNavigate }: { onNavigate: (path: string) => void }) {
  return (
    <header className="publicHeader">
      <button className="publicBrand" onClick={() => onNavigate("/")}>
        <ShieldCheck size={20} />
        <span>Ecommerce CS Agent</span>
      </button>
      <button className="publicLoginLink" onClick={() => onNavigate("/login")}>
        客户登录
      </button>
    </header>
  );
}

function CustomerLoginPage({ onNavigate, onLoggedIn, setToast }: {
  onNavigate: (path: string) => void;
  onLoggedIn: (session: JsonRecord) => void;
  setToast: (toast: ToastState) => void;
}) {
  return (
    <main className="publicShell loginPage">
      <PublicHeader onNavigate={onNavigate} />
      <section className="customerLoginLayout">
        <div className="loginIntro">
          <p className="publicEyebrow">CUSTOMER LOGIN</p>
          <h1>登录客户后台</h1>
          <p>继续维护组织、店铺、商品资料、知识审核、回复规则、动作能力和客户侧审计。</p>
        </div>
        <LoginPanel key="customer-login" target="customer" onLoggedIn={onLoggedIn} setToast={setToast} />
      </section>
    </main>
  );
}

function CapabilityCard({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <article className="capabilityCard">
      <span>{icon}</span>
      <h3>{title}</h3>
      <p>{text}</p>
    </article>
  );
}

function Navigation(props: {
  workspace: Workspace;
  customerTab: CustomerTab;
  systemTab: SystemTab;
  setCustomerTab: (tab: CustomerTab) => void;
  setSystemTab: (tab: SystemTab) => void;
}) {
  if (props.workspace === "customer") {
    return (
      <nav className="navList" aria-label="客户后台导航">
        <span className="navGroup">客户运营</span>
        {customerTabs.map((tab) => (
          <button key={tab.key} className={props.customerTab === tab.key ? "active" : ""} onClick={() => props.setCustomerTab(tab.key)}>
            {tab.icon}{tab.label}
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
            <button key={tab.key} className={props.systemTab === tab.key ? "active" : ""} onClick={() => props.setSystemTab(tab.key)}>
              {tab.icon}{tab.label}
            </button>
          ))}
        </React.Fragment>
      ))}
    </nav>
  );
}

function TopBar({ workspace, session, onRefresh, onLogout }: { workspace: Workspace; session: JsonRecord | null; onRefresh: () => void; onLogout: () => void }) {
  const user = readRecord(session, "user") || {};
  const title = workspace === "customer" ? "客户资料与知识运营" : "平台运维与发布治理";
  const subtitle = workspace === "customer" ? "组织、店铺、商品资料、知识审核和审计" : "租户开通、决策追踪、任务、健康和安全审计";
  return (
    <header className="topBar">
      <div>
        <p className="eyebrow">{workspace === "customer" ? "CUSTOMER ADMIN" : "SYSTEM ADMIN"}</p>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <div className="topActions">
        <button className="iconButton" onClick={onRefresh} title="刷新">
          <RefreshCw size={16} />刷新
        </button>
        {session ? (
          <>
            <span className="userBadge">{String(user.display_name || user.email || "已登录")}</span>
            <button className="iconButton" onClick={onLogout} title="退出登录">
              <LogOut size={16} />退出
            </button>
          </>
        ) : null}
      </div>
    </header>
  );
}

function LoginPanel({ target, onLoggedIn, setToast }: { target: Workspace; onLoggedIn: (session: JsonRecord) => void; setToast: (toast: ToastState) => void }) {
  const [email, setEmail] = React.useState(target === "customer" ? "admin@example.test" : "system-admin@example.test");
  const [password, setPassword] = React.useState("");
  const [organizationId, setOrganizationId] = React.useState("org-001");
  const [loading, setLoading] = React.useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      const path = target === "customer" ? "/v1/admin/auth/login" : "/v1/system-admin/auth/login";
      const body = target === "customer" ? { email, password, organization_id: organizationId } : { email, password };
      await requestJson(path, { method: "POST", body: JSON.stringify(body) });
      const session = await requestJson(target === "customer" ? "/v1/admin/auth/me" : "/v1/system-admin/auth/me");
      onLoggedIn(session);
      setToast({ tone: "success", text: "登录成功" });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
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
          <input value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" />
        </label>
        <label>
          密码
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" />
        </label>
        {target === "customer" ? (
          <label>
            组织 ID
            <input value={organizationId} onChange={(event) => setOrganizationId(event.target.value)} />
          </label>
        ) : null}
        <button className="primaryButton" type="submit" disabled={loading}>
          {loading ? <Loader2 size={16} className="spin" /> : <ShieldCheck size={16} />}
          登录
        </button>
      </form>
    </section>
  );
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
        <ListPanel title="组织" rows={arrayFrom(session.organizations)} fields={["id", "name", "status"]} />
        <ListPanel title="店铺" rows={arrayFrom(session.stores)} fields={["id", "platform", "status"]} />
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
        <RecordSummary record={readRecord(session, "user")} />
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
        <ListPanel title="上线阻断队列" rows={arrayFrom(data.readiness)} fields={["organization_id", "store_id", "status", "reason"]} />
        <ListPanel title="最近消息决策" rows={arrayFrom(data.traces)} fields={["decision_id", "status", "risk_level", "created_at"]} />
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
      <DataTable title="消息决策" rows={filtered} fields={["decision_id", "organization_id", "store_id", "status", "risk_level", "created_at"]} onSelect={setSelected} />
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

function DataTable({ title, rows, fields, onSelect, action }: {
  title: string;
  rows: JsonRecord[];
  fields: string[];
  onSelect?: (record: JsonRecord) => void;
  action?: (record: JsonRecord) => React.ReactNode;
}) {
  return (
    <section className="tablePanel">
      <h3>{title}</h3>
      {rows.length ? (
        <div className="tableWrap">
          <table>
            <thead>
              <tr>{fields.map((field) => <th key={field}>{field}</th>)}{action ? <th>操作</th> : null}</tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={String(row.id || row.decision_id || row.task_id || index)} onClick={() => onSelect?.(row)}>
                  {fields.map((field) => <td key={field}>{renderCell(row[field])}</td>)}
                  {action ? <td onClick={(event) => event.stopPropagation()}>{action(row)}</td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <EmptyState />}
    </section>
  );
}

function AuditTable({ title, rows, onSelect }: { title: string; rows: JsonRecord[]; onSelect: (record: JsonRecord) => void }) {
  return <DataTable title={title} rows={rows} fields={["audit_log_id", "action", "object_type", "reason", "created_at"]} onSelect={onSelect} />;
}

function ListPanel({ title, rows, fields }: { title: string; rows: JsonRecord[]; fields: string[] }) {
  return <DataTable title={title} rows={rows} fields={fields} />;
}

function ContextPanel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <aside className="contextPanel">
      <h2>{title}</h2>
      {children}
    </aside>
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
