import { cookies } from "next/headers";
import { backendBaseUrl, sessionCookieName } from "@/lib/auth-session";
import { isSameOriginMutation } from "@/lib/request-security";

export async function POST(request: Request) {
  if (!isSameOriginMutation(request)) {
    return Response.json(
      { error: "Cross-origin logout rejected." },
      { status: 403 },
    );
  }
  const store = await cookies();
  const session = store.get(sessionCookieName)?.value;
  if (session) {
    await fetch(`${backendBaseUrl()}/api/v1/auth/logout`, {
      method: "POST",
      headers: { Authorization: `Bearer ${session}` },
      cache: "no-store",
    }).catch(() => undefined);
  }
  store.delete(sessionCookieName);
  return new Response(null, { status: 204 });
}
