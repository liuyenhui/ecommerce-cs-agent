// @vitest-environment jsdom
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AdminFrame, RequestStateView } from "../../shared/components";
import { DashboardPage } from "./pages/DashboardPage";
import { AuditPage } from "./pages/AuditPage";
import { HealthPage } from "./pages/HealthPage";
import { ReadinessPage } from "./pages/ReadinessPage";
import { TasksPage } from "./pages/TasksPage";
import { TenantsPage } from "./pages/TenantsPage";
import { TracesPage } from "./pages/TracesPage";
import { App } from "./App";
import { SYSTEM_ADMIN_URLS, systemAdminPaths } from "./system-api";
import {
  RAIL_COLLAPSED_STORAGE_KEY,
  SystemNavigation,
  SystemWorkspace,
  loadDashboardSupportingData,
  persistRailCollapsed,
  readRailCollapsed,
  systemNavigationItems
} from "./SystemWorkspace";
import { PaginationControls } from "./pages/PaginationControls";

const markup = (node: React.ReactNode) => renderToStaticMarkup(<>{node}</>);

function response(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    headers: new Headers({ "Content-Type": "application/json" }),
    json: async () => payload,
    text: async () => JSON.stringify(payload)
  } as Response;
}

beforeEach(() => {
  const values = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      clear: () => values.clear(),
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key)
    }
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("System Admin operations shell", () => {
  it("renders all nine task-oriented navigation destinations with icons", () => {
    const html = markup(<SystemNavigation activePage="dashboard" collapsed={false} onChange={() => undefined} />);

    for (const label of [
      "系统总览",
      "租户与店铺",
      "配置完成度",
      "LLM 治理",
      "评测与发布",
      "决策追踪",
      "任务中心",
      "安全审计",
      "系统健康"
    ]) {
      expect(html).toContain(label);
    }
    expect((html.match(/<svg/g) || [])).toHaveLength(9);
  });

  it("persists the desktop rail preference under the isolated System Admin key", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value)
    };

    persistRailCollapsed(storage, true);

    expect(RAIL_COLLAPSED_STORAGE_KEY).toBe("system-admin:rail-collapsed");
    expect(values.get(RAIL_COLLAPSED_STORAGE_KEY)).toBe("true");
    expect(readRailCollapsed(storage)).toBe(true);
  });

  it("renders the authenticated App and persists a real collapse click with nine tooltips", async () => {
    const requested: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      requested.push(path);
      if (path === SYSTEM_ADMIN_URLS.me) return response({ user: { system_user_id: "sys-1", display_name: "Operator", roles: ["super_admin"] } });
      if (path === SYSTEM_ADMIN_URLS.dashboardSummary) return response({
        active_organizations: 1,
        active_stores: 1,
        decisions_today: 0,
        auto_reply_rate: null,
        handoff_rate: null,
        error_rate: null,
        readiness_blockers: 0,
        pending_tasks: 0,
        critical_alerts: 0,
        recent_releases: [],
        recent_releases_status: "available",
        recent_releases_error: null,
        generated_at: "2026-07-15T00:00:00Z"
      });
      return response({ items: [], page_info: { page: 1, page_size: 5, total: 0 } });
    }));

    render(<App />);
    const collapse = await screen.findByRole("button", { name: "收起桌面导航" });
    for (const label of systemNavigationItems.map((item) => item.label)) {
      expect(screen.getByRole("button", { name: label }).getAttribute("title")).toBeNull();
    }
    fireEvent.click(collapse);

    expect(collapse.getAttribute("aria-expanded")).toBe("false");
    expect(window.localStorage.getItem(RAIL_COLLAPSED_STORAGE_KEY)).toBe("true");
    for (const label of systemNavigationItems.map((item) => item.label)) {
      expect(screen.getByRole("button", { name: label }).getAttribute("title")).toBe(label);
    }
    await waitFor(() => expect(requested).toContain(SYSTEM_ADMIN_URLS.dashboardSummary));
    expect(requested.every((path) => path.startsWith("/v1/system-admin/"))).toBe(true);
  });

  it("keeps every System Admin API URL in the isolated API namespace", () => {
    expect(Object.values(SYSTEM_ADMIN_URLS)).not.toHaveLength(0);
    expect([...Object.values(SYSTEM_ADMIN_URLS), ...systemAdminPaths("decision-1", "task-1")])
      .toSatisfy((paths: string[]) => paths.every((path) => path.startsWith("/v1/system-admin/")));
  });
});

