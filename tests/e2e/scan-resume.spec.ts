import { expect, test } from "@playwright/test";

const completedScan = {
  scan_id: "resumed-scan",
  trace_id: "resumed-trace",
  status: "COMPLETED_WITH_WARNINGS",
  input_kind: "PACKAGED_PRODUCT",
  image_quality: {},
  regions: [],
  barcode_results: [],
  qr_results: [],
  ocr_results: {},
  nutrition: {
    raw_table_text: "Nutrition table",
    basis: "PER_100_ML",
    confidence: 0.8,
    table_columns: ["per 100 ml"],
    table_rows: [{ label: "protein", values: ["3.6"], units: ["g"] }],
  },
  ingredients: {
    raw_text: "Milk",
    allergen_text: "Contains milk",
    confidence: 0.8,
    allergen_confidence: 0.9,
  },
  brand_candidates: [],
  product_name_candidates: [
    { value: "Resumed milk", confidence: 0.8, method: "OCR" },
  ],
  category_candidates: [],
  date_candidates: [],
  meal_items: [],
  portion_estimates: [],
  confidence_summary: { level: "MEDIUM", numeric_score: 0.7, explanation: [] },
  warnings: [],
  manual_review_fields: [],
  corrections: [],
  timings: { total_ms: 1200 },
  images_retained: false,
};

test("a durable scan remains visible and completes after a hard refresh", async ({
  page,
}) => {
  let complete = false;
  await page.addInitScript(() => {
    window.sessionStorage.setItem("nutrilens-active-scan-job", "job-resume");
  });
  await page.route("**/api/backend/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace(
      "/api/backend",
      "",
    );
    let payload: unknown = [];
    if (path === "/auth/me") {
      payload = {
        id: "resume-owner",
        email: "resume@example.invalid",
        name: "Resume Owner",
        avatar_url: null,
        plan: "FREE",
        subscription_status: "FREE",
      };
    } else if (path === "/scan/jobs/job-resume") {
      payload = complete
        ? {
            job_id: "job-resume",
            status: "COMPLETE",
            result: completedScan,
            error_message: null,
          }
        : {
            job_id: "job-resume",
            status: "PREPROCESSING",
            result: null,
            error_message: null,
          };
    } else if (path === "/hydration") {
      payload = {
        day: "2026-09-06",
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
    } else if (
      path.startsWith("/ingredient-intelligence/") ||
      path.includes("/counterfactuals")
    ) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Optional explanation unavailable" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });

  await page.goto("/dashboard");
  await expect(page.getByRole("status")).toContainText("Preparing image");

  await page.reload();
  await expect(page.getByRole("status")).toContainText("Preparing image");
  await expect(page.getByText("uploading the image twice")).toBeVisible();

  complete = true;
  await expect(
    page.getByRole("heading", { name: "Resumed milk", exact: true }),
  ).toBeVisible({ timeout: 8_000 });
  await expect(
    page.getByText("Basis: PER_100_ML", { exact: false }),
  ).toBeVisible();
  await expect(
    page.evaluate(() =>
      window.sessionStorage.getItem("nutrilens-active-scan-job"),
    ),
  ).resolves.toBeNull();
});
