import { expect, test } from "@playwright/test";

// Contract fixture only: this is UI verification, not a production OCR benchmark.
const scan = {
  scan_id: "ui-contract-scan",
  trace_id: "ui-contract-trace",
  status: "COMPLETED_WITH_WARNINGS",
  input_kind: "PACKAGED_PRODUCT",
  image_quality: {},
  regions: [],
  barcode_results: [],
  qr_results: [],
  ocr_results: {
    general: {
      selected_engine: "PADDLEOCR",
      text: "RAW_CONTRACT_OCR_NOT_PRIMARY",
      confidence: 0.91,
      confidence_level: "HIGH",
      fallback_reason: null,
      attempts: [{ engine: "PADDLEOCR", status: "SUCCESS" }],
    },
  },
  nutrition: {
    raw_table_text: "Nutrition table",
    basis: "PER_100_ML",
    confidence: 0.8,
    table_columns: ["PER_100_ML", "PER_SERVING"],
    serving_size_value: "200",
    serving_size_unit: "ml",
    table_rows: [{ label: "protein", values: ["3", "6"], units: ["g", "g"] }],
  },
  ingredients: {
    raw_text: "Milk, cocoa",
    allergen_text: "MILK",
    confidence: 0.8,
    allergen_confidence: 0.9,
  },
  brand_candidates: [
    { value: "Fixture brand", confidence: 0.8, method: "OCR" },
  ],
  product_name_candidates: [
    { value: "Cocoa drink", confidence: 0.8, method: "OCR" },
  ],
  category_candidates: [],
  date_candidates: [],
  meal_items: [],
  portion_estimates: [],
  confidence_summary: { level: "MEDIUM", numeric_score: 0.7, explanation: [] },
  warnings: ["CONTRACT_DIAGNOSTIC_ONLY"],
  manual_review_fields: [],
  corrections: [],
  timings: { total_ms: 1234 },
  images_retained: false,
};

for (const allergenStatement of [
  "Contains: MILK",
  "May contain milk",
  "Free from milk",
  "Contains no milk",
  "MILK",
]) {
  test(`owner result preserves "${allergenStatement}" and carries Ask context`, async ({
    page,
  }) => {
    let assistantScanId: string | undefined;
    const unexpected: string[] = [];
    await page.route("**/api/backend/**", async (route) => {
      const request = route.request();
      const path = new URL(request.url()).pathname.replace("/api/backend", "");
      let payload: unknown;
      let status = 200;
      if (path === "/auth/me") {
        payload = {
          id: "fixture-owner",
          email: "fixture@example.invalid",
          name: "Fixture",
          avatar_url: null,
          plan: "FREE",
          subscription_status: "FREE",
        };
      } else if (path === "/hydration") {
        payload = {
          day: new URL(request.url()).searchParams.get("day"),
          timezone_offset_minutes: 0,
          target_ml: null,
          total_ml: 0,
          remaining_ml: null,
          entries: [],
        };
      } else if (path === "/analytics/summary") {
        payload = {
          diary_entries: 0,
          period_days: 1,
          daily_averages: {},
          insights: [],
          goal_tracking_state: "NOT_CONFIGURED",
          goal_progress: [],
        };
      } else if (path === "/notifications" || path === "/favorites") {
        payload = [];
      } else if (path === "/weight") {
        payload = {
          state: "DISABLED",
          target_weight_kg: null,
          latest_weight_kg: null,
          change_from_first_kg: null,
          difference_from_target_kg: null,
          entries: [],
          method: "SELF_REPORTED_WEIGHT_DIFFERENCE_V1",
          limitation: "Descriptive self-reported records only.",
        };
      } else if (path === "/scan/history") {
        payload = [
          {
            scan_id: scan.scan_id,
            product_name: "Cocoa drink",
            brand: "Fixture brand",
            input_kind: "PACKAGED_PRODUCT",
            created_at: "2026-09-01T12:00:00Z",
            confidence: 0.7,
          },
        ];
      } else if (path === `/scan/${scan.scan_id}`) {
        payload = {
          ...scan,
          insights: {
            highlights: ["Protein: 3 g per 100 ml."],
            positive_signals: [],
            things_to_watch: [],
            allergen_summary: null,
            serving_context: null,
            structured_highlights: [],
            ask_nutri_suggestions: ["Explain this scan."],
          },
          ingredients: {
            ...scan.ingredients,
            allergen_text: allergenStatement,
          },
        };
      } else if (
        path.startsWith("/ingredient-intelligence/") ||
        path.includes("/counterfactuals")
      ) {
        status = 503;
        payload = { detail: "Optional explanation temporarily unavailable" };
      } else if (path === "/assistant/messages") {
        assistantScanId = request.postDataJSON().scan_id;
        payload = {
          answer: "Review the package allergen statement.",
          remaining_today: 3,
          citations: [],
        };
      } else {
        unexpected.push(path);
        status = 404;
        payload = {};
      }
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(payload),
      });
    });
    await page.goto("/dashboard");
    await page
      .getByRole("button", { name: "Scan history", exact: true })
      .click();
    await page.getByRole("button", { name: "Open", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Cocoa drink", exact: true }),
    ).toBeVisible();
    await expect(
      page.locator(".r3-summary").getByText("Fixture brand", { exact: true }),
    ).toBeVisible();
    await expect(
      page.locator(".explicit-allergen").getByRole("heading", {
        name: allergenStatement,
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByRole("table")).toBeVisible();
    await expect(
      page.getByRole("cell", { name: "3 g", exact: true }),
    ).toBeVisible();
    await expect(page.getByText("RAW_CONTRACT_OCR_NOT_PRIMARY")).toBeHidden();
    await expect(
      page.getByText("CONTRACT_DIAGNOSTIC_ONLY", { exact: false }),
    ).toBeHidden();
    await page.getByText("OCR and processing details", { exact: true }).click();
    await expect(page.getByText("RAW_CONTRACT_OCR_NOT_PRIMARY")).toBeVisible();
    await page
      .getByRole("button", { name: "Explain this scan.", exact: false })
      .click();
    await expect(
      page.getByPlaceholder("Ask about food, ingredients or your goals…"),
    ).toHaveValue("Explain this scan.");
    await page
      .getByPlaceholder("Ask about food, ingredients or your goals…")
      .press("Enter");
    await expect(
      page.getByText(/Review the package allergen statement/),
    ).toBeVisible();
    expect(assistantScanId).toBe(scan.scan_id);
    expect(unexpected).toEqual([]);
  });
}
