import { cookies } from "next/headers";
import {
  isSameOriginMutation,
  readBoundedRequestBody,
  RequestBodyTooLargeError,
} from "@/lib/request-security";

export const dynamic = "force-dynamic";

const allowedRoots = new Set([
  "account",
  "analytics",
  "assistant",
  "auth",
  "diary",
  "hydration",
  "ingredient-intelligence",
  "knowledge",
  "notifications",
  "pantry",
  "payments",
  "population",
  "profile",
  "recommendations",
  "recipes",
  "research",
  "scan",
  "shopping-list",
  "subscriptions",
  "system",
  "weight",
]);

async function proxy(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  if (!path.length || !allowedRoots.has(path[0])) {
    return Response.json({ error: "Unsupported API route." }, { status: 404 });
  }

  const incoming = new URL(request.url);
  if (!isSameOriginMutation(request)) {
    return Response.json(
      { error: "Cross-origin mutation rejected." },
      { status: 403 },
    );
  }

  const session = (await cookies()).get("nutrilens_session")?.value;
  if (!session) {
    return Response.json(
      { error: "Authentication required." },
      { status: 401 },
    );
  }

  const backendUrl = (
    process.env.BACKEND_INTERNAL_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    "http://localhost:8000"
  ).replace(/\/$/, "");
  const target = `${backendUrl}/api/v1/${path.map(encodeURIComponent).join("/")}${incoming.search}`;
  const headers = new Headers({
    Accept: request.headers.get("accept") ?? "application/json",
    Authorization: `Bearer ${session}`,
  });
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const idempotencyKey = request.headers.get("idempotency-key");
  if (idempotencyKey) headers.set("Idempotency-Key", idempotencyKey);

  try {
    const maximumBytes =
      path[0] === "scan" ? 52 * 1024 * 1024 : 2 * 1024 * 1024;
    const body = await readBoundedRequestBody(request, maximumBytes);
    const response = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
    });
    const responseHeaders = new Headers({
      "Content-Type":
        response.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store",
    });
    for (const header of [
      "content-disposition",
      "x-request-id",
      "x-ratelimit-limit",
      "x-ratelimit-remaining",
      "retry-after",
    ]) {
      const value = response.headers.get(header);
      if (value) responseHeaders.set(header, value);
    }
    return new Response(response.body, {
      status: response.status,
      headers: responseHeaders,
    });
  } catch (error) {
    if (error instanceof RequestBodyTooLargeError) {
      return Response.json(
        { error: "Request body is too large." },
        { status: 413 },
      );
    }
    return Response.json(
      { error: "NutriLens API is temporarily unavailable." },
      { status: 502 },
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
