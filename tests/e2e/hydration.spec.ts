import { expect, Page, test } from "@playwright/test";

// Mocked API contract tests. Persistence/isolation in PostgreSQL is tested separately.
type Entry = {
  id: string;
  amount_ml: number;
  consumed_at: string;
  source: string;
};

async function mockHydration(page: Page) {
  const state = {
    target: null as number | null,
    entries: [] as Entry[],
    posts: [] as Array<{ id: string; amount_ml: number; consumed_at: string }>,
    queries: [] as URL[],
    failReads: false,
    loseNextPostResponse: false,
    failReadAfterPost: false,
    conflictNextPost: false,
    ownerId: "hydration-owner",
  };
  await page.route("**/api/backend/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/backend", "");
    let payload: unknown = [];
    let status = 200;
    if (path === "/auth/me") {
      payload = {
        id: state.ownerId,
        name: "Water fixture",
        email: "water@example.invalid",
        plan: "FREE",
        subscription_status: "FREE",
      };
    } else if (path === "/analytics/summary") {
      payload = {
        diary_entries: 0,
        daily_averages: {},
        insights: [],
        goal_tracking_state: "NOT_CONFIGURED",
        goal_progress: [],
      };
    } else if (path === "/hydration") {
      state.queries.push(url);
      if (state.failReads) {
        status = 503;
        payload = { detail: "Fixture read failure" };
      } else {
        const day = url.searchParams.get("day")!;
        const offset = Number(url.searchParams.get("timezone_offset_minutes"));
        const nextOffset = Number(
          url.searchParams.get("next_day_timezone_offset_minutes"),
        );
        const start = Date.parse(`${day}T00:00:00Z`) - offset * 60_000;
        const end =
          Date.parse(`${day}T00:00:00Z`) + 86_400_000 - nextOffset * 60_000;
        const entries = state.entries.filter(
          (entry) =>
            Date.parse(entry.consumed_at) >= start &&
            Date.parse(entry.consumed_at) < end,
        );
        const total = entries.reduce((sum, entry) => sum + entry.amount_ml, 0);
        payload = {
          day,
          timezone_offset_minutes: offset,
          target_ml: state.target,
          total_ml: total,
          remaining_ml:
            state.target === null ? null : Math.max(0, state.target - total),
          entries,
        };
      }
    } else if (path === "/hydration/target") {
      state.target = request.postDataJSON().target_ml;
      payload = { target_ml: state.target };
    } else if (path === "/hydration/entries") {
      const body = request.postDataJSON();
      state.posts.push(body);
      if (state.conflictNextPost) {
        state.conflictNextPost = false;
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({ detail: "Entry changed or deleted" }),
        });
        return;
      }
      let entry = state.entries.find((candidate) => candidate.id === body.id);
      if (!entry) {
        entry = { ...body, source: "USER_ENTERED" };
        state.entries.push(entry!);
        status = 201;
      }
      if (state.loseNextPostResponse) {
        state.loseNextPostResponse = false;
        await route.abort("failed");
        return;
      }
      if (state.failReadAfterPost) state.failReads = true;
      payload = entry;
    } else if (path.startsWith("/hydration/entries/")) {
      const id = path.split("/").at(-1);
      if (request.method() === "DELETE") {
        state.entries = state.entries.filter((entry) => entry.id !== id);
        await route.fulfill({ status: 204 });
        return;
      }
      const entry = state.entries.find((candidate) => candidate.id === id)!;
      Object.assign(entry, request.postDataJSON());
      payload = entry;
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
  return state;
}

async function openWater(page: Page) {
  await page.goto("/dashboard");
  await page
    .getByRole("button", { name: "Open water log", exact: true })
    .click();
  const panel = page.getByRole("region", { name: "Water log", exact: true });
  await expect(
    panel.getByRole("button", { name: "+250 ml", exact: true }),
  ).toBeEnabled();
  return panel;
}

