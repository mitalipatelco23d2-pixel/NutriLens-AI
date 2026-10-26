import { describe, expect, it, vi } from "vitest";

import { refreshBrowserSession } from "../lib/session-keepalive";

describe("browser session refresh", () => {
  it("rotates the HttpOnly session through the same-origin route", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }));

    await expect(refreshBrowserSession(fetcher)).resolves.toBe("refreshed");
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith("/api/auth/session/refresh", {
      method: "POST",
      cache: "no-store",
    });
  });

  it("accepts a cookie already rotated by another browser tab", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(Response.json({ id: "owner-1" }));

    await expect(refreshBrowserSession(fetcher)).resolves.toBe("current");
    expect(fetcher).toHaveBeenNthCalledWith(2, "/api/backend/auth/me", {
      cache: "no-store",
    });
  });

  it("distinguishes expiry from a temporary backend failure", async () => {
    const expired = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(new Response(null, { status: 401 }));
    const unavailable = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 503 }));

    await expect(refreshBrowserSession(expired)).resolves.toBe("expired");
    await expect(refreshBrowserSession(unavailable)).resolves.toBe(
      "unavailable",
    );
  });
});
