import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { middleware } from "../middleware";

describe("canonical www redirect", () => {
  it("preserves the complete path and query string", () => {
    const response = middleware(
      new NextRequest(
        "https://www.nutrilensx.tech/recipes/custom?source=saved&view=compact",
      ),
    );

    expect(response.status).toBe(308);
    expect(response.headers.get("location")).toBe(
      "https://nutrilensx.tech/recipes/custom?source=saved&view=compact",
    );
  });

  it("does not redirect the canonical host", () => {
    const response = middleware(
      new NextRequest("https://nutrilensx.tech/recipes/custom"),
    );

    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });
});
