"use client";

import { useEffect, useRef, useState } from "react";
import styles from "./custom-recipes-panel.module.css";

type RecipeOption = {
  id: string;
  name: string;
  version: number;
  servings: number;
};
type Check = {
  check_token: string;
  recipe_id: string;
  recipe_version: number;
  servings: number;
  ingredients: Array<{
    key: string;
    name: string;
    unit: string;
    required_quantity: number;
    available_quantity: number | null;
    missing_quantity: number | null;
    status: "AVAILABLE" | "MISSING" | "UNIT_MISMATCH";
    pantry_item_ids: string[];
  }>;
  limitation: string;
};
type Pending = {
  recipeId: string;
  recipeName: string;
  action: "diary" | "shopping-list";
  body: string;
};
const key = (owner: string) =>
  `nutrilens.recipe-actions.pending.v1:${encodeURIComponent(owner)}`;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function recover(owner: string): Pending | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(key(owner));
    if (!raw || raw.length > 50_000) return null;
    const pending = JSON.parse(raw) as Pending;
    if (
      !uuid.test(pending.recipeId) ||
      typeof pending.recipeName !== "string" ||
      typeof pending.body !== "string" ||
      !["diary", "shopping-list"].includes(pending.action)
    )
      return null;
    const body = JSON.parse(pending.body) as {
      id: string;
      expected_version: number;
      servings: number;
      eaten_at?: string;
      ingredient_keys?: string[];
      check_token?: string;
    };
    if (
      !uuid.test(body.id) ||
      !Number.isSafeInteger(body.expected_version) ||
      body.expected_version < 1 ||
      !Number.isFinite(body.servings) ||
      body.servings < 0.001 ||
      body.servings > 1000
    )
      return null;
    if (
      pending.action === "diary" &&
      (!body.eaten_at || !Number.isFinite(Date.parse(body.eaten_at)))
    )
      return null;
    if (
      pending.action === "shopping-list" &&
      (!/^[0-9a-f]{64}$/.test(body.check_token ?? "") ||
        !Array.isArray(body.ingredient_keys) ||
        body.ingredient_keys.length < 1 ||
        body.ingredient_keys.length > 100 ||
        !body.ingredient_keys.every(
          (value) => typeof value === "string" && value.length <= 300,
        ))
    )
      return null;
    return pending;
  } catch {
    return null;
  }
}
function localNow(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}