test("water target and amounts persist after create, edit, delete and reload", async ({
  page,
}) => {
  const state = await mockHydration(page);
  const panel = await openWater(page);
  await expect(panel.getByText("No target set", { exact: true })).toBeVisible();
  await expect(
    panel.getByText("No water recorded for this day."),
  ).toBeVisible();
  await panel
    .getByText("Set or change your daily target", { exact: true })
    .click();
  await expect(panel.getByLabel("Daily water target (ml)")).toHaveValue("");
  await panel.getByLabel("Daily water target (ml)").fill("2000");
  await panel.getByRole("button", { name: "Save target", exact: true }).click();
  await expect(panel.getByRole("progressbar")).toHaveAttribute("max", "2000");
  for (const value of [250, 500]) {
    await panel
      .getByRole("button", { name: `+${value} ml`, exact: true })
      .click();
    await expect(
      panel.getByRole("button", {
        name: `Edit ${value} ml entry`,
        exact: true,
      }),
    ).toBeVisible();
  }
  await panel.getByLabel("Custom amount (ml)").fill("1250");
  await panel.getByRole("button", { name: "Add water", exact: true }).click();
  await expect(panel.getByRole("progressbar")).toHaveAttribute("value", "2000");
  await panel
    .getByRole("button", { name: "Edit 500 ml entry", exact: true })
    .click();
  await panel.getByLabel("Entry amount (ml)").fill("300");
  await panel.getByRole("button", { name: "Save entry", exact: true }).click();
  await expect(panel.getByRole("progressbar")).toHaveAttribute("value", "1800");
  expect(
    state.entries.find((entry) => entry.amount_ml === 300)?.consumed_at,
  ).toBe(state.posts[1].consumed_at);
  await expect(panel.getByText("200 ml", { exact: true })).toBeVisible();
  await panel
    .getByRole("button", { name: "Delete 250 ml entry", exact: true })
    .click();
  await expect(panel.getByRole("progressbar")).toHaveAttribute("value", "1550");
  await panel
    .getByRole("button", { name: "Clear target", exact: true })
    .click();
  await expect(panel.getByText("No target set", { exact: true })).toBeVisible();
  await expect(panel.getByRole("progressbar")).toHaveCount(0);
  await page.reload();
  await expect(
    page.getByRole("region", { name: "Today's water", exact: true }),
  ).toContainText("1.55 L");
  await page
    .getByRole("button", { name: "Open water log", exact: true })
    .click();
  await expect(panel.getByText("1.55 L", { exact: true })).toBeVisible();
  expect(state.posts).toHaveLength(3);
  expect(new Set(state.posts.map((entry) => entry.id)).size).toBe(3);
});

test("uncertain creation retries the exact payload and blocks duplicate quick adds", async ({
  page,
}) => {
  const state = await mockHydration(page);
  const panel = await openWater(page);
  state.loseNextPostResponse = true;
  await panel
    .getByRole("button", { name: "+250 ml", exact: true })
    .evaluate((button) => {
      // Two events in the same turn exercise the ref lock before React rerenders.
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  await expect(
    panel.getByRole("button", { name: "Retry pending change" }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "+250 ml", exact: true }),
  ).toBeDisabled();
  expect(state.posts).toHaveLength(1);
  await page.reload();
  await page
    .getByRole("button", { name: "Open water log", exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "Retry pending change" }),
  ).toBeEnabled();
  expect(state.posts).toHaveLength(1); // Recovery never replays without a click.
  await panel.getByRole("button", { name: "Retry pending change" }).click();
  await expect(
    panel.getByRole("button", { name: "Edit 250 ml entry" }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Retry pending change" }),
  ).toHaveCount(0);
  expect(state.posts).toHaveLength(2);
  expect(state.posts[1]).toEqual(state.posts[0]);
  expect(state.entries).toHaveLength(1);
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem("nutrilens.hydration.pending.v1:hydration-owner"),
    ),
  ).toBeNull();
});

