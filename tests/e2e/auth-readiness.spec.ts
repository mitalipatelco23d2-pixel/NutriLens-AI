import { expect, test, type Page } from "@playwright/test";

const ready = {
  google: "READY",
  google_client_id: "test-client.apps.googleusercontent.com",
  email: "READY",
  phone_otp: "BLOCKED_EXTERNAL_COST",
};
const providerURL = "https://accounts.google.com/gsi/client";
const providerStub = `window.google = { accounts: { id: {
  initialize(options) { this.callback = options.callback; },
  renderButton(element) {
    const button = document.createElement('button');
    button.textContent = 'Google test provider';
    button.onclick = () => this.callback({ credential: 'synthetic-test-credential' });
    element.replaceChildren(button);
  }
} } };`;

test("a stalled Google script has a bounded loading state", async ({
  page,
}) => {
  await page.clock.install();
  await stubCapabilities(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(providerURL, async (route) => {
    await gate;
    await route.abort().catch(() => {});
  });
  // A stalled third-party script can keep the load event pending.
  await page.goto("/login", { waitUntil: "domcontentloaded" });
  try {
    await expect(page.getByText("Loading Google sign-in…")).toBeVisible();
    await page.clock.fastForward(15_001);
    await expect(
      page.getByRole("button", { name: "Reload Google sign-in" }),
    ).toBeVisible();
    await expect(page.getByText(/not configured|OAuth client ID/)).toHaveCount(
      0,
    );
  } finally {
    release();
  }
});

test("provider login failure remains distinct from configuration failure", async ({
  page,
}) => {
  await stubCapabilities(page);
  await stubProvider(page);
  await page.route("**/api/auth/google", (route) =>
    route.fulfill({ status: 401, json: { error: "Test rejection" } }),
  );
  await page.goto("/login");
  await page.getByRole("button", { name: "Google test provider" }).click();
  await expect(page.locator(".account-auth").getByRole("alert")).toHaveText(
    "Sign-in could not be completed.",
  );
  await expect(page.getByText(/not configured|OAuth client ID/)).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeEnabled();
});

async function stubProvider(page: Page) {
  await page.route(providerURL, (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: providerStub,
    }),
  );
}

async function stubCapabilities(page: Page, payload: unknown = ready) {
  await page.route("**/api/auth/capabilities", (route) =>
    route.fulfill({ json: payload }),
  );
}

test("slow capabilities show loading, never a false configuration warning", async ({
  page,
}) => {
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await stubProvider(page);
  await page.route("**/api/auth/capabilities", async (route) => {
    await gate;
    await route.fulfill({ json: ready });
  });
  await page.goto("/login");
  try {
    await expect(page.getByRole("status")).toHaveText(
      "Loading sign-in options…",
    );
    await expect(page.getByText(/not configured|OAuth client ID/)).toHaveCount(
      0,
    );
  } finally {
    release();
  }
  await expect(
    page.getByRole("button", { name: "Google test provider" }),
  ).toBeVisible();
  await expect(page.getByText("Loading sign-in options…")).toHaveCount(0);
});

test("temporary capability failure retries without erasing the email form", async ({
  page,
}) => {
  let requests = 0;
  await stubProvider(page);
  await page.route("**/api/auth/capabilities", (route) => {
    requests += 1;
    return route.fulfill(
      requests === 1
        ? { status: 503, json: { error: "Temporarily unavailable" } }
        : { json: ready },
    );
  });
  await page.goto("/login");
  await expect(page.locator(".account-auth").getByRole("alert")).toHaveText(
    "Sign-in options could not be loaded. Please retry.",
  );
  await expect(page.getByText(/not configured|OAuth client ID/)).toHaveCount(0);
  await page.getByLabel("Email address").fill("retry-fixture@example.test");
  await page.getByRole("button", { name: "Retry sign-in options" }).click();
  await expect(
    page.getByRole("button", { name: "Google test provider" }),
  ).toBeVisible();
  await expect(page.getByLabel("Email address")).toHaveValue(
    "retry-fixture@example.test",
  );
  expect(requests).toBe(2);
});

