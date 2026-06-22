import assert from "node:assert/strict";
import { describe, test } from "node:test";
import {
  authMePathForWorkspace,
  detectWorkspaceFromLocation,
  resolveAdminRoute
} from "./routing.ts";

describe("admin web routing", () => {
  test("keeps workspace detection host based", () => {
    assert.equal(
      detectWorkspaceFromLocation({ hostname: "admin.ecommerce-cs-agent-dev.fcihome.com", pathname: "/" }),
      "customer"
    );
    assert.equal(
      detectWorkspaceFromLocation({ hostname: "system-admin.ecommerce-cs-agent-dev.fcihome.com", pathname: "/" }),
      "system"
    );
    assert.equal(detectWorkspaceFromLocation({ hostname: "localhost", pathname: "/system-admin" }), "system");
  });

  test("routes customer public entry without exposing the admin shell", () => {
    assert.deepEqual(resolveAdminRoute({ workspace: "customer", pathname: "/", authed: false }), {
      surface: "customer-landing",
      requiresAuth: false
    });
    assert.deepEqual(resolveAdminRoute({ workspace: "customer", pathname: "/login", authed: false }), {
      surface: "customer-login",
      requiresAuth: false
    });
    assert.deepEqual(resolveAdminRoute({ workspace: "customer", pathname: "/admin", authed: false }), {
      surface: "customer-login",
      requiresAuth: true,
      redirectTo: "/login"
    });
    assert.deepEqual(resolveAdminRoute({ workspace: "customer", pathname: "/admin", authed: true }), {
      surface: "customer-admin",
      requiresAuth: true
    });
  });

  test("keeps auth refresh endpoints separated by workspace", () => {
    assert.equal(authMePathForWorkspace("customer"), "/v1/admin/auth/me");
    assert.equal(authMePathForWorkspace("system"), "/v1/system-admin/auth/me");
  });
});
