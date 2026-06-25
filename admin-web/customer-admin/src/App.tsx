import React from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Bot,
  Boxes,
  CheckCircle2,
  ClipboardList,
  FileText,
  Loader2,
  MessageSquareText,
  PackagePlus,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Store,
  UploadCloud
} from "lucide-react";
import { Graph } from "@antv/x6";
import { requestJson } from "../../shared/api";
import {
  AdminFrame,
  AuditTable,
  DataTable,
  Drawer,
  Field,
  ListPanel,
  LoginPanelBase,
  Metric,
  Navigation,
  RecordSummary,
  SectionHeader,
  TopBar,
  useCloseOnEscape
} from "../../shared/components";
import { arrayFrom, firstId, readRecord } from "../../shared/data";
import type { JsonRecord, NavItem, Page, ToastState } from "../../shared/types";

type CustomerTab = "overview" | "messages" | "products" | "knowledge" | "audit";

const customerTabs: Array<NavItem<CustomerTab>> = [
  { key: "overview", label: "首页概览", icon: <Activity size={17} /> },
  { key: "messages", label: "消息历史", icon: <MessageSquareText size={17} /> },
  { key: "products", label: "商品资料", icon: <Boxes size={17} /> },
  { key: "knowledge", label: "知识审核", icon: <FileText size={17} /> },
  { key: "audit", label: "审计查询", icon: <ClipboardList size={17} /> }
];

type CustomerTrace = JsonRecord & {
  decision_id?: string;
  customer_message?: string;
  ai_reply?: string;
  human_reply?: string;
  action?: string;
  status?: string;
  risk_level?: string;
  source?: string;
  trace?: JsonRecord;
};

function normalizePath() {
  if (typeof window === "undefined") return "/";
  const path = window.location.pathname || "/";
  return path.endsWith("/") && path !== "/" ? path.slice(0, -1) : path;
}