/** A separate, owner-keyed action journal survives recipe deletion/list failures and reloads. */
export function CustomRecipeActions({
  ownerId,
  recipes,
  disabled,
  onShoppingChanged,
}: {
  ownerId: string;
  recipes: RecipeOption[];
  disabled: boolean;
  onShoppingChanged?: () => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [servings, setServings] = useState("1");
  const [eatenAt, setEatenAt] = useState("");
  const [consumed, setConsumed] = useState(false);
  const [check, setCheck] = useState<Check | null>(null);
  const [selectedKeys, setSelectedKeys] = useState<string[]>([]);
  const [pending, setPending] = useState<Pending | null>(() =>
    recover(ownerId),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const alive = useRef(false);
  const lock = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const recipe = recipes.find((item) => item.id === selectedId);
  const amount = Number(servings);
  const validAmount =
    Number.isFinite(amount) && amount >= 0.001 && amount <= 1000;
  const locked = disabled || busy || pending !== null;
  const currentCheck =
    check &&
    recipe?.id === check.recipe_id &&
    recipe.version === check.recipe_version &&
    amount === check.servings
      ? check
      : null;
  const resetCheck = () => {
    setCheck(null);
    setSelectedKeys([]);
    setNotice("");
    setError("");
  };
  const failure = (status: number) =>
    status === 409
      ? "The recipe or ingredient availability changed. Refresh recipes and check your pantry again before a new action. Nothing was overwritten."
      : status === 401
        ? "Your session expired. Sign in to continue."
        : status === 404
          ? "This recipe is no longer available in your account."
          : status === 422
            ? "The selected values were rejected. Review servings, time and ingredients."
            : "This action could not be confirmed. Retry the pending action without creating a new one.";

  const mutate = async (action: Pending) => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    let definitive = false;
    try {
      try {
        sessionStorage.setItem(key(ownerId), JSON.stringify(action));
      } catch {
        throw new Error(
          "Enable browser storage before continuing so an interrupted action can be safely recovered.",
        );
      }
      setPending(action);
      const response = await fetch(
        `/api/backend/recipes/custom/${action.recipeId}/${action.action}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: action.body,
          signal: AbortSignal.timeout(20_000),
        },
      );
      let generated = 0;
      if (response.ok) {
        const result = (await response.json()) as { generated_count?: number };
        generated = result.generated_count ?? 0;
      }
      // Expired auth or temporary owner visibility must not discard a possibly
      // committed request. Its original UUID remains the only safe retry.
      definitive =
        response.ok || response.status === 409 || response.status === 422;
      if (definitive) {
        try {
          sessionStorage.removeItem(key(ownerId));
        } catch {
          /* Same UUID remains safe to replay. */
        }
      }
      if (!alive.current) return;
      if (definitive) setPending(null);
      if (response.status === 409) {
        setCheck(null);
        setSelectedKeys([]);
        setConsumed(false);
      }
      if (!response.ok) throw new Error(failure(response.status));
      setConsumed(false);
      setCheck(null);
      setSelectedKeys([]);
      setNotice(
        action.action === "diary"
          ? `${action.recipeName}: consumed servings saved to your diary. Pantry stock was not changed.`
          : `${generated} missing ingredient${generated === 1 ? "" : "s"} added to shopping. Existing entries are not duplicated.`,
      );
      if (action.action === "shopping-list") onShoppingChanged?.();
    } catch (reason) {
      if (alive.current) {
        if (!definitive) setPending(action);
        setError(
          reason instanceof Error &&
            !(reason instanceof TypeError) &&
            !(reason instanceof DOMException)
            ? reason.message
            : "This action could not be confirmed. Retry the pending action without creating a new one.",
        );
      }
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const checkPantry = async () => {
    if (!recipe || !validAmount || locked || lock.current) return;
    lock.current = true;
    setBusy(true);
    resetCheck();
    try {
      const response = await fetch(
        `/api/backend/recipes/custom/${recipe.id}/pantry-check`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_version: recipe.version,
            servings: amount,
          }),
          signal: AbortSignal.timeout(20_000),
        },
      );
      if (!response.ok) throw new Error(failure(response.status));
      const result = (await response.json()) as Check;
      if (alive.current) setCheck(result);
    } catch (reason) {
      if (alive.current)
        setError(
          reason instanceof Error &&
            !(reason instanceof TypeError) &&
            !(reason instanceof DOMException)
            ? reason.message
            : "Pantry check could not be loaded. No diary, stock or shopping changes were made.",
        );
    } finally {
      lock.current = false;
      if (alive.current) setBusy(false);
    }
  };

  return (
    <section
      className={styles.form}
      aria-label="Use a saved recipe"
      aria-busy={busy}
    >
      <h3>Use a saved recipe</h3>
      <p>
        Logging records only servings you confirm you consumed. Pantry checks do
        not change stock; adding shopping items is a separate choice.
      </p>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {pending && (
        <div className={styles.warning}>
          <p>
            An action for {pending.recipeName} is awaiting confirmation. Retry
            reuses its original ID, serving quantity and values, even after a
            refresh. It is never retried automatically.
          </p>
          <button
            className="primary"
            disabled={disabled || busy}
            onClick={() => void mutate(pending)}
          >
            Retry pending recipe action
          </button>
        </div>
      )}
      <fieldset disabled={locked} className={styles.fields}>
        <legend>Choose recipe and portions</legend>
        <div className={styles.row}>
          <label>
            Saved recipe
            <select
              value={selectedId}
              onChange={(event) => {
                setSelectedId(event.target.value);
                setEatenAt(localNow());
                setConsumed(false);
                resetCheck();
              }}
            >
              <option value="">Choose a saved recipe</option>
              {recipes.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Recipe servings to use
            <input
              type="number"
              min="0.001"
              max="1000"
              step="any"
              value={servings}
              onChange={(event) => {
                setServings(event.target.value);
                setConsumed(false);
                resetCheck();
              }}
            />
          </label>
        </div>
        {recipe && (
          <p>
            One serving is 1/{recipe.servings} of the saved recipe. Unknown
            ingredient nutrition stays unknown. No serving weight is assumed.
          </p>
        )}
        <label>
          Consumed at (your local time)
          <input
            type="datetime-local"
            value={eatenAt}
            onChange={(event) => {
              setEatenAt(event.target.value);
              setConsumed(false);
            }}
          />
        </label>
        <label className={styles.checkChoice}>
          <input
            type="checkbox"
            checked={consumed}
            onChange={(event) => setConsumed(event.target.checked)}
          />
          I consumed these recipe servings
        </label>
        <div className={styles.row}>
          <button
            className="primary"
            disabled={
              !recipe ||
              !validAmount ||
              !consumed ||
              !eatenAt ||
              !Number.isFinite(Date.parse(eatenAt))
            }
            onClick={() => {
              if (!recipe || !consumed || !validAmount || !eatenAt) return;
              void mutate({
                recipeId: recipe.id,
                recipeName: recipe.name,
                action: "diary",
                body: JSON.stringify({
                  id: crypto.randomUUID(),
                  expected_version: recipe.version,
                  servings: amount,
                  eaten_at: new Date(eatenAt).toISOString(),
                }),
              });
            }}
          >
            Log consumed servings
          </button>
          <button
            className="outline-button"
            disabled={!recipe || !validAmount}
            onClick={() => void checkPantry()}
          >
            Check recipe against pantry
          </button>
        </div>
      </fieldset>
      {currentCheck && (
        <div>
          <h4>Pantry ingredient check</h4>
          <p>{currentCheck.limitation}</p>
          <ul>
            {currentCheck.ingredients.map((item) => (
              <li key={item.key}>
                <span>
                  {item.name}: needs {item.required_quantity} {item.unit}.{" "}
                </span>
                {item.status === "UNIT_MISMATCH" ? (
                  <span>
                    Quantity unknown: pantry units cannot be safely compared.
                    Review manually; no shopping quantity was inferred.
                  </span>
                ) : item.status === "AVAILABLE" ? (
                  <span>Available in your pantry.</span>
                ) : (
                  <label className={styles.checkChoice}>
                    <input
                      type="checkbox"
                      checked={selectedKeys.includes(item.key)}
                      disabled={locked}
                      onChange={(event) => {
                        setSelectedKeys((current) =>
                          event.target.checked
                            ? [...current, item.key]
                            : current.filter((value) => value !== item.key),
                        );
                      }}
                    />
                    Add missing {item.missing_quantity} {item.unit} of{" "}
                    {item.name}
                  </label>
                )}
              </li>
            ))}
          </ul>
          <button
            className="primary"
            disabled={locked || selectedKeys.length === 0}
            onClick={() => {
              if (!recipe || selectedKeys.length === 0) return;
              void mutate({
                recipeId: recipe.id,
                recipeName: recipe.name,
                action: "shopping-list",
                body: JSON.stringify({
                  id: crypto.randomUUID(),
                  expected_version: recipe.version,
                  servings: amount,
                  ingredient_keys: selectedKeys,
                  check_token: currentCheck.check_token,
                }),
              });
            }}
          >
            Add selected missing ingredients to shopping
          </button>
        </div>
      )}
    </section>
  );
}
