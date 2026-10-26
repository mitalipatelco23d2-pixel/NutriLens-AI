/** Diary evidence is nullable: an unrecorded amount is never an observed zero. */
export type NutrientSnapshot = Record<
  | "calories"
  | "protein_g"
  | "carbs_g"
  | "fat_g"
  | "sugar_g"
  | "sodium_mg"
  | "fiber_g"
  | "vitamin_a_mcg"
  | "vitamin_c_mg"
  | "vitamin_d_mcg"
  | "calcium_mg"
  | "iron_mg"
  | "potassium_mg"
  | "zinc_mg",
  number | null
>;

export function nutrientText(
  value: number | null | undefined,
  unit = "",
  digits = 1,
): string {
  return value == null || !Number.isFinite(value)
    ? "Unknown"
    : `${Number(value.toFixed(digits)).toLocaleString()}${unit ? ` ${unit}` : ""}`;
}

export function knownTotal(
  values: Array<number | null | undefined>,
): number | null {
  return values.reduce<number | null>(
    (total, value) =>
      total === null || value == null || !Number.isFinite(value)
        ? null
        : total + value,
    0,
  );
}

export function servingText(entry: {
  serving_grams: number | null;
  recipe_servings?: number | null;
}): string {
  if (entry.recipe_servings != null)
    return `${entry.recipe_servings} recipe serving${entry.recipe_servings === 1 ? "" : "s"}`;
  return entry.serving_grams == null
    ? "Serving mass unknown"
    : `${entry.serving_grams} g`;
}