async function submitCustomerLogin(email: string, password: string) {
  await requestJson("/v1/admin/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
  return requestJson("/v1/admin/auth/me");
}

function customerLoginErrorFromLocation() {
  if (typeof window === "undefined") return null;
  const error = new URLSearchParams(window.location.search).get("error");
  const errorMessages: Record<string, string> = {
    oidc_unbound_account: "OIDC 未绑定账号，请先使用邮箱密码登录或联系管理员绑定。",
    oidc_disabled: "OIDC 配置未启用，请使用邮箱密码登录。",
    oidc_misconfigured: "OIDC 配置未启用，请使用邮箱密码登录。",
    oidc_state_pkce_failed: "OIDC 回调 state/PKCE 校验失败，请重新发起登录。",
    oidc_exchange_failed: "OIDC 登录失败，请稍后重试。"
  };
  return error ? errorMessages[error] || "OIDC 登录失败，请稍后重试。" : null;
}

export function App() {
  const [path, setPath] = React.useState(() => normalizePath());
  const [customerTab, setCustomerTab] = React.useState<CustomerTab>("overview");
  const [customerSession, setCustomerSession] = React.useState<JsonRecord | null>(null);
  const [toast, setToast] = React.useState<ToastState>(null);

  React.useEffect(() => {
    const syncPath = () => setPath(normalizePath());
    window.addEventListener("popstate", syncPath);
    return () => window.removeEventListener("popstate", syncPath);
  }, []);

  React.useEffect(() => {
    void refreshSession().catch(() => undefined);
  }, []);

  function navigate(nextPath: string) {
    window.history.pushState({}, "", nextPath);
    setPath(normalizePath());
  }

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

  if (path === "/login") {
    return (
      <main className="customerLoginShell">
        <button className="textButton" onClick={() => navigate("/")}>
          <ArrowRight size={15} className="flipIcon" />返回首页
        </button>
        <LoginPanelBase
          title="客户后台登录"
          initialError={customerLoginErrorFromLocation()}
          onSubmit={submitCustomerLogin}
          onLoggedIn={(session) => {
            setCustomerSession(session);
            navigate("/admin");
          }}
          secondaryAction={{
            label: "使用 Fcihome Account 登录",
            onClick: () => window.location.assign("/v1/admin/auth/oidc/start"),
            icon: <ShieldCheck size={16} />
          }}
          setToast={setToast}
        />
        {toast ? <div className={`toast ${toast.tone}`}>{toast.text}</div> : null}
      </main>
    );
  }

  if (path === "/launch") {
    return (
      <LaunchExchange
        onExchanged={(session) => {
          setCustomerSession(session);
          setCustomerTab("messages");
          navigate("/admin");
        }}
        setToast={setToast}
      />
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
        clearToast={() => setToast(null)}
      />
    );
  }

  return <CustomerLanding customerAuthed={Boolean(customerSession)} navigate={navigate} />;
}

function CustomerLanding({ customerAuthed, navigate }: { customerAuthed: boolean; navigate: (path: string) => void }) {
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
              {index < flowSteps.length - 1 ? <ArrowRight className="flowArrow" size={18} aria-hidden="true" /> : null}
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
  toast,
  clearToast
}: {
  customerSession: JsonRecord | null;
  customerTab: CustomerTab;
  setCustomerTab: (tab: CustomerTab) => void;
  refreshSession: () => Promise<void>;
  logout: () => Promise<void>;
  setToast: (toast: ToastState) => void;
  toast: ToastState;
  clearToast: () => void;
}) {
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const isAuthenticated = Boolean(customerSession);
  const closeNav = React.useCallback(() => setMobileNavOpen(false), []);
  useCloseOnEscape(mobileNavOpen, closeNav);

  return (
    <AdminFrame
      isAuthenticated={isAuthenticated}
      mobileNavOpen={mobileNavOpen}
      brand="AI 客服客户后台"
      navigation={
        <Navigation
          items={customerTabs}
          activeTab={customerTab}
          onChange={setCustomerTab}
          ariaLabel="客户后台导航"
          defaultGroup="客户运营"
          onNavigate={closeNav}
        />
      }
      topBar={
        <TopBar
          eyebrow="CUSTOMER ADMIN"
          title="客户资料与知识运营"
          subtitle="店铺、消息历史、商品资料、知识审核和审计"
          showNavButton={isAuthenticated}
          navOpen={mobileNavOpen}
          onToggleNav={() => setMobileNavOpen((open) => !open)}
          onLogout={() => void logout()}
        />
      }
      toast={toast}
      onCloseNav={closeNav}
      onCloseToast={clearToast}
    >
      {customerSession ? (
        <CustomerWorkspace
          session={customerSession}
          activeTab={customerTab}
          setActiveTab={setCustomerTab}
          setToast={setToast}
        />
      ) : (
        <LoginPanelBase
          title="客户后台登录"
          onSubmit={submitCustomerLogin}
          onLoggedIn={() => void refreshSession()}
          setToast={setToast}
        />
      )}
    </AdminFrame>
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
  const organizationId = activeOrg;
  const [storeId, setStoreId] = React.useState(activeStore);
  const [data, setData] = React.useState<Record<string, unknown>>({});
  const [loading, setLoading] = React.useState(false);
  const [selected, setSelected] = React.useState<JsonRecord | null>(null);

  const stores = arrayFrom(session.stores);

  async function refresh() {
    setLoading(true);
    try {
      const [users, audit, products] = await Promise.all([
        requestJson<Page>(`/v1/admin/users?organization_id=${encodeURIComponent(organizationId)}`),
        requestJson<Page>(`/v1/admin/audit-logs?organization_id=${encodeURIComponent(organizationId)}&store_id=${encodeURIComponent(storeId)}`),
        requestJson<Page>(`/v1/product-content/products?store_id=${encodeURIComponent(storeId)}`)
      ]);
      setData({ users: users.items || [], audit: audit.items || [], products: products.items || [] });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    void refresh();
  }, [storeId]);

  return (
    <div className="workGrid singlePane">
      <section className="contentPane">
        <ContextStrip
          storeId={storeId}
          stores={stores}
          setStoreId={setStoreId}
          loading={loading}
        />
        {activeTab === "overview" ? (
          <CustomerOverview session={session} data={data} setActiveTab={setActiveTab} />
        ) : null}
        {activeTab === "messages" ? (
          <MessageHistory storeId={storeId} setToast={setToast} setSelected={setSelected} />
        ) : null}
        {activeTab === "products" ? (
          <ProductContent storeId={storeId} setToast={setToast} setSelected={setSelected} onChanged={refresh} />
        ) : null}
        {activeTab === "knowledge" ? (
          <KnowledgeReview storeId={storeId} setToast={setToast} />
        ) : null}
        {activeTab === "audit" ? (
          <AuditTable title="客户后台审计" rows={arrayFrom(data.audit)} onSelect={setSelected} />
        ) : null}
      </section>
      {selected ? <Drawer title="记录详情" record={selected} onClose={() => setSelected(null)} /> : null}
    </div>
  );
}

function CustomerOverview({ session, data, setActiveTab }: { session: JsonRecord; data: Record<string, unknown>; setActiveTab: (tab: CustomerTab) => void }) {
  return (
    <>
      <SectionHeader
        label="CUSTOMER"
        title="首页概览"
        action={
          <div className="buttonRow">
            <button onClick={() => setActiveTab("messages")}><MessageSquareText size={16} />消息历史</button>
            <button onClick={() => setActiveTab("products")}><PackagePlus size={16} />维护商品</button>
          </div>
        }
      />
      <div className="metricGrid">
        <Metric label="可访问店铺" value={String(arrayFrom(session.stores).length)} tone="ok" />
        <Metric label="商品资料" value={String(arrayFrom(data.products).length)} tone="ok" />
        <Metric label="成员记录" value={String(arrayFrom(data.users).length)} tone="info" />
        <Metric label="审计记录" value={String(arrayFrom(data.audit).length)} tone="warn" />
      </div>
      <div className="twoColumns">
        <ListPanel title="店铺" rows={arrayFrom(session.stores)} fields={["id", "platform", "status"]} emptyState={{ title: "暂无可访问店铺", description: "当前账号还没有可访问店铺；完成店铺授权后会显示在这里。" }} />
        <ListPanel title="商品资料" rows={arrayFrom(data.products)} fields={["title", "external_product_id", "status", "health_status"]} emptyState={{ title: "暂无商品资料", description: "上传商品说明书并确认 AI 抽取字段后，商品会显示在这里。" }} />
      </div>
    </>
  );
}

function LaunchExchange({ onExchanged, setToast }: { onExchanged: (session: JsonRecord) => void; setToast: (toast: ToastState) => void }) {
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token") || "";
    if (!token) {
      setError("启动票据缺失，请从 open_erp_agent 客户端重新打开。");
      return;
    }
    requestJson("/v1/admin/auth/launch/exchange", {
      method: "POST",
      body: JSON.stringify({ launch_token: token })
    })
      .then((session) => {
        setToast({ tone: "success", text: "已进入对应店铺客户后台" });
        onExchanged(session);
      })
      .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  }, [onExchanged, setToast]);

  return (
    <main className="customerLoginShell">
      <section className="loginPanel">
        <Bot size={24} />
        <h2>正在进入 AI 客服客户系统</h2>
        {error ? (
          <>
            <div className="loginError" role="alert"><AlertTriangle size={16} /><span>{error}</span></div>
            <button className="primaryButton" onClick={() => window.location.assign("/login")}>返回登录页</button>
          </>
        ) : (
          <p className="inlineStatus"><Loader2 size={16} className="spin" />正在校验一次性启动票据</p>
        )}
      </section>
    </main>
  );
}

