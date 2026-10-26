import { expect, type Locator, type Page, test } from "@playwright/test";

// Mocked UI contract checks, not evidence of authenticated production persistence.
const keys = [
  "calories",
  "protein_g",
  "carbs_g",
  "fat_g",
  "sugar_g",
  "sodium_mg",
  "fiber_g",
] as const;
type Values = Record<(typeof keys)[number], number | null>;
type Fields = {
  name: string;
  servings: number;
  ingredients: {
    name: string;
    quantity: number;
    unit: string;
    nutrients: Partial<Values>;
    source_label: string;
  }[];
  notes: string;
};
type Recipe = Fields & {
  id: string;
  version: number;
  total_nutrients: Values;
  per_serving: Values;
  source: string;
};
function saved(body: Fields & { id: string }, version = 1): Recipe {
  const total = Object.fromEntries(
    keys.map((key) => {
      const values = body.ingredients.map((item) => item.nutrients[key]);
      return [
        key,
        values.some((value) => value == null)
          ? null
          : values.reduce<number>((sum, value) => sum + (value ?? 0), 0),
      ];
    }),
  ) as Values;
  return {
    ...body,
    version,
    source: "USER_ENTERED",
    total_nutrients: total,
    per_serving: Object.fromEntries(
      keys.map((key) => [
        key,
        total[key] === null ? null : total[key] / body.servings,
      ]),
    ) as Values,
  };
}
async function mockRecipes(page: Page) {
  const state = {
    ownerId: "recipe-owner",
    records: new Map<string, Recipe[]>(),
    posts: [] as Array<Fields & { id: string }>,
    puts: [] as Array<Fields & { expected_version: number }>,
    deletes: [] as string[],
    losePost: false,
    failReads: false,
    failReadAfterPost: false,
    conflictPut: false,
    diaryPosts: [] as Array<{
      id: string;
      expected_version: number;
      servings: number;
      eaten_at: string;
    }>,
    shoppingPosts: [] as Array<{
      id: string;
      expected_version: number;
      servings: number;
      ingredient_keys: string[];
      check_token: string;
    }>,
    pantryChecks: [] as Array<{ expected_version: number; servings: number }>,
    diary: new Map<string, Record<string, unknown>>(),
    shopping: [] as Array<Record<string, unknown>>,
    loseDiary: false,
    actionStatus: 200,
    analyticsUnknown: false,
  };
  await page.route("**/api/backend/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/backend", "");
    const records = state.records.get(state.ownerId) ?? [];
    let payload: unknown = [];
    let status = 200;
    if (path === "/auth/me")
      payload = {
        id: state.ownerId,
        name: "Recipe fixture",
        email: "recipe@example.invalid",
        plan: "FREE",
        subscription_status: "FREE",
      };
    else if (path === "/analytics/summary")
      payload = state.analyticsUnknown
        ? {
            diary_entries: 2,
            period_days: 7,
            daily_averages: {
              calories: null,
              protein_g: 6,
              carbs_g: null,
              fat_g: 2,
              fiber_g: 0,
              calcium_mg: null,
              iron_mg: null,
            },
            insights: ["Incomplete nutrient evidence remains unknown."],
            goal_tracking_state: "AVAILABLE",
            goal_progress: [
              {
                nutrient: "calories",
                label: "Energy",
                unit: "kcal",
                daily_average: null,
                user_target: 1800,
                percent_of_target: null,
              },
            ],
          }
        : {
            diary_entries: 0,
            daily_averages: {},
            insights: [],
            goal_tracking_state: "NOT_CONFIGURED",
            goal_progress: [],
          };
    else if (path === "/analytics/trend")
      payload = state.analyticsUnknown
        ? [
            { date: "2026-09-04", calories: 100, protein_g: 12, sugar_g: 0 },
            {
              date: "2026-09-05",
              calories: null,
              protein_g: null,
              sugar_g: null,
            },
          ]
        : [];
    else if (path === "/analytics/drilldown")
      payload = {
        entries: [],
        period_days: 7,
        selected_date: null,
        limitation: "Logged evidence only.",
      };
    else if (path === "/analytics/patterns")
      payload = {
        state: "INSUFFICIENT_HISTORY",
        observed_days: 2,
        period_days: 7,
        minimum_observed_days: 7,
        observations: [],
      };
    else if (path === "/analytics/compare")
      payload = { state: "INSUFFICIENT_HISTORY", period_days: 7, stories: [] };
    else if (path === "/recipes/use-soon") payload = { suggestions: [] };
    else if (path === "/hydration")
      payload = {
        day: "2026-09-03",
        timezone_offset_minutes: 0,
        target_ml: null,
        total_ml: 0,
        remaining_ml: null,
        entries: [],
      };
    else if (path === "/diary") payload = [...state.diary.values()];
    else if (path === "/shopping-list") payload = state.shopping;
    else if (/\/recipes\/custom\/[^/]+\/pantry-check$/.test(path)) {
      const body = request.postDataJSON() as {
        expected_version: number;
        servings: number;
      };
      state.pantryChecks.push(body);
      const recipe = records.find(
        (item) => item.id === path.split("/").at(-2),
      )!;
      payload = {
        recipe_id: recipe.id,
        recipe_version: recipe.version,
        servings: body.servings,
        check_token: "a".repeat(64),
        limitation:
          "Exact names and comparable units only. Stock is not consumed.",
        ingredients: [
          {
            key: "available",
            name: "Oats",
            unit: "g",
            required_quantity: 50 * body.servings,
            available_quantity: 500,
            missing_quantity: 0,
            status: "AVAILABLE",
            pantry_item_ids: ["pantry-oats"],
          },
          {
            key: "missing",
            name: "Seeds",
            unit: "g",
            required_quantity: 10 * body.servings,
            available_quantity: 0,
            missing_quantity: 10 * body.servings,
            status: "MISSING",
            pantry_item_ids: [],
          },
          {
            key: "mismatch",
            name: "Oil",
            unit: "ml",
            required_quantity: 5 * body.servings,
            available_quantity: null,
            missing_quantity: null,
            status: "UNIT_MISMATCH",
            pantry_item_ids: ["pantry-oil"],
          },
        ],
      };
    } else if (/\/recipes\/custom\/[^/]+\/diary$/.test(path)) {
      const body = request.postDataJSON() as (typeof state.diaryPosts)[number];
      state.diaryPosts.push(body);
      if (state.actionStatus !== 200) {
        status = state.actionStatus;
        payload = { detail: "Action fixture failure" };
      } else {
        const recipe = records.find(
          (item) => item.id === path.split("/").at(-2),
        )!;
        status = state.diary.has(body.id) ? 200 : 201;
        if (!state.diary.has(body.id))
          state.diary.set(body.id, {
            id: body.id,
            name: recipe.name,
            eaten_at: body.eaten_at,
            serving_grams: null,
            recipe_servings: body.servings,
            recipe_id: recipe.id,
            recipe_version: recipe.version,
            source: "CUSTOM_RECIPE",
            nutrients: {
              calories: 60 * body.servings,
              protein_g: null,
              sodium_mg: 0,
              fiber_g: null,
              calcium_mg: null,
              iron_mg: null,
            },
          });
        payload = state.diary.get(body.id);
        if (state.loseDiary) {
          state.loseDiary = false;
          await route.abort("failed");
          return;
        }
      }
    } else if (/\/recipes\/custom\/[^/]+\/shopping-list$/.test(path)) {
      const body =
        request.postDataJSON() as (typeof state.shoppingPosts)[number];
      state.shoppingPosts.push(body);
      if (state.actionStatus !== 200) {
        status = state.actionStatus;
        payload = { detail: "Action fixture failure" };
      } else {
        const recipe = records.find(
          (item) => item.id === path.split("/").at(-2),
        )!;
        const existing = state.shopping.length > 0;
        if (!existing)
          state.shopping.push({
            id: "shopping-seeds",
            name: "Seeds",
            quantity: 10 * body.servings,
            unit: "g",
            checked: false,
            source: "CUSTOM_RECIPE",
            recipe_id: recipe.id,
          });
        payload = {
          recipe_id: recipe.id,
          recipe_version: recipe.version,
          generated_count: existing ? 0 : 1,
          items: state.shopping,
          limitation: "Explicit missing ingredients only.",
        };
      }
    } else if (path === "/recipes/custom" && request.method() === "GET") {
      status = state.failReads ? 503 : 200;
      payload = state.failReads ? { detail: "Fixture read failure" } : records;
    } else if (path === "/recipes/custom" && request.method() === "POST") {
      const body = request.postDataJSON() as Fields & { id: string };
      state.posts.push(body);
      let recipe = records.find((item) => item.id === body.id);
      if (!recipe) {
        recipe = saved(body);
        records.push(recipe);
        state.records.set(state.ownerId, records);
        status = 201;
      }
      if (state.losePost) {
        state.losePost = false;
        await route.abort("failed");
        return;
      }
      if (state.failReadAfterPost) state.failReads = true;
      payload = recipe;
    } else if (path.startsWith("/recipes/custom/")) {
      const id = path.split("/").at(-1);
      const current = records.find((item) => item.id === id)!;
      if (request.method() === "DELETE") {
        state.deletes.push(url.search);
        state.records.set(
          state.ownerId,
          records.filter((item) => item.id !== id),
        );
        await route.fulfill({ status: 204 });
        return;
      }
      if (request.method() === "PUT") {
        const body = request.postDataJSON() as Fields & {
          expected_version: number;
        };
        state.puts.push(body);
        if (state.conflictPut) {
          state.conflictPut = false;
          current.name = "Newer saved recipe";
          current.version += 1;
          status = 409;
          payload = { detail: "Version conflict" };
        } else {
          const { expected_version, ...fields } = body;
          payload = saved({ ...fields, id: current.id }, expected_version + 1);
          state.records.set(
            state.ownerId,
            records.map((item) =>
              item.id === id ? (payload as Recipe) : item,
            ),
          );
        }
      }
    }
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(payload),
    });
  });
  return state;
}
async function openRecipes(page: Page, navigate = true) {
  if (navigate) await page.goto("/dashboard");
  await page.getByRole("button", { name: "Smart pantry", exact: true }).click();
  const panel = page.getByRole("region", {
    name: "Custom recipes",
    exact: true,
  });
  await expect(
    panel.getByRole("button", { name: "Refresh recipes", exact: true }),
  ).toBeEnabled();
  return panel;
}
async function enterRecipe(panel: Locator, name = "My lentil bowl") {
  await panel
    .getByRole("button", { name: "Create recipe", exact: true })
    .click();
  await panel.getByLabel("Recipe name", { exact: true }).fill(name);
  await panel.getByLabel("Number of servings").fill("2");
  const ingredient = panel.getByRole("group", {
    name: "Ingredient 1",
    exact: true,
  });
  await ingredient
    .getByLabel("Ingredient name", { exact: true })
    .fill("Cooked lentils");
  await ingredient.getByLabel("Quantity", { exact: true }).fill("200");
  await ingredient.getByLabel("Unit", { exact: true }).fill("g");
  return ingredient;
}

