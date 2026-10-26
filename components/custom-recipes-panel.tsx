"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CustomRecipeActions } from "./custom-recipe-actions";
import styles from "./custom-recipes-panel.module.css";

const nutrients = [
  ["calories", "Calories", "kcal"],
  ["protein_g", "Protein", "g"],
  ["carbs_g", "Carbohydrate", "g"],
  ["fat_g", "Fat", "g"],
  ["sugar_g", "Sugar", "g"],
  ["sodium_mg", "Sodium", "mg"],
  ["fiber_g", "Fiber", "g"],
] as const;
type NutrientKey = (typeof nutrients)[number][0];
type NutrientValues = Record<NutrientKey, number | null>;
type Ingredient = {
  name: string;
  quantity: number;
  unit: string;
  nutrients: Partial<NutrientValues>;
  source_label: string;
};
type RecipeFields = {
  name: string;
  servings: number;
  ingredients: Ingredient[];
  notes: string;
};
type Recipe = RecipeFields & {
  id: string;
  version: number;
  created_at: string;
  updated_at: string;
  total_nutrients: NutrientValues;
  per_serving: NutrientValues;
  source: "USER_ENTERED";
};
type IngredientDraft = {
  key: string;
  name: string;
  quantity: string;
  unit: string;
  nutrients: Partial<Record<NutrientKey, string>>;
  source_label: string;
};
type Draft = {
  name: string;
  servings: string;
  ingredients: IngredientDraft[];
  notes: string;
};
type Mutation = {
  method: "POST" | "PUT" | "DELETE";
  path: string;
  body?: string;
};
const endpoint = "/api/backend/recipes/custom";
const pendingKey = (ownerId: string) =>
  `nutrilens.recipes.pending.v1:${encodeURIComponent(ownerId)}`;
const uuidPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function recoverPending(ownerId: string): Mutation | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(pendingKey(ownerId));
    if (!raw || raw.length > 200_000) return null;
    const saved = JSON.parse(raw) as { version?: unknown; mutation?: Mutation };
    const mutation = saved.mutation;
    if (saved.version !== 1 || !mutation) return null;
    const id = mutation.path.split("?")[0].slice(1);
    if (mutation.method === "DELETE") {
      return uuidPattern.test(id) &&
        /^\/[0-9a-f-]+\?expected_version=[1-9]\d*$/i.test(mutation.path)
        ? { method: "DELETE", path: mutation.path }
        : null;
    }
    if (typeof mutation.body !== "string") return null;
    const body = JSON.parse(mutation.body) as RecipeFields & {
      id?: string;
      expected_version?: number;
    };
    if (
      typeof body.name !== "string" ||
      !body.name.trim() ||
      body.name.length > 200 ||
      !Number.isFinite(body.servings) ||
      body.servings < 0.001 ||
      body.servings > 1000 ||
      !Array.isArray(body.ingredients) ||
      body.ingredients.length < 1 ||
      body.ingredients.length > 100 ||
      typeof body.notes !== "string" ||
      body.notes.length > 4000 ||
      !body.ingredients.every(
        (item) =>
          item &&
          typeof item.name === "string" &&
          item.name.trim().length > 0 &&
          item.name.length <= 200 &&
          Number.isFinite(item.quantity) &&
          item.quantity >= 0.001 &&
          item.quantity <= 100000 &&
          typeof item.unit === "string" &&
          item.unit.trim().length > 0 &&
          item.unit.length <= 30 &&
          typeof item.source_label === "string" &&
          item.source_label.trim().length > 0 &&
          item.source_label.length <= 200 &&
          typeof item.nutrients === "object" &&
          item.nutrients !== null &&
          Object.entries(item.nutrients).every(
            ([key, value]) =>
              nutrients.some(([known]) => known === key) &&
              (value === null ||
                (typeof value === "number" &&
                  Number.isFinite(value) &&
                  value >= 0 &&
                  value <= 1000000)),
          ),
      )
    )
      return null;
    if (mutation.method === "POST") {
      return mutation.path === "" && uuidPattern.test(body.id ?? "")
        ? { method: "POST", path: "", body: mutation.body }
        : null;
    }
    return mutation.method === "PUT" &&
      mutation.path === `/${id}` &&
      uuidPattern.test(id) &&
      Number.isSafeInteger(body.expected_version) &&
      (body.expected_version ?? 0) > 0
      ? { method: "PUT", path: mutation.path, body: mutation.body }
      : null;
  } catch {
    return null;
  }
}