function MessageHistory({ storeId, setToast, setSelected }: {
  storeId: string;
  setToast: (toast: ToastState) => void;
  setSelected: (record: JsonRecord) => void;
}) {
  const [rows, setRows] = React.useState<CustomerTrace[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [question, setQuestion] = React.useState("");
  const [selectedTrace, setSelectedTrace] = React.useState<CustomerTrace | null>(null);

  async function load(source = "") {
    setLoading(true);
    try {
      const query = new URLSearchParams({ store_id: storeId });
      if (source) query.set("source", source);
      const response = await requestJson<Page>(`/v1/admin/message-traces?${query.toString()}`);
      setRows(arrayFrom(response.items) as CustomerTrace[]);
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    void load();
  }, [storeId]);

  async function simulate(event: React.FormEvent) {
    event.preventDefault();
    const content = question.trim();
    if (!content) {
      setToast({ tone: "error", text: "请输入模拟客户问题" });
      return;
    }
    setLoading(true);
    try {
      const response = await requestJson<JsonRecord>("/v1/admin/message-simulations", {
        method: "POST",
        body: JSON.stringify({ store_id: storeId, platform: "pdd", message: { content } })
      });
      const decision = readRecord(response, "decision");
      setQuestion("");
      setToast({ tone: "success", text: "模拟决策已完成" });
      await load();
      setSelectedTrace({
        decision_id: String(decision.decision_id || ""),
        source: "simulation",
        customer_message: content,
        ai_reply: firstCandidateText(decision),
        action: String(decision.action || ""),
        status: String(decision.decision_status || ""),
        risk_level: String(decision.risk_level || ""),
        trace: readRecord(decision, "trace")
      });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <SectionHeader label="MESSAGES" title="消息历史" action={<button onClick={() => void load()}><Search size={16} />刷新</button>} />
      <form className="operationPanel messageSimulator" onSubmit={simulate}>
        <label>
          模拟客户咨询
          <textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="例如：这个商品有哪些尺寸？" />
        </label>
        <div className="buttonRow end">
          <button className="primaryButton" disabled={loading}>
            {loading ? <Loader2 size={16} className="spin" /> : <Bot size={16} />}
            模拟决策
          </button>
        </div>
      </form>
      <DataTable
        title="客服会话消息"
        rows={rows}
        fields={["decision_id", "source", "customer_message", "ai_reply", "human_reply", "action", "status", "risk_level"]}
        onSelect={(row) => setSelectedTrace(row as CustomerTrace)}
        action={(row) => <button onClick={() => setSelectedTrace(row as CustomerTrace)}><Search size={15} />决策路径</button>}
        emptyState={{
          title: loading ? "正在读取消息历史" : "暂无消息历史",
          description: loading ? "消息历史正在读取，请稍候。" : "收到客户咨询或完成模拟咨询后，AI 决策记录会显示在这里。"
        }}
      />
      {selectedTrace ? (
        <MessageTraceDrawer
          trace={selectedTrace}
          onClose={() => setSelectedTrace(null)}
          onRaw={() => setSelected(selectedTrace)}
        />
      ) : null}
    </>
  );
}

function MessageTraceDrawer({ trace, onClose, onRaw }: { trace: CustomerTrace; onClose: () => void; onRaw: () => void }) {
  return (
    <aside className="drawer messageTraceDrawer">
      <div className="drawerHeader">
        <h2>决策路径</h2>
        <button onClick={onClose}>关闭</button>
      </div>
      <div className="traceSummary">
        <Metric label="动作" value={String(trace.action || "-")} tone="info" />
        <Metric label="状态" value={String(trace.status || "-")} tone="ok" />
        <Metric label="风险" value={String(trace.risk_level || "-")} tone="warn" />
      </div>
      <section className="traceTextBlock">
        <h3>客户消息</h3>
        <p>{String(trace.customer_message || "-")}</p>
        <h3>AI 回复</h3>
        <p>{String(trace.ai_reply || "当前决策未生成可直接发送回复。")}</p>
        {trace.human_reply ? (
          <>
            <h3>人工回复</h3>
            <p>{String(trace.human_reply)}</p>
          </>
        ) : null}
      </section>
      <DecisionFlowGraph trace={trace.trace} status={String(trace.status || trace.action || "")} />
      <button onClick={onRaw}>查看原始记录</button>
    </aside>
  );
}

function DecisionFlowGraph({ trace, status }: { trace: unknown; status: string }) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    if (!containerRef.current) return undefined;
    const graph = new Graph({
      container: containerRef.current,
      width: containerRef.current.clientWidth || 520,
      height: 320,
      interacting: false,
      panning: false,
      mousewheel: false,
      background: { color: "#ffffff" }
    });
    const steps = ["接收消息", "字段映射", "上下文检查", "商品/知识/规则", "回复生成", "风险闸门", "输出动作", "反馈/记录"];
    const runtimeSteps = readTraceSteps(trace);
    const blocked = status === "waiting_context" || status === "handoff";
    const nodes = steps.map((label, index) => {
      const runtime = runtimeSteps[index];
      const fill = runtime?.status === "failed" ? "#fee2e2" : blocked && index >= 2 ? "#fff7ed" : "#eef2ff";
      return graph.addNode({
        id: `node-${index}`,
        x: 26 + (index % 2) * 230,
        y: 24 + Math.floor(index / 2) * 70,
        width: 170,
        height: 42,
        label,
        attrs: {
          body: { rx: 6, ry: 6, stroke: "#94a3b8", fill },
          label: { fill: "#1f2937", fontSize: 12, fontWeight: 600 }
        }
      });
    });
    nodes.slice(0, -1).forEach((node, index) => {
      graph.addEdge({
        source: node,
        target: nodes[index + 1],
        attrs: { line: { stroke: "#64748b", strokeWidth: 1.4, targetMarker: "block" } },
        router: { name: "manhattan" }
      });
    });
    graph.centerContent();
    return () => graph.dispose();
  }, [trace, status]);

  return <div className="decisionGraph" ref={containerRef} aria-label="AI 客服决策流程图" />;
}

