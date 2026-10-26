import { describe, expect, it } from "vitest";

import { pantry, products, weeklyNutrition } from "./data";

describe("NutriLens demonstration data", () => {
  it("keeps product scores inside the documented range", () => {
    expect(products.length).toBeGreaterThan(0);
    expect(products.every((product) => product.score >= 0 && product.score <= 100)).toBe(true);
  });

  it("contains a complete demonstration week", () => {
    expect(weeklyNutrition).toHaveLength(7);
  });

  it("provides pantry data for the R0 interaction scaffold", () => {
    expect(pantry.length).toBeGreaterThanOrEqual(3);
  });
});