describe("request states", () => {
  it.each([
    [{ kind: "loading" as const }, "正在加载真实系统数据"],
    [{ kind: "empty" as const, title: "暂无记录", description: "服务端未返回记录" }, "暂无记录"],
    [{ kind: "forbidden" as const, message: "当前角色无权访问" }, "当前角色无权访问"],
    [{ kind: "partial" as const, data: { ok: true }, failures: ["任务数据暂不可用"] }, "部分数据加载失败"],
    [{ kind: "error" as const, message: "服务暂不可用" }, "服务暂不可用"]
  ])("renders %o without demo fallback", (state, expected) => {
    const html = markup(<RequestStateView state={state}>{() => <span>真实数据</span>}</RequestStateView>);

    expect(html).toContain(expected);
    expect(html).not.toMatch(/demo|sample|fake/i);
  });
});

describe("DashboardPage", () => {
  it("renders server dashboard-summary aggregates instead of list lengths", () => {
    const html = markup(<DashboardPage state={{
      kind: "success",
      data: {
        summary: {
          active_organizations: 47,
          active_stores: 82,
          decisions_today: 301,
          auto_reply_rate: null,
          handoff_rate: 0.2,
          error_rate: 0.01,
          readiness_blockers: 6,
          pending_tasks: 9,
          critical_alerts: 2,
          recent_releases: [{ release_id: "release-real", organization_id: "org-1", config_version_id: "version-1", version_number: 1, status: "running", published_at: "2026-07-15T00:00:00Z", submitted_at: "2026-07-14T23:00:00Z" }],
          recent_releases_status: "available",
          recent_releases_error: null,
          generated_at: "2026-07-15T00:00:00Z"
        },
        readiness: { items: [{ store_id: "store-1" }], page: { page: 1, page_size: 20, total: 999 } },
        tasks: { items: [{ task_id: "task-1" }], page: { page: 1, page_size: 20, total: 888 } },
        decisions: { items: [], page: { page: 1, page_size: 20, total: 0 } }
      }
    }} />);

    expect(html).toContain("47");
    expect(html).toContain("82");
    expect(html).toContain("301");
    expect(html).toContain("暂无可计算数据");
    expect(html).toContain("release-real");
    expect(html).not.toContain("999");
    expect(html).not.toContain("888");
  });

  it("shows an explicit partial failure instead of pretending releases are empty", () => {
    const html = markup(<DashboardPage state={{ kind: "success", data: {
      summary: { active_organizations: 1, active_stores: 1, decisions_today: 1, auto_reply_rate: 1, handoff_rate: 0, error_rate: 0, readiness_blockers: 0, pending_tasks: 0, critical_alerts: 0, recent_releases: [], recent_releases_status: "unavailable", recent_releases_error: "release_data_unavailable", generated_at: "2026-07-15T00:00:00Z" },
      readiness: { items: [], page: { page: 1, page_size: 5, total: 0 } }, tasks: { items: [], page: { page: 1, page_size: 5, total: 0 } }, decisions: { items: [], page: { page: 1, page_size: 5, total: 0 } }
    } }} />);
    expect(html).toContain("发布数据暂不可用");
    expect(html).not.toContain("暂无最近发布");
  });
});

