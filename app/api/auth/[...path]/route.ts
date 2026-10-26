import { cookies } from "next/headers";

import {
  backendBaseUrl,
  sessionCookieName,
  setSessionCookie,
} from "@/lib/auth-session";
import {
  isSameOriginMutation,
  readBoundedRequestBody,
  RequestBodyTooLargeError,
} from "@/lib/request-security";

export const dynamic = "force-dynamic";

const publicActions = new Set([
  "capabilities",
  "email/signup",
  "email/login",
  "email/verify",
  "email/resend-verification",
  "password/forgot",
  "password/reset",
  "phone/request",
  "phone/verify",
]);

const authenticatedActions = new Set(["password/change", "session/refresh"]);

function authJson(body: unknown, init: ResponseInit) {
  return Response.json(body, {
    ...init,
    headers: { "Cache-Control": "no-store" },
  });
}

async function handle(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const action = path.join("/");
  if (!publicActions.has(action) && !authenticatedActions.has(action)) {
    return authJson(
      { error: "Unsupported authentication route." },
      { status: 404 },
    );
  }
  if (request.method !== "GET" && !isSameOriginMutation(request)) {
    return authJson(
      { error: "Cross-origin authentication rejected." },
      { status: 403 },
    );
  }

  const headers = new Headers({
    Accept: "application/json",
  });
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);

  if (authenticatedActions.has(action)) {
    const session = (await cookies()).get(sessionCookieName)?.value;
    if (!session) {
      return authJson({ error: "Authentication required." }, { status: 401 });
    }
    headers.set("Authorization", `Bearer ${session}`);
  }

  try {
    const body = await readBoundedRequestBody(request, 64 * 1024);
    const response = await fetch(
      `${backendBaseUrl()}/api/v1/auth/${path.map(encodeURIComponent).join("/")}`,
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
      },
    );
    const text = await response.text();
    const payload = text ? (JSON.parse(text) as Record<string, unknown>) : {};
    if (response.ok && typeof payload.access_token === "string") {
      await setSessionCookie(
        payload.access_token,
        Number(payload.expires_in_seconds ?? 1800),
      );
      return authJson({ user: payload.user }, { status: response.status });
    }
    return authJson(payload, { status: response.status });
  } catch (error) {
    if (error instanceof RequestBodyTooLargeError) {
      return authJson({ error: "Request body is too large." }, { status: 413 });
    }
    return authJson(
      { error: "Authentication service is temporarily unavailable." },
      { status: 502 },
    );
  }
}

export const GET = handle;
export const POST = handle;
