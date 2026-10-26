import { describe, expect, it } from "vitest";
import {
  knownTotal,
  nutrientText,
  servingText,
} from "../lib/nutrient-evidence";

describe("nullable diary nutrition evidence", () => {
  it("keeps missing and non-finite evidence distinct from a measured zero", () => {
    expect(nutrientText(null, "kcal")).toBe("Unknown");
    expect(nutrientText(undefined, "g")).toBe("Unknown");
    expect(nutrientText(Number.NaN, "g")).toBe("Unknown");
    expect(nutrientText(0, "g")).toBe("0 g");
    expect(nutrientText(12.56, "mg")).toBe("12.6 mg");
  });
  it("makes aggregates unknown if any contributing record is unknown", () => {
    expect(knownTotal([100, null, 0])).toBeNull();
    expect(knownTotal([100, undefined])).toBeNull();
    expect(knownTotal([0, 0])).toBe(0);
    expect(knownTotal([100, 25])).toBe(125);
  });
  it("does not invent a recipe serving mass", () => {
    expect(servingText({ serving_grams: null, recipe_servings: 2.5 })).toBe(
      "2.5 recipe servings",
    );
    expect(servingText({ serving_grams: null, recipe_servings: 1 })).toBe(
      "1 recipe serving",
    );
    expect(servingText({ serving_grams: null })).toBe("Serving mass unknown");
    expect(servingText({ serving_grams: 125 })).toBe("125 g");
  });
});