describe("operational pages", () => {
  it("submits datetime-local audit bounds as timezone-aware ISO timestamps", () => {
    let submitted: Record<string, string> | undefined;
    render(<AuditPage
      state={{ kind: "empty", title: "暂无审计记录", description: "没有记录" }}
      onSearch={(filters) => { submitted = filters; }}
    />);

    fireEvent.change(screen.getByLabelText("time_from"), { target: { value: "2026-07-15T08:30" } });
    fireEvent.change(screen.getByLabelText("time_to"), { target: { value: "2026-07-15T09:30" } });
    fireEvent.click(screen.getByRole("button", { name: "查询" }));

    expect(submitted).toBeDefined();
    expect(submitted?.time_from).toBe(new Date(submitted?.time_from || "").toISOString());
    expect(submitted?.time_to).toBe(new Date(submitted?.time_to || "").toISOString());
  });

  it("uses paginated totals and keeps tenant details separate from readiness", () => {
    const html = markup(<TenantsPage state={{
      kind: "success",
      data: {
        tenants: { items: [{ organization_id: "org-1", name: "甲组织", status: "active" }], page: { page: 1, page_size: 20, total: 73 } },
        stores: { items: [], page: { page: 1, page_size: 20, total: 109 } }
      }
    }} />);

    expect(html).toContain("共 73 个租户");
    expect(html).toContain("共 109 家店铺");
    expect(html).not.toContain("配置完成度检查");
  });

  it("shows reason, impact and next action for every blocked readiness check", () => {
    const html = markup(<ReadinessPage state={{
      kind: "success",
      data: {
        items: [{
          organization_id: "org-1",
          store_id: "store-1",
          status: "blocked",
          updated_at: "2026-07-15T00:00:00Z",
          checks: [{ code: "product_content", status: "blocked", message: "缺少商品资料", reason: "尚未导入" }]
        }],
        page: { page: 1, page_size: 20, total: 1 }
      }
    }} />);

    expect(html).toContain("原因");
    expect(html).toContain("影响");
    expect(html).toContain("下一步");
    expect(html).toContain("尚未导入");
  });

  it("only renders retry controls when the server marks a task retryable", () => {
    const html = markup(<TasksPage state={{
      kind: "success",
      data: {
        items: [
          { task_id: "task-safe", task_type: "embedding", status: "failed", retryable: true },
          { task_id: "task-unsafe", task_type: "bulk_import", status: "failed", retryable: false },
          { task_id: "task-queued", task_type: "embedding", status: "queued", retryable: true }
        ],
        page: { page: 1, page_size: 20, total: 3 }
      }
    }} onRetry={() => undefined} />);

    expect((html.match(/>重试</g) || [])).toHaveLength(1);
  });

  it("shows partial dependency failure as degraded in structured health groups", () => {
    const html = markup(<HealthPage state={{
      kind: "success",
      data: {
        status: "healthy",
        checked_at: "2026-07-15T00:00:00Z",
        dependencies: [
          { name: "api", status: "healthy", checked_at: "2026-07-15T00:00:00Z" },
          { name: "postgresql", status: "degraded", message: "replica lag", checked_at: "2026-07-15T00:00:00Z" },
          { name: "k8s_deployment", status: "healthy", checked_at: "2026-07-15T00:00:00Z" }
        ]
      }
    }} />);

    expect(html).toContain("应用");
    expect(html).toContain("依赖");
    expect(html).toContain("部署");
    expect(html).toContain("degraded");
  });

  it("shows the server trace total instead of the current page row count", () => {
    const html = markup(<TracesPage
      state={{ kind: "success", data: { items: [{ decision_id: "decision-1" }], page: { page: 1, page_size: 20, total: 247 } } }}
      detail={null}
      onSearch={() => undefined}
      onOpen={() => undefined}
      onClose={() => undefined}
    />);

    expect(html).toContain("共 247 条决策");
  });

  it("does not query organization-scoped Task 7 releases from the global dashboard", async () => {
    let releaseCalled = false;
    let readinessFilters: unknown;
    const page = { items: [], page: { page: 1, page_size: 5, total: 0 } };
    const api = {
      readiness: async (filters: unknown) => { readinessFilters = filters; return page; },
      tasks: async () => page,
      traces: async () => page,
      releases: async () => { releaseCalled = true; return page; }
    };

    const result = await loadDashboardSupportingData(api, new Date("2026-07-15T12:00:00Z"));

    expect(releaseCalled).toBe(false);
    expect(readinessFilters).toEqual({ status: "blocked", page_size: 5 });
    expect(result.pages).toHaveLength(3);
  });

  it("removes the retry control after the task is queued", () => {
    function RetryHarness() {
      const [task, setTask] = React.useState({ task_id: "task-1", status: "failed", retryable: true });
      return <TasksPage state={{ kind: "success", data: { items: [task], page: { page: 1, page_size: 20, total: 1 } } }} onRetry={() => setTask({ ...task, status: "queued", retryable: false })} />;
    }
    render(<RetryHarness />);
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(screen.queryByRole("button", { name: "重试" })).toBeNull();
  });

  it("uses server totals and enforces pagination bounds", () => {
    const onPageChange = vi.fn();
    render(<PaginationControls page={{ page: 2, page_size: 20, total: 41 }} onPageChange={onPageChange} />);
    fireEvent.click(screen.getByRole("button", { name: "上一页" }));
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    expect(onPageChange.mock.calls).toEqual([[1], [3]]);
    expect(screen.getByText("第 2 / 3 页，共 41 条")).toBeTruthy();
  });
});

