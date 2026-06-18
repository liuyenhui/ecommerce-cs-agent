import "@testing-library/jest-dom/vitest";
import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

async function renderApp(path = "/") {
  vi.resetModules();
  window.history.pushState({}, "", path);
  document.body.innerHTML = '<div id="root"></div>';
  const fetchMock = vi.fn<(...args: Parameters<typeof fetch>) => ReturnType<typeof fetch>>(
    () => Promise.reject(new Error("not authenticated"))
  );
  vi.stubGlobal("fetch", fetchMock);
  await import("./main");
  return fetchMock;
}

describe("LoginPanel", () => {
  beforeEach(() => {
    cleanup();
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  test("renders customer login fields empty by default", async () => {
    await renderApp("/");

    expect(await screen.findByRole("heading", { name: "客户后台登录" })).toBeInTheDocument();
    expect(screen.getByLabelText("邮箱")).toHaveValue("");
    expect(screen.getByLabelText("密码")).toHaveValue("");
    expect(screen.getByLabelText("组织 ID")).toHaveValue("");
    expect(screen.queryByDisplayValue("admin@example.test")).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("org-001")).not.toBeInTheDocument();
  });

  test("renders system login fields empty by default", async () => {
    await renderApp("/system-admin");

    expect(await screen.findByRole("heading", { name: "系统后台登录" })).toBeInTheDocument();
    expect(screen.getByLabelText("邮箱")).toHaveValue("");
    expect(screen.getByLabelText("密码")).toHaveValue("");
    expect(screen.queryByDisplayValue("system-admin@example.test")).not.toBeInTheDocument();
  });

  test("shows inline customer validation errors without sending invalid requests", async () => {
    const fetchMock = await renderApp("/");
    await screen.findByRole("heading", { name: "客户后台登录" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    fetchMock.mockClear();

    await userEvent.click(screen.getByRole("button", { name: /登录/ }));

    expect(screen.getByText("请填写邮箱、密码和组织 ID")).toBeInTheDocument();
    expect(screen.getByLabelText("邮箱")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("密码")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("组织 ID")).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("shows inline system validation errors without sending invalid requests", async () => {
    const fetchMock = await renderApp("/system-admin");
    await screen.findByRole("heading", { name: "系统后台登录" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    fetchMock.mockClear();

    await userEvent.click(screen.getByRole("button", { name: /登录/ }));

    expect(screen.getByText("请填写邮箱和密码")).toBeInTheDocument();
    expect(screen.getByLabelText("邮箱")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("密码")).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("uses customer auth endpoints and disables submit while login is pending", async () => {
    const fetchMock = await renderApp("/");
    await screen.findByRole("heading", { name: "客户后台登录" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    fetchMock.mockClear();
    let resolveLogin: (response: Response) => void = () => undefined;
    const loginResponse = new Promise<Response>((resolve) => {
      resolveLogin = resolve;
    });
    fetchMock.mockImplementationOnce(() => loginResponse);
    fetchMock.mockImplementationOnce(() => Promise.resolve(new Response(JSON.stringify({
      user: { display_name: "Customer Admin" },
      active_organization_id: "org-a",
      active_store_id: "store-a",
      organizations: [],
      stores: []
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await userEvent.type(screen.getByLabelText("邮箱"), "admin@example.invalid");
    await userEvent.type(screen.getByLabelText("密码"), "demo-passphrase");
    await userEvent.type(screen.getByLabelText("组织 ID"), "org-a");
    await userEvent.click(screen.getByRole("button", { name: /登录/ }));

    await waitFor(() => expect(screen.getByRole("button", { name: /登录/ })).toBeDisabled());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/v1/admin/auth/login");
    resolveLogin(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toBe("/v1/admin/auth/me");
  });

  test("uses system auth endpoints and disables submit while login is pending", async () => {
    const fetchMock = await renderApp("/system-admin");
    await screen.findByRole("heading", { name: "系统后台登录" });
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    fetchMock.mockClear();
    let resolveLogin: (response: Response) => void = () => undefined;
    const loginResponse = new Promise<Response>((resolve) => {
      resolveLogin = resolve;
    });
    fetchMock.mockImplementationOnce(() => loginResponse);
    fetchMock.mockImplementationOnce(() => Promise.resolve(new Response(JSON.stringify({
      user: { display_name: "System Admin" }
    }), { status: 200, headers: { "Content-Type": "application/json" } })));

    await userEvent.type(screen.getByLabelText("邮箱"), "system-admin@example.invalid");
    await userEvent.type(screen.getByLabelText("密码"), "demo-passphrase");
    await userEvent.click(screen.getByRole("button", { name: /登录/ }));

    await waitFor(() => expect(screen.getByRole("button", { name: /登录/ })).toBeDisabled());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/v1/system-admin/auth/login");
    resolveLogin(new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toBe("/v1/system-admin/auth/me");
  });
});
