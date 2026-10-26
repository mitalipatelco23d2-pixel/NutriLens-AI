import { expect, type Page, test } from "@playwright/test";

type WeightEntry = {
  id: string;
  weight_kg: number;
  recorded_at: string;
  source: "USER_ENTERED";
};

const emptyProfile = () => ({
  goal: "balanced",
  custom_goal: null as string | null,
  allergens: [] as string[],
  dietary_preferences: [] as string[],
  consent_personalization: false,
  daily_targets: {
    calories: null,
    protein_g: null,
    fiber_g: null,
    sodium_mg: null,
    calcium_mg: null,
    iron_mg: null,
  },
  body_context: {
    adult_attestation: false,
    consent_bmi_context: false,
    height_cm: null,
    weight_kg: null,
  },
});

async function mockAccount(page: Page) {
  const state = {
    profile: emptyProfile(),
    profilePuts: [] as Array<ReturnType<typeof emptyProfile>>,
    weightEnabled: false,
    target: null as number | null,
    entries: [] as WeightEntry[],
    failNextWeightRead: false,
  };

  const weightSummary = () => {
    const entries = [...state.entries].sort(
      (left, right) =>
        Date.parse(right.recorded_at) - Date.parse(left.recorded_at),
    );
    const latest = entries[0]?.weight_kg ?? null;
    const first = entries.at(-1)?.weight_kg ?? null;
    return {
      state: state.weightEnabled ? "ACTIVE" : "DISABLED",
      target_weight_kg: state.target,
      latest_weight_kg: latest,
      change_from_first_kg:
        entries.length > 1 && latest !== null && first !== null
          ? latest - first
          : null,
      difference_from_target_kg:
        latest !== null && state.target !== null ? latest - state.target : null,
      entries: state.weightEnabled ? entries : [],
      method: "SELF_REPORTED_WEIGHT_DIFFERENCE_V1",
      limitation:
        "Descriptive self-reported records only. NutriLens does not assign an ideal weight, safe pace, calorie prescription, diagnosis or treatment.",
    };
  };

  await page.route("**/api/backend/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/backend", "");
    const method = request.method();
    let payload: unknown = {};
    let status = 200;

    if (path === "/auth/me") {
      payload = {
        id: "weight-owner",
        name: "Weight fixture",
        email: "weight@example.invalid",
        plan: "FREE",
        subscription_status: "FREE",
      };
    } else if (path === "/analytics/summary") {
      payload = {
        diary_entries: 0,
        period_days: 1,
        daily_averages: {
          calories: null,
          protein_g: null,
          carbs_g: null,
          fat_g: null,
          sugar_g: null,
          sodium_mg: null,
          fiber_g: null,
          calcium_mg: null,
          iron_mg: null,
        },
        insights: [],
        goal_tracking_state: "NOT_CONFIGURED",
        goal_progress: [],
        goal_tracking_limitation: "User-entered references only.",
      };
    } else if (path === "/scan/history") {
      payload = [];
    } else if (path === "/notifications") {
      payload = [];
    } else if (path === "/hydration") {
      payload = {
        day: "2026-09-23",
        timezone_offset_minutes: 330,
        target_ml: null,
        total_ml: 0,
        remaining_ml: null,
        entries: [],
      };
    } else if (path === "/payments/account") {
      payload = {
        plan: "FREE",
        subscription_status: "FREE",
        mode: "test",
        subscription: null,
        payments: [],
      };
    } else if (path === "/profile/bmi-context") {
      payload = {
        state: "NOT_CONFIGURED",
        bmi: null,
        limitation:
          "This value is a weight-for-height context only, not a diagnosis or target.",
        reference_url:
          "https://www.who.int/data/gho/data/themes/topics/topic-details/GHO/body-mass-index",
      };
    } else if (path === "/profile/household") {
      payload = [];
    } else if (path === "/profile") {
      if (method === "PUT") {
        const profile = request.postDataJSON() as ReturnType<
          typeof emptyProfile
        >;
        state.profile = structuredClone(profile);
        state.profilePuts.push(structuredClone(profile));
      }
      payload = state.profile;
    } else if (path === "/weight") {
      if (state.failNextWeightRead) {
        state.failNextWeightRead = false;
        status = 503;
        payload = { detail: "Fixture summary failure" };
      } else {
        payload = weightSummary();
      }
    } else if (path === "/weight/settings" && method === "PUT") {
      const body = request.postDataJSON() as {
        target_weight_kg: number | null;
      };
      state.weightEnabled = true;
      state.target = body.target_weight_kg;
      payload = { state: "ACTIVE", target_weight_kg: state.target };
    } else if (path === "/weight/settings" && method === "DELETE") {
      state.weightEnabled = false;
      state.target = null;
      state.entries = [];
      await route.fulfill({ status: 204 });
      return;
    } else if (path === "/weight/entries" && method === "POST") {
      const body = request.postDataJSON() as Omit<WeightEntry, "source">;
      const existing = state.entries.find(({ id }) => id === body.id);
      if (existing) {
        payload = existing;
      } else {
        const entry: WeightEntry = { ...body, source: "USER_ENTERED" };
        state.entries.push(entry);
        payload = entry;
        status = 201;
      }
    } else if (path.startsWith("/weight/entries/")) {
      const id = path.split("/").at(-1);
      if (method === "DELETE") {
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

test("custom wellness intent and consented weight records persist through reload and erase", async ({
  page,
}) => {
  test.setTimeout(60_000);
  const state = await mockAccount(page);
  await page.goto("/account");

  await page.getByLabel("Primary goal").selectOption("custom");
  await page.getByRole("button", { name: "Save preferences" }).click();
  await expect(
    page.getByText("Describe your custom goal before saving."),
  ).toBeVisible();
  expect(state.profilePuts).toHaveLength(0);
  await page
    .getByLabel("Describe your custom goal")
    .fill("Build consistent meal habits");
  await page.getByRole("button", { name: "Save preferences" }).click();
  await expect(page.getByText("Preferences saved.")).toBeVisible();
  expect(state.profilePuts.at(-1)).toMatchObject({
    goal: "custom",
    custom_goal: "Build consistent meal habits",
  });

  const weight = page.getByRole("region", {
    name: "Optional weight tracking",
  });
  const enable = weight.getByRole("button", {
    name: "Enable optional tracking",
  });
  await expect(enable).toBeDisabled();
  await weight
    .getByRole("checkbox", { name: /I choose to store self-reported/ })
    .check();
  await enable.click();
  await expect(weight.getByText("No records yet.")).toBeVisible();

  await weight.getByLabel("Weight (kg)", { exact: true }).fill("70");
  await weight.getByRole("button", { name: "Add record" }).click();
  await expect(
    weight.getByRole("button", { name: "Edit 70 kg record" }),
  ).toBeVisible();
  expect(state.entries).toHaveLength(1);

  await weight.getByRole("button", { name: "Edit 70 kg record" }).click();
  await weight.getByLabel("Weight (kg)", { exact: true }).fill("69.5");
  await weight.getByRole("button", { name: "Save record" }).click();
  await expect(
    weight.getByRole("button", { name: "Edit 69.5 kg record" }),
  ).toBeVisible();

  await weight.getByLabel("Target weight (kg)").fill("65");
  state.failNextWeightRead = true;
  await weight.getByRole("button", { name: "Save target" }).click();
  await expect(
    weight.getByText(
      "Target saved. The latest summary could not be reloaded; refresh before making another change.",
    ),
  ).toBeVisible();
  expect(state.target).toBe(65);

  await page.reload();
  await expect(page.getByLabel("Primary goal")).toHaveValue("custom");
  await expect(page.getByLabel("Describe your custom goal")).toHaveValue(
    "Build consistent meal habits",
  );
  await expect(
    weight.getByRole("button", { name: "Delete 69.5 kg record" }),
  ).toBeVisible();
  await expect(weight.getByLabel("Target weight (kg)")).toHaveValue("65");

  await weight.getByRole("button", { name: "Delete 69.5 kg record" }).click();
  await weight
    .getByRole("button", { name: "Confirm delete 69.5 kg record" })
    .click();
  await expect(weight.getByText("No records yet.")).toBeVisible();

  await weight.getByLabel("Type ERASE to confirm").fill("ERASE");
  await weight.getByRole("button", { name: "Disable and erase" }).click();
  await expect(enable).toBeDisabled();
  expect(state.weightEnabled).toBe(false);
  expect(state.target).toBeNull();
  expect(state.entries).toEqual([]);
});

test("Today and My Nutrition show only owner weight records and account controls", async ({
  page,
}) => {
  const state = await mockAccount(page);
  const now = Date.now();
  state.weightEnabled = true;
  state.target = 65;
  state.entries = [
    {
      id: "0a71dfe3-6852-4dd3-988f-359675fb9e33",
      weight_kg: 70,
      recorded_at: new Date(now - 2 * 24 * 60 * 60 * 1000).toISOString(),
      source: "USER_ENTERED",
    },
    {
      id: "a3de3d5a-d98b-43cc-b2f2-9e09cfd768f4",
      weight_kg: 69.5,
      recorded_at: new Date(now - 24 * 60 * 60 * 1000).toISOString(),
      source: "USER_ENTERED",
    },
  ];

  await page.goto("/dashboard");
  const snapshot = page.getByRole("region", { name: "Weight snapshot" });
  await expect(snapshot.getByText("69.5 kg", { exact: true })).toBeVisible();
  await expect(snapshot.getByText("-0.5 kg", { exact: true })).toBeVisible();
  await expect(snapshot).toContainText(
    "NutriLens does not assign an ideal weight",
  );
  await expect(
    snapshot.getByRole("link", { name: "Manage weight" }),
  ).toHaveAttribute("href", "/account#weight-tracking-title");

  await page.getByRole("button", { name: "My nutrition", exact: true }).click();
  const history = page.getByRole("article", { name: "Weight history" });
  await expect(history.getByText("69.5 kg", { exact: true })).toBeVisible();
  await expect(history.getByText("-0.5 kg", { exact: true })).toBeVisible();
  await expect(history).toContainText("2");
  await expect(history).toContainText(
    "No pace, outcome or calorie prescription is inferred.",
  );
});