describe("async request ownership", () => {
  it("requests page two for more than twenty server tasks", async () => {
    const paths: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      paths.push(String(input));
      const page = String(input).includes("page=2") ? 2 : 1;
      return response({ items: [{ task_id: `task-${page}`, status: "queued", retryable: false }], page_info: { page, page_size: 20, total: 25 } });
    }));
    render(<SystemWorkspace activePage="tasks" setToast={() => undefined} />);
    await screen.findByText("task-1");
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("task-2");
    expect(paths.some((path) => path.includes("page=2") && path.includes("page_size=20"))).toBe(true);
  });

  it("never lets an older audit response overwrite the latest filter", async () => {
    let resolveFirst!: (value: Response) => void;
    const first = new Promise<Response>((resolve) => { resolveFirst = resolve; });
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      calls += 1;
      if (calls === 1) return first;
      expect(String(input)).toContain("action=newest");
      return Promise.resolve(response({ items: [{ audit_log_id: "new-record" }], page_info: { page: 1, page_size: 20, total: 1 } }));
    }));
    render(<SystemWorkspace activePage="audit" setToast={() => undefined} />);
    fireEvent.change(screen.getByLabelText("action"), { target: { value: "newest" } });
    fireEvent.click(screen.getByRole("button", { name: "查询" }));
    await screen.findByText("new-record");
    resolveFirst(response({ items: [{ audit_log_id: "old-record" }], page_info: { page: 1, page_size: 20, total: 1 } }));
    await Promise.resolve();
    expect(screen.queryByText("old-record")).toBeNull();
  });

  it("does not restore a late auth me response after logout", async () => {
    let resolveInitialMe!: (value: Response) => void;
    const initialMe = new Promise<Response>((resolve) => { resolveInitialMe = resolve; });
    let resolveLogout!: (value: Response) => void;
    const pendingLogout = new Promise<Response>((resolve) => { resolveLogout = resolve; });
    let meCalls = 0;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === SYSTEM_ADMIN_URLS.me && ++meCalls === 1) return initialMe;
      if (path === SYSTEM_ADMIN_URLS.me) return Promise.resolve(response({ user: { display_name: "Operator" } }));
      if (path === SYSTEM_ADMIN_URLS.login) return Promise.resolve(response({}));
      if (path === SYSTEM_ADMIN_URLS.logout) return pendingLogout;
      if (path === SYSTEM_ADMIN_URLS.dashboardSummary) return Promise.resolve(response({ active_organizations: 0, active_stores: 0, decisions_today: 0, auto_reply_rate: null, handoff_rate: null, error_rate: null, readiness_blockers: 0, pending_tasks: 0, critical_alerts: 0, recent_releases: [], recent_releases_status: "available", recent_releases_error: null, generated_at: "2026-07-15T00:00:00Z" }));
      return Promise.resolve(response({ items: [], page_info: { page: 1, page_size: 5, total: 0 } }));
    }));
    render(<App />);
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "operator@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "password" } });
    fireEvent.click(screen.getByRole("button", { name: "登录" }));
    const logout = await screen.findByRole("button", { name: "退出" });
    fireEvent.click(logout);
    await screen.findByText("正在退出系统后台");
    expect(screen.queryByRole("heading", { name: "系统后台登录" })).toBeNull();
    resolveInitialMe(response({ user: { display_name: "Late user" } }));
    await Promise.resolve();
    expect(screen.queryByText("Late user")).toBeNull();
    resolveLogout(response({}));
    await screen.findByRole("heading", { name: "系统后台登录" });
  });
});

describe("shared mobile navigation focus", () => {
  it("traps mobile focus, closes on Escape, and restores the menu trigger", async () => {
    Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ matches: true, addEventListener: () => undefined, removeEventListener: () => undefined }) });
    function FrameHarness() {
      const [open, setOpen] = React.useState(false);
      return <AdminFrame isAuthenticated mobileNavOpen={open} brand="Admin" navigation={<><button>第一项</button><button>最后一项</button></>} topBar={<button onClick={() => setOpen(true)}>菜单</button>} toast={null} onCloseNav={() => setOpen(false)} onCloseToast={() => undefined}>内容</AdminFrame>;
    }
    render(<FrameHarness />);
    const menu = screen.getByRole("button", { name: "菜单" });
    menu.focus();
    fireEvent.click(menu);
    const dialog = await screen.findByRole("dialog", { name: "后台导航" });
    const first = screen.getByRole("button", { name: "第一项" });
    const last = screen.getByRole("button", { name: "最后一项" });
    expect(document.activeElement).toBe(first);
    expect(dialog.getAttribute("aria-modal")).toBe("true");
    expect(document.querySelector(".mainPane")?.getAttribute("inert")).toBe("");
    expect(document.querySelector(".mainPane")?.getAttribute("aria-hidden")).toBe("true");
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.activeElement).toBe(menu);
  });

  it("keeps the shared customer/system shell non-modal on desktop", async () => {
    Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) });
    render(<AdminFrame isAuthenticated mobileNavOpen brand="Admin" navigation={<button>导航</button>} topBar={<button>菜单</button>} toast={null} onCloseNav={() => undefined} onCloseToast={() => undefined}>内容</AdminFrame>);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(document.querySelector(".mainPane")?.hasAttribute("inert")).toBe(false);
    expect(document.querySelector(".mainPane")?.hasAttribute("aria-hidden")).toBe(false);
  });
});
