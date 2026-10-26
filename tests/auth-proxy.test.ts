import { afterEach, describe, expect, it, vi } from "vitest";

const authMocks = vi.hoisted(() => ({
  session: undefined as string | undefined,
  setSessionCookie: vi.fn(),
}));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: () =>
      authMocks.session === undefined
        ? undefined
        : { value: authMocks.session },
  }),
}));
vi.mock("@/lib/auth-session", () => ({
  backendBaseUrl: () => "https://backend.example.test",
  sessionCookieName: "test_session",
  setSessionCookie: authMocks.setSessionCookie,
}));
vi.mock("@/lib/request-security", () => import("../lib/request-security"));

import { GET, POST } from "../app/api/auth/[...path]/route";

const capabilitiesContext = {
  params: Promise.resolve({ path: ["capabilities"] }),
};
afterEach(() => {
  authMocks.session = undefined;
  authMocks.setSessionCookie.mockReset();
  vi.unstubAllGlobals();
});

describe("auth proxy does not cache configuration or errors", () => {
  it.each([200, 503])(
    "preserves status %i and explicitly disables caching",
    async (status) => {
      const upstream = vi
        .fn()
        .mockResolvedValue(Response.json({ google: "READY" }, { status }));
      vi.stubGlobal("fetch", upstream);
      const response = await GET(
        new Request("https://nutrilens.example.test/api/auth/capabilities"),
        capabilitiesContext,
      );
      expect(response.status).toBe(status);
      expect(response.headers.get("Cache-Control")).toBe("no-store");
      expect(upstream).toHaveBeenCalledWith(
        "https://backend.example.test/api/v1/auth/capabilities",
        expect.objectContaining({ cache: "no-store" }),
      );
    },
  );
  it("does not cache a network failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    const response = await GET(
      new Request("https://nutrilens.example.test/api/auth/capabilities"),
      capabilitiesContext,
    );
    expect(response.status).toBe(502);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });
  it("keeps the cross-origin auth protection", async () => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    const response = await POST(
      new Request("https://nutrilens.example.test/api/auth/email/login", {
        method: "POST",
        headers: { origin: "https://foreign.example.test" },
        body: "{}",
      }),
      { params: Promise.resolve({ path: ["email", "login"] }) },
    );
    expect(response.status).toBe(403);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(upstream).not.toHaveBeenCalled();
  });
  it("rotates an authenticated session without exposing its token", async () => {
    authMocks.session = "old-session";
    const upstream = vi.fn().mockResolvedValue(
      Response.json({
        access_token: "new-session",
        expires_in_seconds: 1800,
        user: { id: "owner-1" },
      }),
    );
    vi.stubGlobal("fetch", upstream);

    const response = await POST(
      new Request("https://nutrilens.example.test/api/auth/session/refresh", {
        method: "POST",
        headers: { origin: "https://nutrilens.example.test" },
      }),
      { params: Promise.resolve({ path: ["session", "refresh"] }) },
    );

    const upstreamInit = upstream.mock.calls[0]?.[1] as RequestInit;
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ user: { id: "owner-1" } });
    expect(new Headers(upstreamInit.headers).get("Authorization")).toBe(
      "Bearer old-session",
    );
    expect(authMocks.setSessionCookie).toHaveBeenCalledWith(
      "new-session",
      1800,
    );
  });
});
