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
  Store,
  UploadCloud
} from "lucide-react";
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
import { DecisionTraceReplay } from "../../shared/trace-replay";
import { presentDecisionBadges, presentDecisionTrace, presentServiceStage } from "../../shared/trace-presentation";
import type { JsonRecord, NavItem, Page, ToastState } from "../../shared/types";
import { SimulationComposer } from "./SimulationComposer";
import { scrollBehaviorForReducedMotion } from "./landing-motion";
import {
  buildCanonicalSimulationTrace,
  isCurrentOperation,
  requireReloadedSimulation,
  type OperationToken
} from "./simulation-workflow";

type CustomerTab = "overview" | "messages" | "products" | "knowledge" | "audit";

const customerTabs: Array<NavItem<CustomerTab>> = [
  { key: "overview", label: "首页概览", icon: <Activity size={17} /> },
  { key: "messages", label: "消息历史", icon: <MessageSquareText size={17} /> },
  { key: "products", label: "商品资料", icon: <Boxes size={17} /> },
  { key: "knowledge", label: "知识审核", icon: <FileText size={17} /> },
  { key: "audit", label: "审计查询", icon: <ClipboardList size={17} /> }
];

const openErpAiCsLoginUrl = "https://www.fcihome.com/ai-cs/customer-admin-login";

type CustomerTrace = JsonRecord & {
  decision_id?: string;
  request_id?: string;
  platform?: string;
  store_id?: string;
  external_message_id?: string;
  conversation_id?: string;
  customer_message?: string;
  ai_reply?: string;
  human_reply?: string;
  action?: string;
  status?: string;
  risk_level?: string;
  missing_context?: unknown;
  service_stage?: JsonRecord;
  source?: string;
  trace?: JsonRecord;
};

