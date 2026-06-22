export type Workspace = "customer" | "system";
export type AdminSurface = "customer-landing" | "customer-login" | "customer-admin" | "system-login" | "system-admin";

type RouteInput = {
  workspace: Workspace;
  pathname: string;
  authed: boolean;
};

type RouteState = {
  surface: AdminSurface;
  requiresAuth: boolean;
  redirectTo?: string;
};

const CUSTOMER_ADMIN_HOST = "admin.ecommerce-cs-agent-dev.fcihome.com";
const SYSTEM_ADMIN_HOST = "system-admin.ecommerce-cs-agent-dev.fcihome.com";

export function detectWorkspaceFromLocation(location: Pick<Location, "hostname" | "pathname">): Workspace {
  if (location.hostname === SYSTEM_ADMIN_HOST || location.hostname.startsWith("system-admin.")) return "system";
  if (location.hostname === CUSTOMER_ADMIN_HOST || location.hostname.startsWith("admin.")) return "customer";
  return location.pathname.startsWith("/system-admin") ? "system" : "customer";
}

export function authMePathForWorkspace(workspace: Workspace) {
  return workspace === "customer" ? "/v1/admin/auth/me" : "/v1/system-admin/auth/me";
}

export function resolveAdminRoute({ workspace, pathname, authed }: RouteInput): RouteState {
  if (workspace === "customer") {
    if (isCustomerAdminPath(pathname)) {
      return authed
        ? { surface: "customer-admin", requiresAuth: true }
        : { surface: "customer-login", requiresAuth: true, redirectTo: "/login" };
    }
    if (pathname === "/login") return { surface: "customer-login", requiresAuth: false };
    return { surface: "customer-landing", requiresAuth: false };
  }

  if (pathname === "/login" && !authed) return { surface: "system-login", requiresAuth: false };
  return authed
    ? { surface: "system-admin", requiresAuth: true }
    : { surface: "system-login", requiresAuth: true, redirectTo: "/login" };
}

export function shouldRefreshAuth(workspace: Workspace, pathname: string) {
  return workspace === "system" || isCustomerAdminPath(pathname);
}

export function isCustomerAdminPath(pathname: string) {
  return pathname === "/admin" || pathname.startsWith("/admin/");
}