function ProductContent({ storeId, setToast, setSelected, onChanged }: {
  storeId: string;
  setToast: (toast: ToastState) => void;
  setSelected: (record: JsonRecord) => void;
  onChanged: () => Promise<void>;
}) {
  const [products, setProducts] = React.useState<JsonRecord[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [uploadOpen, setUploadOpen] = React.useState(false);

  async function loadProducts() {
    setLoading(true);
    try {
      const response = await requestJson<Page>(`/v1/product-content/products?store_id=${encodeURIComponent(storeId)}`);
      setProducts(arrayFrom(response.items));
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoading(false);
    }
  }

  React.useEffect(() => {
    void loadProducts();
  }, [storeId]);

  async function handleImported(record: JsonRecord) {
    setSelected(record);
    setToast({ tone: "success", text: "商品已保存" });
    setUploadOpen(false);
    await loadProducts();
    await onChanged();
  }

  return (
    <>
      <SectionHeader label="PRODUCT CONTENT" title="商品资料" action={<button className="primaryButton" onClick={() => setUploadOpen(true)}><UploadCloud size={16} />上传商品</button>} />
      <DataTable
        title="商品列表"
        rows={products}
        fields={["title", "external_product_id", "store_id", "status", "health_status", "updated_at"]}
        onSelect={setSelected}
        action={(row) => <button onClick={() => setSelected(row)}><Search size={15} />详情</button>}
        emptyState={{
          title: loading ? "正在加载商品资料" : "暂无商品资料",
          description: loading ? "商品列表正在读取，请稍候。" : "点击右上角上传商品，AI 会先抽取字段，确认后再写入正式商品资料。"
        }}
      />
      {uploadOpen ? <ProductUploadModal storeId={storeId} onClose={() => setUploadOpen(false)} onImported={handleImported} setToast={setToast} /> : null}
    </>
  );
}

function ProductUploadModal({ storeId, onClose, onImported, setToast }: {
  storeId: string;
  onClose: () => void;
  onImported: (record: JsonRecord) => Promise<void>;
  setToast: (toast: ToastState) => void;
}) {
  const [file, setFile] = React.useState<File | null>(null);
  const [draft, setDraft] = React.useState<JsonRecord | null>(null);
  const [form, setForm] = React.useState({ external_product_id: "", title: "", attributes: "{}" });
  const [loading, setLoading] = React.useState(false);

  async function analyze(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setToast({ tone: "error", text: "请选择商品资料文件" });
      return;
    }
    setLoading(true);
    try {
      const response = await requestJson("/v1/product-content/product-import-drafts", {
        method: "POST",
        body: JSON.stringify({
          store_id: storeId,
          file_name: file.name,
          mime_type: file.type || "application/octet-stream",
          content_base64: await fileToBase64(file),
          idempotency_key: `admin-web-upload-${Date.now()}-${file.name}`
        })
      });
      const draftProduct = readRecord(response, "draft_product");
      setDraft(response);
      setForm({
        external_product_id: String(draftProduct.external_product_id || ""),
        title: String(draftProduct.title || ""),
        attributes: JSON.stringify(readRecord(draftProduct, "attributes"), null, 2)
      });
      setToast({ tone: "success", text: "AI 已生成商品草稿" });
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoading(false);
    }
  }

  async function confirm() {
    if (!draft?.draft_id) return;
    setLoading(true);
    try {
      const attributes = parseAttributes(form.attributes);
      const response = await requestJson(`/v1/product-content/product-import-drafts/${draft.draft_id}/confirm`, {
        method: "POST",
        body: JSON.stringify({
          idempotency_key: `admin-web-confirm-${draft.draft_id}`,
          draft_product: {
            external_product_id: form.external_product_id.trim(),
            title: form.title.trim(),
            status: "active",
            attributes
          }
        })
      });
      await onImported(response);
    } catch (error) {
      setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modalBackdrop" role="dialog" aria-modal="true">
      <form className="modal uploadModal" onSubmit={analyze}>
        <div className="modalHeader">
          <div>
            <p className="eyebrow">PRODUCT UPLOAD</p>
            <h2>上传商品</h2>
          </div>
          <button type="button" onClick={onClose}>关闭</button>
        </div>
        <label>
          商品资料文件
          <input type="file" onChange={(event) => setFile(event.target.files?.[0] || null)} />
        </label>
        {!draft ? (
          <button className="primaryButton" type="submit" disabled={loading}>
            {loading ? <Loader2 size={16} className="spin" /> : <UploadCloud size={16} />}
            上传并分析
          </button>
        ) : (
          <div className="draftFields">
            <Field label="外部商品 ID" value={form.external_product_id} onChange={(value) => setForm({ ...form, external_product_id: value })} />
            <Field label="商品名称" value={form.title} onChange={(value) => setForm({ ...form, title: value })} />
            <label>
              抽取属性 JSON
              <textarea value={form.attributes} onChange={(event) => setForm({ ...form, attributes: event.target.value })} />
            </label>
            <div className="buttonRow end">
              <button type="button" onClick={onClose}>取消</button>
              <button className="primaryButton" type="button" onClick={confirm} disabled={loading}>
                {loading ? <Loader2 size={16} className="spin" /> : <CheckCircle2 size={16} />}
                确认保存
              </button>
            </div>
          </div>
        )}
      </form>
    </div>
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

function ContextStrip({ storeId, stores, setStoreId, loading }: {
  storeId: string;
  stores: JsonRecord[];
  setStoreId: (value: string) => void;
  loading: boolean;
}) {
  return (
    <section className="filterBar">
      <Store size={17} />
      <select value={storeId} onChange={(event) => setStoreId(event.target.value)}>
        {stores.map((item) => <option key={String(item.id || item.store_id)} value={String(item.id || item.store_id)}>{String(item.name || item.id || item.store_id)}</option>)}
      </select>
      {loading ? <span className="inlineStatus"><Loader2 size={16} className="spin" />读取中</span> : null}
    </section>
  );
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("文件读取失败"));
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",").pop() || "" : result);
    };
    reader.readAsDataURL(file);
  });
}

function parseAttributes(value: string): JsonRecord {
  try {
    const parsed = JSON.parse(value || "{}");
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as JsonRecord : {};
  } catch {
    throw new Error("抽取属性 JSON 格式不正确");
  }
}

function firstCandidateText(decision: JsonRecord): string {
  const candidates = Array.isArray(decision.candidates) ? decision.candidates : [];
  const first = candidates[0];
  if (first && typeof first === "object" && "reply_text" in first) {
    return String((first as JsonRecord).reply_text || "");
  }
  return "";
}

function readTraceSteps(trace: unknown): JsonRecord[] {
  if (!trace || typeof trace !== "object") return [];
  const steps = (trace as JsonRecord).steps;
  return Array.isArray(steps) ? (steps.filter((item) => item && typeof item === "object") as JsonRecord[]) : [];
}