type CustomerConversation = {
  id: string;
  title: string;
  subtitle: string;
  lastMessage: string;
  lastTime: string;
  orderLabel: string;
  source: string;
  traces: CustomerTrace[];
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

function platformLabel(value: unknown) {
  const platform = String(value || "").trim();
  const labels: Record<string, string> = { pdd: "拼多多" };
  return labels[platform] || platform || "未知平台";
}

function storeOptionLabel(store: JsonRecord) {
  const id = String(store.id || store.store_id || "").trim();
  const name = String(store.name || "").trim();
  const displayName = name && name !== id ? name : "未命名店铺";
  return `${platformLabel(store.platform)}-${displayName}-${id || "未绑定编号"}`;
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
            label: "使用 open_erp_agent 微信登录",
            onClick: () => window.location.assign(openErpAiCsLoginUrl),
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
  const publicWorkflow = [
    ["客户提问", "收到买家的商品、订单或售后问题。"],
    ["查商品资料", "检索已审核的商品、订单、物流和规则；缺资料就先补资料，不让 AI 猜。"],
    ["检查规则与风险", "检查价格、退款条件和风险表达，判断能不能自动回复。"],
    ["安全回复或转人工", "满足条件才自动回复，不确定时给建议或转人工。"]
  ] as const;
  const reassurance = [
    ["资料有依据", "回复使用已审核的商品、订单、物流和规则资料。", <Search size={19} />],
    ["回复有规则", "价格、退款和风险规则决定是否允许自动发送。", <ShieldCheck size={19} />],
    ["风险可转人工", "资料不全或风险较高时，AI 不强行作答。", <AlertTriangle size={19} />]
  ] as const;
  const openCustomerAdmin = () => navigate(customerAuthed ? "/admin" : "/login");
  const showDemoFlow = () => {
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    document.getElementById("demo-flow")?.scrollIntoView({
      behavior: scrollBehaviorForReducedMotion(reducedMotion),
      block: "start"
    });
  };

  return (
    <main className="landingPage">
      <header className="landingHeader">
        <button className="landingBrand" onClick={() => navigate("/")} aria-label="回到首页">
          <MessageSquareText size={18} />
          <span>AI 客服管理后台</span>
        </button>
        <nav aria-label="公开页导航">
          <button className="textButton" onClick={showDemoFlow}>
            查看演示流程
          </button>
          <button className="darkButton" onClick={openCustomerAdmin}>
            进入客户后台
          </button>
        </nav>
      </header>

      <section className="heroSection">
        <div className="heroCopy">
          <p className="landingEyebrow">可控 AI 客服工作流</p>
          <h1>看得见 AI 怎么回答，也看得见它为什么不回答。</h1>
          <p className="heroSubtitle">
            商品资料给 AI 依据，模拟问答先检查效果，规则和风险控制决定自动回复还是转人工。
          </p>
          <div className="heroActions">
            <button className="darkButton" onClick={openCustomerAdmin}>
              进入客户后台 <ArrowRight size={16} />
            </button>
            <button className="textButton" onClick={showDemoFlow}>
              查看演示流程
            </button>
          </div>
        </div>
        <figure className="workflowProof">
          <picture>
            <source media="(max-width: 720px)" srcSet="/ai-workflow-proof-mobile.png" />
            <img
              src="/ai-workflow-proof.png"
              alt="客户问题经过资料检索、风险检查并停在资料补充步骤的真实客户后台"
            />
          </picture>
          <figcaption>真实客户后台工作流：缺资料就先补资料，不让 AI 猜。</figcaption>
        </figure>
      </section>

      <section className="flowSection" id="demo-flow">
        <div className="sectionIntro">
          <p className="landingEyebrow">一次咨询怎么处理</p>
          <h2>从客户提问到安全回复，每一步都有依据。</h2>
        </div>
        <ol className="flowRail" aria-label="AI 客服处理一次客户咨询的流程">
          {publicWorkflow.map(([title, description], index) => (
            <li key={title}>
              <span className="flowIndex">{index + 1}</span>
              <div>
                <strong>{title}</strong>
                <p>{description}</p>
              </div>
              {index < publicWorkflow.length - 1 ? <ArrowRight className="flowArrow" size={18} aria-hidden="true" /> : null}
            </li>
          ))}
        </ol>
      </section>

      <section className="reassuranceSection" aria-labelledby="reassurance-title">
        <div className="sectionIntro">
          <p className="landingEyebrow">放心交给 AI，也保留人工判断</p>
          <h2 id="reassurance-title">不是每个问题都让 AI 硬答。</h2>
        </div>
        <div className="reassuranceList">
          {reassurance.map(([title, description, icon]) => (
            <article key={title}>
              <span className="reassuranceIcon" aria-hidden="true">{icon}</span>
              <h3>{title}</h3>
              <p>{description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="finalCta">
        <h2>先看清工作流，再决定哪些回复可以自动发送。</h2>
        <button className="darkButton" onClick={openCustomerAdmin}>
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
  const exchangedLaunchTokenRef = React.useRef("");

  React.useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("token") || "";
    if (!token) {
      setError("启动票据缺失，请从 open_erp_agent 客户端重新打开。");
      return;
    }
    if (exchangedLaunchTokenRef.current === token) return;
    exchangedLaunchTokenRef.current = token;
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
  const [simulationLoading, setSimulationLoading] = React.useState(false);
  const [simulationError, setSimulationError] = React.useState<string | null>(null);
  const [selectedTrace, setSelectedTrace] = React.useState<CustomerTrace | null>(null);
  const [selectedConversationId, setSelectedConversationId] = React.useState("");
  const [searchText, setSearchText] = React.useState("");
  const currentStoreRef = React.useRef(storeId);
  const generationRef = React.useRef(0);
  const loadRequestRef = React.useRef(0);
  const simulationRequestRef = React.useRef(0);
  const mountedRef = React.useRef(true);

  const conversations = React.useMemo(() => buildCustomerConversations(rows, searchText), [rows, searchText]);
  const selectedConversation = conversations.find((conversation) => conversation.id === selectedConversationId) || conversations[0] || null;

  function operationIsCurrent(operation: OperationToken, currentRequestId: number) {
    return isCurrentOperation(
      operation,
      currentStoreRef.current,
      generationRef.current,
      currentRequestId,
      mountedRef.current
    );
  }

  async function load(
    source = "",
    options: { reportError?: boolean; throwOnError?: boolean } = {},
    operationStoreId = currentStoreRef.current,
    operationGeneration = generationRef.current
  ) {
    const operation: OperationToken = {
      storeId: operationStoreId,
      generation: operationGeneration,
      requestId: ++loadRequestRef.current
    };
    if (operationIsCurrent(operation, loadRequestRef.current)) setLoading(true);
    try {
      const query = new URLSearchParams({ store_id: operation.storeId });
      if (source) query.set("source", source);
      const response = await requestJson<Page>(`/v1/admin/message-traces?${query.toString()}`);
      const loadedRows = arrayFrom(response.items) as CustomerTrace[];
      if (!operationIsCurrent(operation, loadRequestRef.current)) return [];
      setRows(loadedRows);
      return loadedRows;
    } catch (error) {
      if (!operationIsCurrent(operation, loadRequestRef.current)) return [];
      if (options.reportError !== false) {
        setToast({ tone: "error", text: error instanceof Error ? error.message : String(error) });
      }
      if (options.throwOnError) throw error;
      return [];
    } finally {
      if (operationIsCurrent(operation, loadRequestRef.current)) setLoading(false);
    }
  }

  React.useLayoutEffect(() => {
    mountedRef.current = true;
    if (currentStoreRef.current !== storeId) {
      currentStoreRef.current = storeId;
      generationRef.current += 1;
      loadRequestRef.current += 1;
      simulationRequestRef.current += 1;
    }
    setRows([]);
    setQuestion("");
    setSearchText("");
    setSelectedConversationId("");
    setSelectedTrace(null);
    setSimulationError(null);
    setSimulationLoading(false);
    void load("", {}, storeId, generationRef.current);
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      loadRequestRef.current += 1;
      simulationRequestRef.current += 1;
    };
  }, [storeId]);

  React.useEffect(() => {
    if (!conversations.length) {
      setSelectedConversationId("");
      return;
    }
    if (!selectedConversationId || !conversations.some((conversation) => conversation.id === selectedConversationId)) {
      setSelectedConversationId(conversations[0].id);
    }
  }, [conversations, selectedConversationId]);

  async function simulate() {
    const content = question.trim();
    if (!content || simulationLoading) return;
    const operation: OperationToken = {
      storeId: currentStoreRef.current,
      generation: generationRef.current,
      requestId: ++simulationRequestRef.current
    };
    setSimulationLoading(true);
    setSimulationError(null);
    try {
      const response = await requestJson<JsonRecord>("/v1/admin/message-simulations", {
        method: "POST",
        body: JSON.stringify({ store_id: operation.storeId, platform: "pdd", message: { content } })
      });
      if (!operationIsCurrent(operation, simulationRequestRef.current)) return;
      const decision = readRecord(response, "decision");
      const decisionId = String(decision.decision_id || "");
      const createdTrace = await requireReloadedSimulation(
        () => load("", { reportError: false, throwOnError: true }, operation.storeId, operation.generation),
        decisionId
      );
      if (!operationIsCurrent(operation, simulationRequestRef.current)) return;
      setSearchText("");
      setSelectedConversationId(String(createdTrace.conversation_id || createdTrace.decision_id || ""));
      setSelectedTrace(buildCanonicalSimulationTrace(createdTrace, content));
      setQuestion("");
      setToast({ tone: "success", text: "模拟决策已完成" });
    } catch (error) {
      if (operationIsCurrent(operation, simulationRequestRef.current)) {
        setSimulationError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (operationIsCurrent(operation, simulationRequestRef.current)) setSimulationLoading(false);
    }
  }

  function changeQuestion(value: string) {
    setQuestion(value);
    setSimulationError(null);
  }

  return (
    <>
      <SectionHeader label="MESSAGES" title="消息历史" action={<button disabled={simulationLoading} onClick={() => void load()}><Search size={16} />刷新</button>} />
      <section className="messageHistoryWorkspace" aria-label="客服消息历史工作台">
        <aside className="conversationList" aria-label="会话列表">
          <label className="conversationSearch">
            <Search size={16} />
            <input
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              placeholder="搜索买家、订单、会话"
            />
          </label>
          <div className="conversationListBody">
            {conversations.length ? conversations.map((conversation) => (
              <button
                type="button"
                key={conversation.id}
                className={`conversationItem ${conversation.id === selectedConversation?.id ? "active" : ""}`}
                onClick={() => setSelectedConversationId(conversation.id)}
              >
                <span className="conversationAvatar">{conversation.source === "simulation" ? "测" : "客"}</span>
                <span className="conversationText">
                  <strong>{conversation.title}</strong>
                  <span>{conversation.subtitle}</span>
                  <em>{conversation.lastMessage}</em>
                  <small>{conversation.orderLabel}</small>
                </span>
                <time>{conversation.lastTime || "-"}</time>
              </button>
            )) : (
              <div className="emptyState">
                <strong>{loading ? "正在读取消息历史" : "暂无会话历史"}</strong>
                <p>{loading ? "消息历史正在读取，请稍候。" : "收到客户咨询或完成模拟咨询后，会话会显示在这里。"}</p>
              </div>
            )}
          </div>
        </aside>
        <section className="conversationDetail" aria-label="会话详情">
          {selectedConversation ? (
            <>
              <header className="conversationHeader">
                <div>
                  <h3>{selectedConversation.title}</h3>
                  <p>{platformLabel(selectedConversation.traces[0]?.platform)} · 店铺 {selectedConversation.traces[0]?.store_id || storeId} · 会话 {selectedConversation.id}</p>
                </div>
                <span>{selectedConversation.traces.length} 条历史</span>
              </header>
              <div className="conversationTimeline">
                {selectedConversation.traces.map((trace, index) => (
                  <React.Fragment key={String(trace.decision_id || trace.external_message_id || index)}>
                    <ChatBubble
                      side="buyer"
                      roleLabel={trace.source === "simulation" ? "模拟买家" : "买家"}
                      time={messageTimeLabel(trace)}
                      text={String(trace.customer_message || "-")}
                    />
                    {trace.ai_reply ? (
                      <ChatBubble
                        side="agent"
                        roleLabel="AI 客服"
                        time={messageTimeLabel(trace)}
                        text={String(trace.ai_reply)}
                        meta={decisionBadges(trace)}
                        action={<button onClick={() => setSelectedTrace(trace)}><Search size={15} />决策路径</button>}
                      />
                    ) : null}
                    {trace.human_reply ? (
                      <ChatBubble
                        side="agent"
                        roleLabel="人工客服"
                        time={messageTimeLabel(trace)}
                        text={String(trace.human_reply)}
                        action={<button onClick={() => setSelectedTrace(trace)}><Search size={15} />决策路径</button>}
                      />
                    ) : null}
                    {!trace.ai_reply && !trace.human_reply ? (
                      <div className="conversationActionOnly">
                        <button onClick={() => setSelectedTrace(trace)}><Search size={15} />决策路径</button>
                      </div>
                    ) : null}
                  </React.Fragment>
                ))}
              </div>
              <SimulationComposer
                value={question}
                loading={simulationLoading}
                error={simulationError}
                onChange={changeQuestion}
                onSubmit={() => void simulate()}
              />
            </>
          ) : (
            loading ? (
              <div className="emptyState">
                <strong>正在读取消息历史</strong>
                <p>消息历史正在读取，请稍候。</p>
              </div>
            ) : (
              <SimulationComposer
                value={question}
                loading={simulationLoading}
                error={simulationError}
                emptyState
                onChange={changeQuestion}
                onSubmit={() => void simulate()}
              />
            )
          )}
        </section>
      </section>
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

function ChatBubble({ side, roleLabel, time, text, meta, action }: {
  side: "buyer" | "agent";
  roleLabel: string;
  time: string;
  text: string;
  meta?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <article className={`chatBubble ${side}`}>
      <div className="chatBubbleMeta">
        <span>{roleLabel}</span>
        {time ? <time>{time}</time> : null}
      </div>
      <p>{text}</p>
      {meta || action ? (
        <div className="chatBubbleFooter">
          {meta || <span />}
          {action}
        </div>
      ) : null}
    </article>
  );
}

function buildCustomerConversations(rows: CustomerTrace[], searchText: string): CustomerConversation[] {
  const groups = new Map<string, CustomerTrace[]>();
  rows.forEach((row) => {
    const key = String(row.conversation_id || row.external_message_id || row.decision_id || "unknown");
    groups.set(key, [...(groups.get(key) || []), row]);
  });
  const query = searchText.trim().toLowerCase();
  return Array.from(groups.entries())
    .map(([id, traces]) => {
      const last = traces[traces.length - 1] || {};
      return {
        id,
        title: conversationTitle(last, id),
        subtitle: `会话 ${id}`,
        lastMessage: conversationLastMessage(last),
        lastTime: messageTimeLabel(last),
        orderLabel: orderLabel(last),
        source: String(last.source || "external"),
        traces
      };
    })
    .filter((conversation) => {
      if (!query) return true;
      return [
        conversation.title,
        conversation.subtitle,
        conversation.lastMessage,
        conversation.orderLabel,
        conversation.id,
        ...conversation.traces.flatMap((trace) => [
          trace.decision_id,
          trace.request_id,
          trace.external_message_id,
          trace.customer_message,
          trace.ai_reply,
          trace.human_reply
        ])
      ].some((value) => String(value || "").toLowerCase().includes(query));
    });
}

function conversationTitle(trace: CustomerTrace, fallback: string) {
  if (trace.source === "simulation") return "模拟咨询";
  const id = String(trace.conversation_id || fallback || "").trim();
  if (!id) return "客户会话";
  return id.length > 10 ? `${id.slice(0, 4)}****${id.slice(-4)}` : id;
}

function conversationLastMessage(trace: CustomerTrace) {
  return String(trace.customer_message || trace.ai_reply || trace.human_reply || "暂无消息内容");
}

function orderLabel(trace: CustomerTrace) {
  const listing = String(trace.listing_ref || "").trim();
  return listing ? `商品 ${listing}` : "无订单号";
}

function messageTimeLabel(trace: CustomerTrace) {
  const value = String(trace.sent_at || trace.created_at || trace.updated_at || "").trim();
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false });
}

function decisionBadges(trace: CustomerTrace) {
  const badges = presentDecisionBadges({
    action: trace.action,
    status: trace.status,
    risk: trace.risk_level
  });
  const stage = presentServiceStage(trace.service_stage);
  return (
    <span className="decisionBadges" aria-label="本次 AI 决策摘要">
      <span className={`decisionBadge ${stage.tone}`} title={stage.raw || "legacy-unclassified"}>{stage.label}</span>
      {badges.map((badge) => (
        <span key={badge.key} className={`decisionBadge ${badge.tone}`} title={badge.raw}>{badge.label}</span>
      ))}
    </span>
  );
}

function MessageTraceDrawer({ trace, onClose, onRaw }: { trace: CustomerTrace; onClose: () => void; onRaw: () => void }) {
  const presentation = presentDecisionTrace({
    action: trace.action,
    status: trace.status,
    risk: trace.risk_level,
    missingContext: trace.missing_context
  });
  const stage = presentServiceStage(trace.service_stage);
  const stageRecord = readRecord(trace, "service_stage");
  const secondaryStages = Array.isArray(stageRecord.secondary_stages)
    ? stageRecord.secondary_stages.map((value) => presentServiceStage({ primary_stage: value }).label)
    : [];
  return (
    <aside className="drawer messageTraceDrawer">
      <div className="drawerHeader">
        <h2>决策路径</h2>
        <button onClick={onClose}>关闭</button>
      </div>
      <div className="traceSummary">
        <Metric label="咨询阶段" value={stage.label} tone="info" title={stage.raw || "legacy-unclassified"} />
        <Metric label="动作" value={presentation.actionLabel} tone="info" title={String(trace.action || "-")} />
        <Metric label="状态" value={presentation.statusLabel} tone="ok" title={String(trace.status || "-")} />
        <Metric label="风险" value={presentation.riskLabel} tone="warn" title={String(trace.risk_level || "-")} />
      </div>
      <section className="traceTextBlock" aria-label="咨询阶段分类详情">
        <h3>阶段分类依据</h3>
        <p>主分类：{stage.label}；次分类：{secondaryStages.join("、") || "无"}</p>
        <p>置信度：{typeof stageRecord.confidence === "number" ? stageRecord.confidence.toFixed(2) : "-"}；理由码：{String(stageRecord.reason_code || "-")}</p>
        <p>所需资料：{Array.isArray(stageRecord.needs_context) ? stageRecord.needs_context.join("、") || "无" : "无"}</p>
        <p>证据引用：{Array.isArray(stageRecord.evidence_refs) ? stageRecord.evidence_refs.join("、") || "无" : "无"}</p>
      </section>
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
      <DecisionTraceReplay
        trace={trace.trace}
        action={trace.action}
        status={trace.status}
        risk={trace.risk_level}
        missingContext={trace.missing_context}
      />
      <button onClick={onRaw}>查看原始记录</button>
    </aside>
  );
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
        {stores.map((item) => <option key={String(item.id || item.store_id)} value={String(item.id || item.store_id)}>{storeOptionLabel(item)}</option>)}
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