function freshIngredient(): IngredientDraft {
  return {
    key: crypto.randomUUID(),
    name: "",
    quantity: "",
    unit: "",
    nutrients: {},
    source_label: "User-entered ingredient values",
  };
}
function recipeDraft(recipe?: RecipeFields): Draft {
  return recipe
    ? {
        name: recipe.name,
        servings: String(recipe.servings),
        notes: recipe.notes,
        ingredients: recipe.ingredients.map((item) => ({
          ...item,
          key: crypto.randomUUID(),
          quantity: String(item.quantity),
          nutrients: Object.fromEntries(
            nutrients.map(([key]) => [
              key,
              item.nutrients[key] == null ? "" : String(item.nutrients[key]),
            ]),
          ),
        })),
      }
    : { name: "", servings: "", ingredients: [freshIngredient()], notes: "" };
}
function parseDraft(draft: Draft): RecipeFields | null {
  const servings = Number(draft.servings);
  if (
    !draft.name.trim() ||
    !Number.isFinite(servings) ||
    servings < 0.001 ||
    servings > 1000
  )
    return null;
  const ingredients: Ingredient[] = [];
  for (const item of draft.ingredients) {
    const quantity = Number(item.quantity);
    if (
      !item.name.trim() ||
      !item.unit.trim() ||
      !item.source_label.trim() ||
      !Number.isFinite(quantity) ||
      quantity < 0.001 ||
      quantity > 100000
    )
      return null;
    const values: Partial<NutrientValues> = {};
    for (const [key] of nutrients) {
      const raw = item.nutrients[key]?.trim() ?? "";
      const number = raw === "" ? null : Number(raw);
      if (
        number !== null &&
        (!Number.isFinite(number) || number < 0 || number > 1000000)
      )
        return null;
      values[key] = number;
    }
    ingredients.push({
      name: item.name.trim(),
      quantity,
      unit: item.unit.trim(),
      source_label: item.source_label.trim(),
      nutrients: values,
    });
  }
  return { name: draft.name.trim(), servings, notes: draft.notes, ingredients };
}

