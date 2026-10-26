import { backendBaseUrl, setSessionCookie } from "@/lib/auth-session";
import { isSameOriginMutation } from "@/lib/request-security";

export async function POST(request: Request) {
  if (!isSameOriginMutation(request)) {
    return Response.json(
      { error: "Cross-origin authentication rejected." },
      { status: 403 },
    );
  }
  const response = await fetch(`${backendBaseUrl()}/api/v1/auth/google`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
    cache: "no-store",
  });
  if (!response.ok)
    return Response.json(
      { error: "Authentication failed." },
      { status: response.status },
    );
  const session = (await response.json()) as {
    access_token: string;
    expires_in_seconds: number;
    user: unknown;
  };
  await setSessionCookie(session.access_token, session.expires_in_seconds);
  return Response.json({ user: session.user });
}