function seedActionRecipe(state: Awaited<ReturnType<typeof mockRecipes>>) {
  const recipe = saved({
    id: "53b8a477-7794-4098-a41c-38e388aab873",
    name: "My breakfast recipe",
    servings: 2,
    notes: "",
    ingredients: [
      {
        name: "Oats",
        quantity: 100,
        unit: "g",
        nutrients: { calories: 120, sodium_mg: 0 },
        source_label: "Measured label evidence",
      },
    ],
  });
  state.records.set(state.ownerId, [recipe]);
  return recipe;
}

test("dashboard and analytics never present incomplete recipe nutrition as zero or a partial macro split", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  state.analyticsUnknown = true;
  await page.goto("/dashboard");
  await expect(
    page.getByText("Progress unknown", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Missing nutrient evidence stays unknown, not zero, and is never estimated.",
      { exact: true },
    ),
  ).toBeVisible();
  await page.getByRole("button", { name: "My nutrition", exact: true }).click();
  await expect(
    page.getByText(
      "Some logged entries lack this nutrient. Gaps and the unknown total are not zeros.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.getByText("Progress unknown")).toBeVisible();
  await expect(
    page.getByText("Protein Unknown", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Carbs Unknown", { exact: true })).toBeVisible();
  await expect(page.getByText("Fat Unknown", { exact: true })).toBeVisible();
  await expect(
    page.getByRole("progressbar", { name: "Energy progress" }),
  ).toHaveCount(0);
  await expect(page.getByText("0 g", { exact: true })).toBeVisible();
});

async function chooseActionRecipe(panel: Locator, recipe: Recipe) {
  const actions = panel.getByRole("region", {
    name: "Use a saved recipe",
    exact: true,
  });
  const select = actions.getByRole("combobox", {
    name: "Saved recipe",
    exact: true,
  });
  await expect(select).toBeEnabled();
  await select.selectOption({ label: recipe.name });
  return actions;
}

test("recipe consumption is explicit, serving-based and nullable in the diary", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  const recipe = seedActionRecipe(state);
  const panel = await openRecipes(page);
  const actions = await chooseActionRecipe(panel, recipe);
  await actions.getByLabel("Recipe servings to use").fill("2.5");
  await actions
    .getByLabel("Consumed at (your local time)")
    .fill("2026-09-05T12:34");
  const log = actions.getByRole("button", {
    name: "Log consumed servings",
    exact: true,
  });
  await expect(log).toBeDisabled();
  expect(state.diaryPosts).toHaveLength(0);
  await actions
    .getByLabel("I consumed these recipe servings", { exact: true })
    .check();
  await log.click();
  await expect(actions.getByRole("status")).toContainText(
    "consumed servings saved to your diary",
  );
  expect(state.diaryPosts).toHaveLength(1);
  expect(state.diaryPosts[0]).toMatchObject({
    expected_version: 1,
    servings: 2.5,
  });
  expect(state.diaryPosts[0].eaten_at).toMatch(/T.*Z$/);
  expect(Object.keys(state.diaryPosts[0])).toEqual([
    "id",
    "expected_version",
    "servings",
    "eaten_at",
  ]);
  expect(state.shoppingPosts).toHaveLength(0);
  await expect(log).toBeDisabled();
  await page.getByRole("button", { name: "Food diary", exact: true }).click();
  await expect(
    page.getByText("My breakfast recipe", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText(/2.5 recipe servings/)).toBeVisible();
  await expect(page.getByText("150 kcal", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Protein: Unknown · Sodium: 0 mg", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("100 g", { exact: true })).toHaveCount(0);
});

test("lost recipe log response survives reload and auth errors without a new consumption ID", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  const recipe = seedActionRecipe(state);
  const actions = await chooseActionRecipe(await openRecipes(page), recipe);
  state.loseDiary = true;
  await actions
    .getByLabel("I consumed these recipe servings", { exact: true })
    .check();
  await actions
    .getByRole("button", { name: "Log consumed servings", exact: true })
    .click();
  await expect(
    actions.getByRole("button", { name: "Retry pending recipe action" }),
  ).toBeVisible();
  expect(state.diary.size).toBe(1);
  const original = { ...state.diaryPosts[0] };
  await page.reload();
  const recovered = (await openRecipes(page, false)).getByRole("region", {
    name: "Use a saved recipe",
    exact: true,
  });
  const retry = recovered.getByRole("button", {
    name: "Retry pending recipe action",
    exact: true,
  });
  await expect(retry).toBeEnabled();
  expect(state.diaryPosts).toHaveLength(1);
  for (const status of [401, 403, 404]) {
    state.actionStatus = status;
    await retry.click();
    await expect(retry).toBeEnabled();
    expect(state.diaryPosts.at(-1)).toEqual(original);
  }
  state.actionStatus = 200;
  await retry.click();
  await expect(retry).toHaveCount(0);
  expect(state.diaryPosts).toHaveLength(5);
  expect(state.diaryPosts.at(-1)).toEqual(original);
  expect(state.diary.size).toBe(1);
});

test("pantry checks require explicit missing selection and preserve unit uncertainty", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  const recipe = seedActionRecipe(state);
  const panel = await openRecipes(page);
  const actions = await chooseActionRecipe(panel, recipe);
  await actions
    .getByRole("button", { name: "Check recipe against pantry", exact: true })
    .click();
  await expect(
    actions.getByText(/Quantity unknown: pantry units/),
  ).toBeVisible();
  await expect(
    actions.getByText("Available in your pantry.", { exact: true }),
  ).toBeVisible();
  expect(state.diaryPosts).toHaveLength(0);
  expect(state.shoppingPosts).toHaveLength(0);
  const add = actions.getByRole("button", {
    name: "Add selected missing ingredients to shopping",
    exact: true,
  });
  await expect(add).toBeDisabled();
  await expect(actions.getByRole("checkbox", { name: /Oil/ })).toHaveCount(0);
  await actions
    .getByRole("checkbox", { name: "Add missing 10 g of Seeds", exact: true })
    .check();
  await add.click();
  await expect(actions.getByRole("status")).toContainText(
    "1 missing ingredient added",
  );
  expect(state.shoppingPosts[0]).toMatchObject({
    expected_version: 1,
    servings: 1,
    ingredient_keys: ["missing"],
    check_token: "a".repeat(64),
  });
  expect(state.shopping).toHaveLength(1);
  await expect(
    page.getByText("Recipe ingredient · 10 g", { exact: true }),
  ).toBeVisible();
});

test("pantry checks expire when servings change and stock conflicts require a fresh check", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  const recipe = seedActionRecipe(state);
  const actions = await chooseActionRecipe(await openRecipes(page), recipe);
  const check = actions.getByRole("button", {
    name: "Check recipe against pantry",
    exact: true,
  });
  await check.click();
  await expect(
    actions.getByRole("heading", {
      name: "Pantry ingredient check",
      exact: true,
    }),
  ).toBeVisible();
  await actions.getByLabel("Recipe servings to use").fill("2");
  await expect(
    actions.getByRole("heading", {
      name: "Pantry ingredient check",
      exact: true,
    }),
  ).toHaveCount(0);
  await check.click();
  await actions
    .getByRole("checkbox", { name: "Add missing 20 g of Seeds", exact: true })
    .check();
  state.actionStatus = 409;
  await actions
    .getByRole("button", {
      name: "Add selected missing ingredients to shopping",
      exact: true,
    })
    .click();
  await expect(actions.getByRole("alert")).toContainText(
    "ingredient availability changed",
  );
  await expect(
    actions.getByRole("heading", {
      name: "Pantry ingredient check",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(
    actions.getByRole("button", {
      name: "Retry pending recipe action",
      exact: true,
    }),
  ).toHaveCount(0);
  expect(state.shopping).toHaveLength(0);
});

test("a pending recipe action is never exposed or replayed in another owner's session", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  const owner = state.ownerId;
  const recipe = seedActionRecipe(state);
  const actions = await chooseActionRecipe(await openRecipes(page), recipe);
  state.loseDiary = true;
  await actions
    .getByLabel("I consumed these recipe servings", { exact: true })
    .check();
  await actions
    .getByRole("button", { name: "Log consumed servings", exact: true })
    .click();
  await expect(
    actions.getByRole("button", {
      name: "Retry pending recipe action",
      exact: true,
    }),
  ).toBeVisible();
  state.ownerId = "different-owner";
  await page.reload();
  let panel = await openRecipes(page, false);
  await expect(
    panel.getByRole("button", {
      name: "Retry pending recipe action",
      exact: true,
    }),
  ).toHaveCount(0);
  await expect(panel.getByText(recipe.name, { exact: true })).toHaveCount(0);
  expect(state.diaryPosts).toHaveLength(1);
  state.ownerId = owner;
  await page.reload();
  panel = await openRecipes(page, false);
  await expect(
    panel.getByRole("button", {
      name: "Retry pending recipe action",
      exact: true,
    }),
  ).toBeVisible();
  expect(state.diaryPosts).toHaveLength(1);
});

test("custom recipe CRUD preserves evidence, unknowns and server per-serving values", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  const panel = await openRecipes(page);
  await expect(panel.getByText("No custom recipes saved yet.")).toBeVisible();
  const first = await enterRecipe(panel);
  await first
    .getByText("Optional nutrition for ingredient 1", { exact: true })
    .click();
  await first.getByLabel("Calories (kcal)", { exact: true }).fill("240");
  await first.getByLabel("Protein (g)", { exact: true }).fill("18");
  await first.getByLabel("Sugar (g)", { exact: true }).fill("0");
  await first
    .getByLabel("Nutrition source", { exact: true })
    .fill("My measured ingredient evidence");
  await panel
    .getByRole("button", { name: "Add ingredient", exact: true })
    .click();
  const second = panel.getByRole("group", {
    name: "Ingredient 2",
    exact: true,
  });
  await second.getByLabel("Ingredient name").fill("Olive oil");
  await second.getByLabel("Quantity", { exact: true }).fill("1");
  await second.getByLabel("Unit", { exact: true }).fill("tsp");
  await second
    .getByText("Optional nutrition for ingredient 2", { exact: true })
    .click();
  await second.getByLabel("Calories (kcal)", { exact: true }).fill("40");
  await second.getByLabel("Sugar (g)", { exact: true }).fill("0");
  await panel.getByLabel("Recipe notes").fill("Mix after cooking.");
  await panel.getByRole("button", { name: "Save recipe", exact: true }).click();
  const card = panel.getByRole("article", {
    name: "Recipe: My lentil bowl",
    exact: true,
  });
  await expect(card).toBeVisible();
  await expect(
    card.getByRole("row", { name: "Calories 280 kcal 140 kcal", exact: true }),
  ).toBeVisible();
  await expect(
    card.getByRole("row", { name: "Protein Unknown Unknown", exact: true }),
  ).toBeVisible();
  await expect(
    card.getByRole("row", { name: "Sugar 0 g 0 g", exact: true }),
  ).toBeVisible();
  await expect(card).toContainText("My measured ingredient evidence");
  expect(state.posts[0].ingredients[0].nutrients.protein_g).toBe(18);
  expect(state.posts[0].ingredients[1].nutrients.protein_g).toBeNull();
  await card
    .getByRole("button", { name: "Edit recipe My lentil bowl", exact: true })
    .click();
  await panel.getByLabel("Recipe name", { exact: true }).fill("My edited bowl");
  await panel.getByLabel("Number of servings").fill("4");
  await panel
    .getByRole("button", { name: "Save recipe changes", exact: true })
    .click();
  const edited = panel.getByRole("article", {
    name: "Recipe: My edited bowl",
    exact: true,
  });
  await expect(
    edited.getByRole("row", { name: "Calories 280 kcal 70 kcal", exact: true }),
  ).toBeVisible();
  expect(state.puts[0].expected_version).toBe(1);
  expect(state.puts[0]).not.toHaveProperty("id");
  await page.reload();
  await openRecipes(page, false);
  await expect(edited).toBeVisible();
  await edited
    .getByRole("button", { name: "Delete recipe My edited bowl", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Delete this recipe?" });
  await dialog.getByRole("button", { name: "Keep recipe" }).click();
  expect(state.deletes).toHaveLength(0);
  await edited
    .getByRole("button", { name: "Delete recipe My edited bowl", exact: true })
    .click();
  await dialog.getByRole("button", { name: "Confirm delete recipe" }).click();
  await expect(panel.getByText("No custom recipes saved yet.")).toBeVisible();
  expect(state.deletes).toEqual(["?expected_version=2"]);
});

test("interrupted creation reloads with explicit same-ID retry and rejects double submit", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  const panel = await openRecipes(page);
  await enterRecipe(panel);
  state.losePost = true;
  await panel
    .getByRole("button", { name: "Save recipe", exact: true })
    .evaluate((button) => {
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  await expect(
    panel.getByRole("button", { name: "Retry pending recipe change" }),
  ).toBeEnabled();
  expect(state.posts).toHaveLength(1);
  await expect(
    panel.getByRole("button", { name: "Save recipe", exact: true }),
  ).toBeDisabled();
  await page.reload();
  await openRecipes(page, false);
  await expect(
    panel.getByRole("button", { name: "Retry pending recipe change" }),
  ).toBeEnabled();
  expect(state.posts).toHaveLength(1);
  await panel
    .getByRole("button", { name: "Retry pending recipe change" })
    .click();
  await expect(
    panel.getByRole("button", { name: "Retry pending recipe change" }),
  ).toHaveCount(0);
  expect(state.posts).toHaveLength(2);
  expect(state.posts[1]).toEqual(state.posts[0]);
  expect(state.records.get(state.ownerId)).toHaveLength(1);
  expect(
    await page.evaluate(() =>
      sessionStorage.getItem("nutrilens.recipes.pending.v1:recipe-owner"),
    ),
  ).toBeNull();
});

test("pending recipe belongs only to its owner and never replays on account change", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  const panel = await openRecipes(page);
  await enterRecipe(panel, "Owner A private recipe");
  state.losePost = true;
  await panel.getByRole("button", { name: "Save recipe", exact: true }).click();
  await expect(
    panel.getByRole("button", { name: "Retry pending recipe change" }),
  ).toBeVisible();
  state.ownerId = "owner-b";
  await page.reload();
  await openRecipes(page, false);
  await expect(
    panel.getByRole("button", { name: "Create recipe", exact: true }),
  ).toBeEnabled();
  await expect(
    panel.getByRole("button", { name: "Retry pending recipe change" }),
  ).toHaveCount(0);
  await expect(panel).not.toContainText("Owner A private recipe");
  expect(state.posts).toHaveLength(1);
  state.ownerId = "recipe-owner";
  await page.reload();
  await openRecipes(page, false);
  await expect(
    panel.getByRole("button", { name: "Retry pending recipe change" }),
  ).toBeEnabled();
  expect(state.posts).toHaveLength(1);
});

test("stale version keeps the draft but requires review before a new edit", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  const panel = await openRecipes(page);
  await enterRecipe(panel);
  await panel.getByRole("button", { name: "Save recipe", exact: true }).click();
  await panel
    .getByRole("button", { name: "Edit recipe My lentil bowl", exact: true })
    .click();
  await panel
    .getByLabel("Recipe name", { exact: true })
    .fill("Stale draft name");
  state.conflictPut = true;
  await panel
    .getByRole("button", { name: "Save recipe changes", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("changed or deleted");
  await expect(panel.getByLabel("Recipe name", { exact: true })).toHaveValue(
    "Stale draft name",
  );
  await expect(
    panel.getByRole("button", { name: "Save recipe changes", exact: true }),
  ).toBeDisabled();
  await expect(
    panel.getByRole("article", {
      name: "Recipe: Newer saved recipe",
      exact: true,
    }),
  ).toBeVisible();
  await panel
    .getByRole("button", { name: "Cancel recipe edit", exact: true })
    .click();
  await panel
    .getByRole("button", {
      name: "Edit recipe Newer saved recipe",
      exact: true,
    })
    .click();
  await panel
    .getByRole("button", { name: "Save recipe changes", exact: true })
    .click();
  await expect(
    panel.getByRole("form", { name: "Edit custom recipe" }),
  ).toHaveCount(0);
  expect(state.puts.map((body) => body.expected_version)).toEqual([1, 2]);
});

test("confirmed save followed by failed read only retries the list", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  const panel = await openRecipes(page);
  await enterRecipe(panel);
  state.failReadAfterPost = true;
  await panel.getByRole("button", { name: "Save recipe", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("was saved");
  await expect(
    panel.getByRole("button", { name: "Retry pending recipe change" }),
  ).toHaveCount(0);
  state.failReads = false;
  await panel
    .getByRole("button", { name: "Refresh recipes", exact: true })
    .click();
  await expect(
    panel.getByRole("article", { name: "Recipe: My lentil bowl", exact: true }),
  ).toBeVisible();
  expect(state.posts).toHaveLength(1);
});

test("ingredient removal and numeric validation do not invent a missing recipe value", async ({
  page,
}) => {
  const state = await mockRecipes(page);
  const panel = await openRecipes(page);
  const first = await enterRecipe(panel);
  await panel
    .getByRole("button", { name: "Add ingredient", exact: true })
    .click();
  await panel
    .getByRole("button", { name: "Remove ingredient 2", exact: true })
    .click();
  await expect(
    panel.getByRole("button", { name: "Remove ingredient 1", exact: true }),
  ).toBeDisabled();
  await panel.getByLabel("Number of servings").fill("0");
  await panel.getByRole("button", { name: "Save recipe", exact: true }).click();
  expect(state.posts).toHaveLength(0);
  await panel.getByLabel("Number of servings").fill("2");
  await first
    .getByText("Optional nutrition for ingredient 1", { exact: true })
    .click();
  await first.getByLabel("Calories (kcal)", { exact: true }).fill("-5");
  await panel.getByRole("button", { name: "Save recipe", exact: true }).click();
  expect(state.posts).toHaveLength(0);
  await first.getByLabel("Calories (kcal)", { exact: true }).fill("");
  await panel.getByRole("button", { name: "Save recipe", exact: true }).click();
  await expect(
    panel.getByRole("row", { name: "Calories Unknown Unknown", exact: true }),
  ).toBeVisible();
});
