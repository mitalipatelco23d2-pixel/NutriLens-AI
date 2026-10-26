export type AuthCapabilities = {
  google: "READY" | "NOT_CONFIGURED";
  google_client_id: string | null;
  email: "READY" | "NOT_CONFIGURED";
  phone_otp: "READY" | "BLOCKED_EXTERNAL_COST";
};

// An incomplete/error response is not evidence that Google is unconfigured.
export function parseAuthCapabilities(value: unknown): AuthCapabilities {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Invalid authentication capabilities.");
  const payload = value as Record<string, unknown>;
  const clientId = payload.google_client_id;
  if (
    (payload.google !== "READY" && payload.google !== "NOT_CONFIGURED") ||
    (payload.email !== "READY" && payload.email !== "NOT_CONFIGURED") ||
    (payload.phone_otp !== "READY" &&
      payload.phone_otp !== "BLOCKED_EXTERNAL_COST") ||
    (payload.google === "READY"
      ? typeof clientId !== "string" || !clientId.trim()
      : clientId !== null && clientId !== undefined && clientId !== "")
  )
    throw new Error("Invalid authentication capabilities.");
  return {
    google: payload.google as AuthCapabilities["google"],
    google_client_id:
      typeof clientId === "string" ? clientId.trim() || null : null,
    email: payload.email as AuthCapabilities["email"],
    phone_otp: payload.phone_otp as AuthCapabilities["phone_otp"],
  };
}