test("a hanging capability request ends with a retry, not missing configuration", async ({
  page,
}) => {
  await page.clock.install();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/auth/capabilities", async (route) => {
    await gate;
    await route.abort().catch(() => {});
  });
  await page.goto("/login");
  try {
    await expect(page.getByText("Loading sign-in options…")).toBeVisible();
    await page.clock.fastForward(15_001);
    await expect(
      page.getByRole("button", { name: "Retry sign-in options" }),
    ).toBeVisible();
    await expect(page.getByText(/not configured|OAuth client ID/)).toHaveCount(
      0,
    );
  } finally {
    release();
  }
});

test("only explicit unavailable capabilities produce a configuration message", async ({
  page,
}) => {
  let providerRequests = 0;
  await page.route(providerURL, (route) => {
    providerRequests += 1;
    return route.abort();
  });
  await stubCapabilities(page, {
    ...ready,
    google: "NOT_CONFIGURED",
    google_client_id: null,
  });
  await page.goto("/login");
  await expect(
    page.getByText("Google sign-in is not configured for this site."),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Sign in", exact: true }),
  ).toBeEnabled();
  expect(providerRequests).toBe(0);
});

test("a malformed capability payload offers retry instead of a configuration claim", async ({
  page,
}) => {
  await stubCapabilities(page, { ...ready, google_client_id: null });
  await page.goto("/login");
  await expect(
    page.getByRole("button", { name: "Retry sign-in options" }),
  ).toBeVisible();
  await expect(page.getByText(/not configured|OAuth client ID/)).toHaveCount(0);
});

test("Google script failure offers reload and recovers without a configuration claim", async ({
  page,
}) => {
  await stubCapabilities(page);
  await page.route(providerURL, (route) => route.abort());
  await page.goto("/login");
  await expect(
    page.getByRole("button", { name: "Reload Google sign-in" }),
  ).toBeVisible();
  await expect(page.getByText(/not configured|OAuth client ID/)).toHaveCount(0);
  await page.unroute(providerURL);
  await stubProvider(page);
  await page.getByRole("button", { name: "Reload Google sign-in" }).click();
  await expect(
    page.getByRole("button", { name: "Google test provider" }),
  ).toBeVisible();
});

test("Google initializes again after client navigation with its script already cached", async ({
  page,
}) => {
  let providerRequests = 0;
  await stubCapabilities(page);
  await page.route(providerURL, (route) => {
    providerRequests += 1;
    return route.fulfill({
      contentType: "application/javascript",
      body: providerStub,
    });
  });
  await page.goto("/login");
  await expect(
    page.getByRole("button", { name: "Google test provider" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "NutriLens X", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Start scanning", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Start scanning", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Google test provider" }),
  ).toBeVisible();
  expect(providerRequests).toBe(1);
});

test("a loaded script missing Google's API is a provider error, not configuration", async ({
  page,
}) => {
  await stubCapabilities(page);
  await page.route(providerURL, (route) =>
    route.fulfill({
      contentType: "application/javascript",
      body: "/* no provider */",
    }),
  );
  await page.goto("/login");
  await expect(
    page.getByRole("button", { name: "Reload Google sign-in" }),
  ).toBeVisible();
  await expect(page.getByText(/not configured|OAuth client ID/)).toHaveCount(0);
});

test("email signup requires and submits explicit legal acceptance", async ({
  page,
}) => {
  await stubCapabilities(page);
  await stubProvider(page);
  let signupBody: unknown;
  await page.route("**/api/auth/email/signup", async (route) => {
    signupBody = route.request().postDataJSON();
    await route.fulfill({
      status: 202,
      json: { message: "Check your inbox to verify your email." },
    });
  });
  await page.goto("/login");
  await page.getByRole("button", { name: "Create account" }).click();
  await page.getByLabel("Name").fill("Legal Owner");
  await page.getByLabel("Email address").fill("legal-owner@example.test");
  await page.getByLabel("Password").fill("Strong-password-42!");
  const submit = page.getByRole("button", { name: "Create account" });
  await expect(submit).toBeDisabled();
  await expect(
    page.getByRole("link", { name: "Terms of Use" }),
  ).toHaveAttribute("href", "/terms");
  await expect(
    page.locator("form").getByRole("link", { name: "Privacy Policy" }),
  ).toHaveAttribute("href", "/privacy");
  await page.getByRole("checkbox").check();
  await submit.click();
  await expect(
    page.getByText("Check your inbox to verify your email."),
  ).toBeVisible();
  expect(signupBody).toMatchObject({
    accepted_terms: true,
    accepted_privacy: true,
  });
});
