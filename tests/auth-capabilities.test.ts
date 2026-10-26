import { describe, expect, it } from "vitest";
import { parseAuthCapabilities } from "../lib/auth-capabilities";

const ready = {
  google: "READY",
  google_client_id: "test-client.apps.googleusercontent.com",
  email: "READY",
  phone_otp: "BLOCKED_EXTERNAL_COST",
};

describe("public authentication capability validation", () => {
  it("accepts configured runtime capability data without inventing an ID", () => {
    expect(parseAuthCapabilities(ready)).toEqual(ready);
  });
  it("accepts an explicitly unavailable provider", () => {
    expect(
      parseAuthCapabilities({
        ...ready,
        google: "NOT_CONFIGURED",
        google_client_id: null,
      }).google,
    ).toBe("NOT_CONFIGURED");
  });
  it.each([
    null,
    [],
    {},
    { error: "Temporarily unavailable" },
    { ...ready, google_client_id: null },
    { ...ready, google_client_id: "  " },
    { ...ready, google_client_id: 123 },
    { ...ready, google: "NOT_CONFIGURED" },
    { ...ready, google: ["READY"] },
    { ...ready, email: ["READY"] },
    { ...ready, phone_otp: {} },
  ])(
    "rejects incomplete or contradictory data rather than reporting missing configuration: %j",
    (payload) => {
      expect(() => parseAuthCapabilities(payload)).toThrow();
    },
  );
});
