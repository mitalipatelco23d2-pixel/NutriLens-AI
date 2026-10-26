export type BrowserSessionRefreshResult =
  "refreshed" | "current" | "expired" | "unavailable";

export async function refreshBrowserSession(
  fetcher: typeof fetch = fetch,
): Promise<BrowserSessionRefreshResult> {
  const response = await fetcher("/api/auth/session/refresh", {
    method: "POST",
    cache: "no-store",
  });
  if (response.ok) return "refreshed";
  if (response.status !== 401) return "unavailable";

  // Another tab can rotate the shared HttpOnly cookie while this request is
  // waiting. Probe the current cookie before treating a refresh 401 as expiry.
  const current = await fetcher("/api/backend/auth/me", {
    cache: "no-store",
  });
  if (current.ok) return "current";
  return current.status === 401 ? "expired" : "unavailable";
}
