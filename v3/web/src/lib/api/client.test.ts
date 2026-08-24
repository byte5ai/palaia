/**
 * The API client's half of the admin session gate (SPEC-401).
 *
 * Two obligations, both invisible in a screenshot and both load-bearing:
 * every state-changing call carries the double-submit token the hub
 * requires, and a session that has expired mid-use costs exactly one
 * redirect to the sign-in page.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, resetSignInRedirect } from "./client";

const CSRF_HEADER = "X-Palaia-CSRF";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

function headersOf(call: unknown[]): Record<string, string> {
  const init = call[1] as RequestInit;
  return (init.headers ?? {}) as Record<string, string>;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  document.cookie = "palaia_oauth_csrf=token-from-the-cookie";
  fetchMock = vi.fn(async () => jsonResponse({ ok: true }));
  vi.stubGlobal("fetch", fetchMock);
  resetSignInRedirect();
});

afterEach(() => {
  document.cookie = "palaia_oauth_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the double-submit token", () => {
  it("travels with every state-changing call", async () => {
    await api.createVault({ key: "work" });
    await api.updateAutomation("a1", { name: "renamed" });
    await api.setHookEnabled("h1", false);
    await api.revokeToken("t1");
    await api.uninstallAddon("u1");
    await api.deleteGatewayProfile("default");

    expect(fetchMock).toHaveBeenCalledTimes(6);
    for (const call of fetchMock.mock.calls) {
      const init = call[1] as RequestInit;
      expect(["POST", "PUT", "PATCH", "DELETE"]).toContain(init.method);
      expect(headersOf(call)[CSRF_HEADER]).toBe("token-from-the-cookie");
    }
  });

  it("is left off reads, which the hub does not ask for it on", async () => {
    await api.listVaults();
    await api.health();

    for (const call of fetchMock.mock.calls) {
      expect(headersOf(call)[CSRF_HEADER]).toBeUndefined();
    }
  });

  it("is simply absent when the browser has no token yet", async () => {
    document.cookie = "palaia_oauth_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";

    await api.createVault({ key: "work" });

    expect(headersOf(fetchMock.mock.calls[0])[CSRF_HEADER]).toBeUndefined();
  });
});

describe("a session that expired mid-use", () => {
  it("sends the browser to the sign-in page the hub names, once", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", {
      pathname: "/explorer",
      search: "?vault=work",
      assign,
    });
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "Please sign in to continue.", sign_in_url: "/oauth/login" }, 401),
    );

    await expect(api.listVaults()).rejects.toBeInstanceOf(ApiError);
    await expect(api.listNotes("work")).rejects.toBeInstanceOf(ApiError);

    expect(assign).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledWith(
      "/oauth/login?next=%2Fexplorer%3Fvault%3Dwork",
    );
  });

  it("bounces the shell to sign-in even when only the session probe fails", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/", search: "", assign });
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: "Please sign in.", sign_in_url: "/oauth/login" }, 401),
    );

    // A hub with the gate off answers 200 here, so a 401 means exactly
    // "this hub wants a session and this browser has none".
    await expect(api.session()).rejects.toBeInstanceOf(ApiError);

    expect(assign).toHaveBeenCalledWith("/oauth/login?next=%2F");
  });

  it("leaves a refused request alone when the hub names no sign-in page", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { pathname: "/", search: "", assign });
    fetchMock.mockResolvedValue(jsonResponse({ detail: "nope" }, 401));

    await expect(api.listVaults()).rejects.toBeInstanceOf(ApiError);

    expect(assign).not.toHaveBeenCalled();
  });
});

describe("signing out", () => {
  it("posts to the sign-in flow's own endpoint", async () => {
    await api.signOut();

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/oauth/logout");
    expect(init.method).toBe("POST");
  });
});