function RecipeNutrition({ recipe }: { recipe: Recipe }) {
  return (
    <div className={styles.tableWrap}>
      <table>
        <caption>Nutrition calculated from your ingredient values</caption>
        <thead>
          <tr>
            <th scope="col">Nutrient</th>
            <th scope="col">Whole recipe</th>
            <th scope="col">Per serving</th>
          </tr>
        </thead>
        <tbody>
          {nutrients.map(([key, label, unit]) => (
            <tr key={key}>
              <th scope="row">{label}</th>
              {[recipe.total_nutrients[key], recipe.per_serving[key]].map(
                (value, index) => (
                  <td key={index}>
                    {value == null
                      ? "Unknown"
                      : `${Number(value.toFixed(2))} ${unit}`}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function CustomRecipesPanel({
  ownerId,
  onShoppingChanged,
}: {
  ownerId: string;
  onShoppingChanged?: () => void;
}) {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState<Mutation | null>(() =>
    recoverPending(ownerId),
  );
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState<Recipe | null>(null);
  const [conflict, setConflict] = useState(false);
  const [deleting, setDeleting] = useState<Recipe | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const lock = useRef(false);
  const alive = useRef(false);
  const requestNumber = useRef(0);

  const refresh = useCallback(async () => {
    const request = ++requestNumber.current;
    try {
      const response = await fetch(endpoint, {
        cache: "no-store",
        signal: AbortSignal.timeout(20_000),
      });
      if (!response.ok)
        throw new Error(
          response.status === 401
            ? "Your session expired. Sign in again to view your recipes."
            : "Your recipes could not be loaded. Please refresh.",
        );
      const next = (await response.json()) as Recipe[];
      if (!Array.isArray(next))
        throw new Error("Your recipes could not be loaded. Please refresh.");
      if (alive.current && request === requestNumber.current) setRecipes(next);
    } finally {
      if (alive.current && request === requestNumber.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    let active = true;
    alive.current = true;
    void refresh().catch((reason: unknown) => {
      if (active)
        setError(
          reason instanceof Error
            ? reason.message
            : "Your recipes could not be loaded.",
        );
    });
    return () => {
      active = false;
      alive.current = false;
      requestNumber.current += 1;
    };
  }, [refresh]);
  useEffect(() => {
    if (deleting) dialog.current?.showModal();
    else dialog.current?.close();
  }, [deleting]);

  const mutate = async (mutation: Mutation) => {
    if (lock.current) return;
    lock.current = true;
    setSaving(true);
    setError("");
    setNotice("");
    let confirmed = false;
    try {
      try {
        sessionStorage.setItem(
          pendingKey(ownerId),
          JSON.stringify({ version: 1, mutation }),
        );
      } catch {
        throw new Error(
          "Browser storage is unavailable. Enable storage before saving so an interrupted recipe change can be recovered.",
        );
      }
      const response = await fetch(`${endpoint}${mutation.path}`, {
        method: mutation.method,
        headers: mutation.body
          ? { "Content-Type": "application/json" }
          : undefined,
        body: mutation.body,
        signal: AbortSignal.timeout(20_000),
      });
      const definitive =
        response.ok ||
        (response.status < 500 &&
          response.status !== 408 &&
          response.status !== 429);
      if (definitive) {
        confirmed = true;
        try {
          sessionStorage.removeItem(pendingKey(ownerId));
        } catch {
          /* Replaying this request preserves its UUID/version. */
        }
      }
      if (!alive.current) return;
      if (definitive) setPending(null);
      if (
        !response.ok &&
        !(mutation.method === "DELETE" && response.status === 404)
      ) {
        if (response.status === 409) {
          setConflict(true);
          setDeleting(null);
          try {
            await refresh();
          } catch {
            /* Keep the conflict message and offer refresh. */
          }
        }
        throw new Error(
          response.status === 409
            ? "This recipe was changed or deleted. Your draft has not overwritten it. Review the latest saved recipe before editing again."
            : response.status === 401
              ? "Your session expired. Sign in again before saving."
              : response.status === 422
                ? "Some recipe values were rejected. Check the name, quantities, servings and nutrition values."
                : response.status === 429
                  ? "Please wait a moment, then retry this same recipe change."
                  : "Your recipe change could not be confirmed. Please retry.",
        );
      }
      setDraft(null);
      setEditing(null);
      setDeleting(null);
      setConflict(false);
      setNotice(
        mutation.method === "DELETE"
          ? "Recipe deleted."
          : "Recipe saved to your account.",
      );
      try {
        await refresh();
      } catch {
        if (alive.current)
          setError(
            "Your recipe change was saved, but the latest list could not be loaded. Refresh recipes; do not submit a new copy.",
          );
      }
    } catch (reason) {
      if (alive.current) {
        if (!confirmed) setPending(mutation);
        setDeleting(null);
        setError(
          reason instanceof Error &&
            !(reason instanceof TypeError) &&
            !(reason instanceof DOMException)
            ? reason.message
            : "Your recipe change could not be confirmed. Please retry.",
        );
      }
    } finally {
      lock.current = false;
      if (alive.current) setSaving(false);
    }
  };
  const updateIngredient = (index: number, patch: Partial<IngredientDraft>) => {
    setDraft((current) =>
      current
        ? {
            ...current,
            ingredients: current.ingredients.map((item, at) =>
              at === index ? { ...item, ...patch } : item,
            ),
          }
        : current,
    );
  };
  const disabled = loading || saving || pending !== null;
  const startEditing = (recipe?: Recipe) => {
    setDraft(recipeDraft(recipe));
    setEditing(recipe ?? null);
    setConflict(false);
    setError("");
    setNotice("");
  };

  return (
    <section
      className={`card ${styles.panel}`}
      aria-label="Custom recipes"
      aria-busy={loading || saving}
    >
      <div className={styles.heading}>
        <div>
          <p className="eyebrow">YOUR KITCHEN</p>
          <h2>Custom recipes</h2>
          <p>
            Save your own ingredients and portions privately to your account.
          </p>
        </div>
        <button
          className="primary"
          disabled={disabled || draft !== null}
          onClick={() => startEditing()}
        >
          Create recipe
        </button>
      </div>
      <p>
        Nutrition uses only the values you enter. Missing evidence stays
        unknown, not zero. Saving a recipe does not log a meal, change pantry
        stock or add shopping items.
      </p>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {loading && <p role="status">Loading your recipes…</p>}
      {pending && (
        <div className={styles.warning}>
          <p>
            A recipe change is awaiting confirmation. Retry sends the original
            ID and values, not a new copy. It is never retried automatically.
          </p>
          <button
            className="primary"
            disabled={loading || saving}
            onClick={() => void mutate(pending)}
          >
            Retry pending recipe change
          </button>
        </div>
      )}
      {draft && (
        <form
          className={styles.form}
          aria-label={editing ? "Edit custom recipe" : "New custom recipe"}
          onSubmit={(event) => {
            event.preventDefault();
            if (disabled || conflict || lock.current) return;
            const fields = parseDraft(draft);
            if (!fields) {
              setError(
                "Enter a recipe name, positive servings and ingredient quantities. Nutrition must be nonnegative or blank.",
              );
              return;
            }
            void mutate(
              editing
                ? {
                    method: "PUT",
                    path: `/${editing.id}`,
                    body: JSON.stringify({
                      ...fields,
                      expected_version: editing.version,
                    }),
                  }
                : {
                    method: "POST",
                    path: "",
                    body: JSON.stringify({
                      id: crypto.randomUUID(),
                      ...fields,
                    }),
                  },
            );
          }}
        >
          <h3>{editing ? "Edit recipe" : "New recipe"}</h3>
          <fieldset disabled={disabled || conflict} className={styles.fields}>
            <legend>Recipe details</legend>
            <div className={styles.row}>
              <label>
                Recipe name
                <input
                  value={draft.name}
                  required
                  maxLength={200}
                  onChange={(event) =>
                    setDraft({ ...draft, name: event.target.value })
                  }
                />
              </label>
              <label>
                Number of servings
                <input
                  type="number"
                  min="0.001"
                  max="1000"
                  step="any"
                  required
                  value={draft.servings}
                  onChange={(event) =>
                    setDraft({ ...draft, servings: event.target.value })
                  }
                />
              </label>
            </div>
            {draft.ingredients.map((item, index) => (
              <fieldset key={item.key} className={styles.ingredient}>
                <legend>Ingredient {index + 1}</legend>
                <div className={styles.row}>
                  <label>
                    Ingredient name
                    <input
                      value={item.name}
                      maxLength={200}
                      required
                      onChange={(event) =>
                        updateIngredient(index, { name: event.target.value })
                      }
                    />
                  </label>
                  <label>
                    Quantity
                    <input
                      type="number"
                      min="0.001"
                      max="100000"
                      step="any"
                      value={item.quantity}
                      required
                      onChange={(event) =>
                        updateIngredient(index, {
                          quantity: event.target.value,
                        })
                      }
                    />
                  </label>
                  <label>
                    Unit
                    <input
                      value={item.unit}
                      maxLength={30}
                      required
                      placeholder="e.g. g, ml, cup"
                      onChange={(event) =>
                        updateIngredient(index, { unit: event.target.value })
                      }
                    />
                  </label>
                </div>
                <details className={styles.evidence}>
                  <summary>
                    Optional nutrition for ingredient {index + 1}
                  </summary>
                  <p>
                    Enter totals for the full quantity listed above, not per 100
                    g, per 100 ml or per serving. Changing quantity does not
                    recalculate these evidence values. Leave unverified
                    nutrients blank.
                  </p>
                  <div className={styles.nutrientInputs}>
                    {nutrients.map(([key, label, unit]) => (
                      <label key={key}>
                        {label} ({unit})
                        <input
                          type="number"
                          min="0"
                          max="1000000"
                          step="any"
                          value={item.nutrients[key] ?? ""}
                          placeholder="Unknown"
                          onChange={(event) =>
                            updateIngredient(index, {
                              nutrients: {
                                ...item.nutrients,
                                [key]: event.target.value,
                              },
                            })
                          }
                        />
                      </label>
                    ))}
                  </div>
                  <label>
                    Nutrition source
                    <input
                      value={item.source_label}
                      maxLength={200}
                      required
                      onChange={(event) =>
                        updateIngredient(index, {
                          source_label: event.target.value,
                        })
                      }
                    />
                  </label>
                </details>
                <button
                  type="button"
                  className="outline-button"
                  disabled={draft.ingredients.length === 1}
                  aria-label={`Remove ingredient ${index + 1}`}
                  onClick={() =>
                    setDraft({
                      ...draft,
                      ingredients: draft.ingredients.filter(
                        (_, at) => at !== index,
                      ),
                    })
                  }
                >
                  Remove ingredient
                </button>
              </fieldset>
            ))}
            <button
              type="button"
              className="outline-button"
              disabled={draft.ingredients.length >= 100}
              onClick={() =>
                setDraft({
                  ...draft,
                  ingredients: [...draft.ingredients, freshIngredient()],
                })
              }
            >
              Add ingredient
            </button>
            <label>
              Recipe notes
              <textarea
                value={draft.notes}
                maxLength={4000}
                rows={3}
                onChange={(event) =>
                  setDraft({ ...draft, notes: event.target.value })
                }
              />
            </label>
          </fieldset>
          {conflict && (
            <p className={styles.warning}>
              Your draft is kept here for reference but cannot overwrite a newer
              version. Cancel this edit, then choose Edit on the refreshed
              recipe.
            </p>
          )}
          <div className={styles.row}>
            <button
              className="primary"
              type="submit"
              disabled={disabled || conflict}
            >
              {editing ? "Save recipe changes" : "Save recipe"}
            </button>
            <button
              className="outline-button"
              type="button"
              disabled={saving || pending !== null}
              onClick={() => {
                setDraft(null);
                setEditing(null);
                setConflict(false);
              }}
            >
              Cancel recipe edit
            </button>
          </div>
        </form>
      )}
      {!loading && !error && recipes.length === 0 && (
        <p>No custom recipes saved yet.</p>
      )}
      {recipes.length >= 200 && (
        <p>
          Showing the first 200 saved recipes. Older recipes remain in your
          account and account export.
        </p>
      )}
      <div className={styles.recipes}>
        {recipes.map((recipe) => (
          <article
            key={recipe.id}
            className={styles.recipe}
            aria-label={`Recipe: ${recipe.name}`}
          >
            <div className={styles.heading}>
              <div>
                <h3>{recipe.name}</h3>
                <p>
                  {recipe.servings} serving{recipe.servings === 1 ? "" : "s"} ·
                  User-entered recipe
                </p>
              </div>
              <div className={styles.row}>
                <button
                  className="outline-button"
                  disabled={disabled || draft !== null}
                  aria-label={`Edit recipe ${recipe.name}`}
                  onClick={() => startEditing(recipe)}
                >
                  Edit
                </button>
                <button
                  className="outline-button"
                  disabled={disabled || draft !== null}
                  aria-label={`Delete recipe ${recipe.name}`}
                  onClick={() => setDeleting(recipe)}
                >
                  Delete
                </button>
              </div>
            </div>
            <ul>
              {recipe.ingredients.map((item, index) => (
                <li key={index}>
                  {item.name} — {item.quantity} {item.unit}
                  <small>Nutrition source: {item.source_label}</small>
                </li>
              ))}
            </ul>
            {recipe.notes && <p className={styles.notes}>{recipe.notes}</p>}
            <RecipeNutrition recipe={recipe} />
            <p>
              Unknown means at least one ingredient lacks that nutrient value.
              These values are user-entered, not independently verified.
            </p>
          </article>
        ))}
      </div>
      <CustomRecipeActions
        key={ownerId}
        ownerId={ownerId}
        recipes={recipes}
        disabled={loading || saving || pending !== null || draft !== null}
        onShoppingChanged={onShoppingChanged}
      />
      <button
        className="outline-button"
        disabled={loading || saving}
        onClick={() => {
          setLoading(true);
          setError("");
          void refresh().catch((reason: unknown) => {
            if (alive.current)
              setError(
                reason instanceof Error
                  ? reason.message
                  : "Your recipes could not be loaded.",
              );
          });
        }}
      >
        Refresh recipes
      </button>
      <dialog
        ref={dialog}
        className={styles.confirm}
        aria-labelledby="delete-custom-recipe-title"
        onCancel={(event) => {
          if (saving) event.preventDefault();
          else setDeleting(null);
        }}
      >
        <h3 id="delete-custom-recipe-title">Delete this recipe?</h3>
        <p>
          {deleting?.name} will be removed from your saved recipes. This does
          not change your meal diary or pantry.
        </p>
        <div className={styles.row}>
          <button
            className="outline-button"
            disabled={saving}
            onClick={() => setDeleting(null)}
            autoFocus
          >
            Keep recipe
          </button>
          <button
            className="primary"
            disabled={saving || !deleting}
            onClick={() => {
              if (deleting)
                void mutate({
                  method: "DELETE",
                  path: `/${deleting.id}?expected_version=${deleting.version}`,
                });
            }}
          >
            Confirm delete recipe
          </button>
        </div>
      </dialog>
    </section>
  );
}
