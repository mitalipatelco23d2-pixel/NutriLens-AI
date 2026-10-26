import { expect, test } from "@playwright/test";

test("public visitor can move from the landing page to sign-in", async ({
  page,
}) => {
  // This local/CI journey has no auth backend. Explicitly model an unavailable
  // provider; a failed capability request must not masquerade as configuration.
  await page.route("**/api/auth/capabilities", (route) =>
    route.fulfill({
      json: {
        google: "NOT_CONFIGURED",
        google_client_id: null,
        email: "READY",
        phone_otp: "BLOCKED_EXTERNAL_COST",
      },
    }),
  );
  await page.goto("/");

  await expect(
    page.getByRole("heading", {
      level: 1,
      name: /Understand what you.re really eating/i,
    }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Start scanning" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Your food choices deserve better context.",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("Google sign-in is not configured for this site."),
  ).toBeVisible();
});

test("private dashboard sends an unauthenticated visitor to sign-in", async ({
  page,
}) => {
  await page.route("**/api/backend/auth/me", (route) =>
    route.fulfill({
      status: 401,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Authentication required." }),
    }),
  );
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/);
});

test("pricing exposes every finite consumer plan and interval", async ({
  page,
}) => {
  await page.goto("/pricing");

  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Core food safety stays free. Upgrade for depth.",
    }),
  ).toBeVisible();
  for (const plan of ["FREE", "PLUS", "PRO", "MAX"]) {
    await expect(
      page.getByRole("heading", { level: 2, name: plan, exact: true }),
    ).toBeVisible();
  }

  await page.getByRole("button", { name: /Yearly/ }).click();
  await expect(page.getByText("/year", { exact: true })).toHaveCount(4);
  await expect(
    page.getByText(/No literal unlimited AI inference/),
  ).toBeVisible();
  await expect(page.getByText(/No real or Test-mode payment/)).toBeVisible();
  await expect(page.getByRole("button", { name: /coming soon/ })).toHaveCount(
    3,
  );
});

test("public legal navigation remains reachable on a mobile viewport", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await page.getByRole("link", { name: "Privacy", exact: true }).click();
  await expect(page).toHaveURL(/\/privacy$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Privacy Policy" }),
  ).toBeVisible();

  await page.getByRole("link", { name: /NutriLens X/ }).click();
  await page.getByRole("link", { name: "Terms", exact: true }).click();
  await expect(page).toHaveURL(/\/terms$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Terms of Use" }),
  ).toBeVisible();
});

test("public product boundary is explicit and does not advertise a fabricated score", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("NLX score", { exact: true })).toHaveCount(0);
  await expect(
    page.getByText("observed signals", { exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "About", exact: true }).first().click();
  await expect(page).toHaveURL(/\/about$/);
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Food intelligence built around evidence and uncertainty.",
    }),
  ).toBeVisible();
  await expect(page.getByText(/not diagnosis, treatment/i)).toBeVisible();
});

test("payment-review policies are public while Live Mode remains gated", async ({
  page,
  request,
}) => {
  await page.goto("/shipping");
  await expect(
    page.getByRole("heading", { level: 1, name: "Shipping Policy" }),
  ).toBeVisible();
  await expect(page.getByText(/does not sell or ship food/i)).toBeVisible();

  await page.goto("/refunds");
  await expect(
    page.getByRole("heading", { level: 1, name: "Cancellation and Refunds" }),
  ).toBeVisible();
  await expect(
    page.getByText(/No real payment is currently accepted/i),
  ).toBeVisible();

  await page.goto("/contact");
  await expect(
    page.getByRole("heading", { level: 1, name: "Contact Us" }),
  ).toBeVisible();
  await expect(page.getByText(/pending public launch/i)).toBeVisible();

  const sitemap = await request.get("/sitemap.xml", { timeout: 10_000 });
  const sitemapText = await sitemap.text();
  expect(sitemapText).toContain("/refunds");
  expect(sitemapText).toContain("/shipping");
  const robots = await request.get("/robots.txt", { timeout: 10_000 });
  expect(await robots.text()).toContain("Disallow: /dashboard");
});
