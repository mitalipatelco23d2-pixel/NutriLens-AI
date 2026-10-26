import { cookies } from "next/headers";

export const sessionCookieName = "nutrilens_session";

export function backendBaseUrl() {
  return (
    process.env.BACKEND_INTERNAL_URL ??
    process.env.NEXT_PUBLIC_API_URL ??
    "http://localhost:8000"
  ).replace(/\/$/, "");
}

export async function setSessionCookie(token: string, maxAge: number) {
  const store = await cookies();
  store.set(sessionCookieName, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge,
    priority: "high",
  });
}
