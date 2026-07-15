import React from "react";
import { AdminFrame, LoginPanelBase, TopBar, useCloseOnEscape } from "../../shared/components";
import type { JsonRecord, ToastState } from "../../shared/types";
import { systemApi } from "./system-api";
import { persistRailCollapsed, readRailCollapsed, SystemNavigation, SystemWorkspace } from "./SystemWorkspace";
import type { SystemPage } from "./system-types";

const pageTitles: Record<SystemPage, { title: string; subtitle: string }> = {
  dashboard: { title: "系统总览", subtitle: "平台聚合指标与优先运营工作" },
  tenants: { title: "租户与店铺", subtitle: "跨租户开通状态与店铺运行边界" },
  readiness: { title: "配置完成度", subtitle: "逐店铺上线检查与阻断处理" },
  llm: { title: "LLM 治理", subtitle: "Provider、路由、成本与配置版本" },
  releases: { title: "评测与发布", subtitle: "评测门禁、审批、发布与回滚" },
  traces: { title: "决策追踪", subtitle: "按明确范围定位并回放单条决策" },
  tasks: { title: "任务中心", subtitle: "后台任务状态与安全重试" },
  audit: { title: "安全审计", subtitle: "高风险变更与敏感访问查询" },
  health: { title: "系统健康", subtitle: "应用、依赖与部署健康检查" }
};

export function App() {
  const [activePage, setActivePage] = React.useState<SystemPage>("dashboard");
  const [systemSession, setSystemSession] = React.useState<JsonRecord | null>(null);
  const [toast, setToast] = React.useState<ToastState>(null);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const [loggingOut, setLoggingOut] = React.useState(false);
  const [railCollapsed, setRailCollapsed] = React.useState(() => {
    try { return readRailCollapsed(window.localStorage); } catch { return false; }
  });
  const authGeneration = React.useRef(0);
  const authController = React.useRef<AbortController | null>(null);
  const closeNav = React.useCallback(() => setMobileNavOpen(false), []);
  useCloseOnEscape(mobileNavOpen, closeNav);

  React.useEffect(() => {
    const generation = ++authGeneration.current;
    const controller = new AbortController();
    authController.current = controller;
    void systemApi.me(controller.signal).then((session) => {
      if (!controller.signal.aborted && authGeneration.current === generation) setSystemSession(session);
    }).catch(() => undefined);
    return () => { controller.abort(); authGeneration.current += 1; };
  }, []);

  function loggedIn(session: JsonRecord) {
    authController.current?.abort();
    authGeneration.current += 1;
    setLoggingOut(false);
    setSystemSession(session);
  }

  async function login(email: string, password: string) {
    authController.current?.abort();
    const generation = ++authGeneration.current;
    const controller = new AbortController();
    authController.current = controller;
    setLoggingOut(false);
    const session = await systemApi.login(email, password, controller.signal);
    if (controller.signal.aborted || authGeneration.current !== generation) throw new DOMException("Superseded authentication request", "AbortError");
    return session;
  }

  async function logout() {
    authController.current?.abort();
    const generation = ++authGeneration.current;
    const controller = new AbortController();
    authController.current = controller;
    setLoggingOut(true);
    setSystemSession(null);
    try { await systemApi.logout(controller.signal); } catch { /* The server session may already be gone. */ }
    if (controller.signal.aborted || authGeneration.current !== generation) return;
    setLoggingOut(false);
    setToast({ tone: "info", text: "已退出系统后台" });
  }

  function toggleRail() {
    setRailCollapsed((current) => {
      const next = !current;
      try { persistRailCollapsed(window.localStorage, next); } catch { /* Storage may be unavailable. */ }
      return next;
    });
  }

  const heading = pageTitles[activePage];
  const isAuthenticated = Boolean(systemSession);
  return <AdminFrame
    isAuthenticated={isAuthenticated}
    mobileNavOpen={mobileNavOpen}
    railCollapsed={railCollapsed}
    onToggleRail={toggleRail}
    brand="System Admin"
    navigation={<SystemNavigation activePage={activePage} collapsed={railCollapsed} onChange={setActivePage} onNavigate={closeNav} />}
    topBar={<TopBar eyebrow="SYSTEM ADMIN" title={heading.title} subtitle={heading.subtitle} showNavButton={isAuthenticated} navOpen={mobileNavOpen} onToggleNav={() => setMobileNavOpen((open) => !open)} onLogout={() => void logout()} />}
    toast={toast}
    onCloseNav={closeNav}
    onCloseToast={() => setToast(null)}
  >
    {systemSession
      ? <SystemWorkspace session={systemSession} activePage={activePage} setToast={setToast} />
      : loggingOut
        ? <section className="loginSurface"><p className="inlineStatus" role="status">正在退出系统后台</p></section>
        : <LoginPanelBase title="系统后台登录" onSubmit={login} onLoggedIn={loggedIn} setToast={setToast} />}
  </AdminFrame>;
}