test("pending recovery is owner scoped and a conflict clears the retry", async ({
  page,
}) => {
  const state = await mockHydration(page);
  const panel = await openWater(page);
  state.loseNextPostResponse = true;
  await panel.getByRole("button", { name: "+250 ml", exact: true }).click();
  await expect(
    panel.getByRole("button", { name: "Retry pending change" }),
  ).toBeVisible();
  state.ownerId = "different-fixture-owner";
  state.entries = [];
  await page.reload();
  await page
    .getByRole("button", { name: "Open water log", exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "+250 ml", exact: true }),
  ).toBeEnabled();
  await expect(
    panel.getByRole("button", { name: "Retry pending change" }),
  ).toHaveCount(0);
  expect(state.posts).toHaveLength(1);
  state.ownerId = "hydration-owner";
  state.conflictNextPost = true;
  await page.reload();
  await page
    .getByRole("button", { name: "Open water log", exact: true })
    .click();
  await panel.getByRole("button", { name: "Retry pending change" }).click();
  await expect(panel.getByRole("alert")).toContainText("changed or deleted");
  await expect(
    panel.getByRole("button", { name: "Retry pending change" }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem("nutrilens.hydration.pending.v1:hydration-owner"),
    ),
  ).toBeNull();
});

test("saved mutation with failed refresh retries only the read", async ({
  page,
}) => {
  const state = await mockHydration(page);
  const panel = await openWater(page);
  state.failReadAfterPost = true;
  await panel.getByRole("button", { name: "+500 ml", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("Your change was saved");
  await expect(
    panel.getByRole("button", { name: "Retry pending change" }),
  ).toHaveCount(0);
  state.failReads = false;
  await panel.getByRole("button", { name: "Refresh water log" }).click();
  await expect(
    panel.getByRole("button", { name: "Edit 500 ml entry" }),
  ).toBeVisible();
  expect(state.posts).toHaveLength(1);
});

test.describe("historical local-day boundaries", () => {
  test.use({ timezoneId: "America/New_York" });
  test("sends both midnight offsets for a 23-hour day and keeps the selected date", async ({
    page,
  }) => {
    await page.clock.install({ time: new Date("2026-09-02T16:00:00Z") });
    const state = await mockHydration(page);
    const panel = await openWater(page);
    await panel.getByLabel("Water log date").fill("2026-03-08");
    await expect(
      panel.getByRole("button", { name: "+250 ml", exact: true }),
    ).toBeEnabled();
    await expect
      .poll(() => state.queries.at(-1)?.searchParams.get("day"))
      .toBe("2026-03-08");
    const query = state.queries.at(-1)!;
    expect(query.searchParams.get("timezone_offset_minutes")).toBe("-300");
    expect(query.searchParams.get("next_day_timezone_offset_minutes")).toBe(
      "-240",
    );
    await panel.getByRole("button", { name: "+250 ml", exact: true }).click();
    await expect(
      panel.getByRole("button", { name: "Edit 250 ml entry" }),
    ).toBeVisible();
    expect(state.posts[0].consumed_at).toBe("2026-03-08T16:00:00.000Z");
    await panel.getByLabel("Water log date").fill("2026-09-02");
    await expect(
      panel.getByText("No water recorded for this day."),
    ).toBeVisible();
  });
});

test("read failures expose a retry and recover without creating an entry", async ({
  page,
}) => {
  const state = await mockHydration(page);
  state.failReads = true;
  await page.goto("/dashboard");
  await expect(
    page.getByRole("region", { name: "Today's water", exact: true }),
  ).toContainText("Water summary unavailable");
  await page
    .getByRole("button", { name: "Open water log", exact: true })
    .click();
  const panel = page.getByRole("region", { name: "Water log", exact: true });
  await expect(panel.getByRole("alert")).toContainText("could not be loaded");
  state.failReads = false;
  await panel.getByRole("button", { name: "Refresh water log" }).click();
  await expect(panel.getByText("No target set", { exact: true })).toBeVisible();
  expect(state.posts).toEqual([]);
});
