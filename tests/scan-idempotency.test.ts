import { describe, expect, it } from "vitest";

import { scanIdempotencyKey } from "../lib/scan-idempotency";

describe("scanIdempotencyKey", () => {
  it("is stable for the same scan kind and image bytes", async () => {
    const bytes = new TextEncoder().encode("same label image").buffer;

    expect(await scanIdempotencyKey("product", bytes)).toBe(
      await scanIdempotencyKey("product", bytes),
    );
  });

  it("separates scan kinds and different image bytes", async () => {
    const first = new TextEncoder().encode("first image").buffer;
    const second = new TextEncoder().encode("second image").buffer;

    expect(await scanIdempotencyKey("product", first)).not.toBe(
      await scanIdempotencyKey("meal", first),
    );
    expect(await scanIdempotencyKey("product", first)).not.toBe(
      await scanIdempotencyKey("product", second),
    );
  });
});
