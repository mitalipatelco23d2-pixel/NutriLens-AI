"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { CreditCard, RefreshCw, Scale, ShieldCheck, Users } from "lucide-react";
import { useEffect, useState } from "react";

type BillingAccount = {
  plan: string;
  subscription_status: string;
  mode: string;
  subscription: {
    provider_subscription_id: string;
    plan: string;
    interval: string;
    status: string;
    next_renewal: string | null;
    provider: string;
  } | null;
  payments: {
    provider_payment_id: string;
    amount_paise: number | null;
    currency: string;
    status: string;
    created_at: string;
  }[];
};

type WellnessGoal =
  | "balanced"
  | "maintain-weight"
  | "lose-weight-gradually"
  | "gain-weight-gradually"
  | "improve-nutrition"
  | "high-protein"
  | "low-sugar"
  | "low-sodium"
  | "custom";

type HealthProfile = {
  goal: WellnessGoal;
  custom_goal: string | null;
  allergens: string[];
  dietary_preferences: string[];
  consent_personalization: boolean;
  daily_targets: {
    calories: number | null;
    protein_g: number | null;
    fiber_g: number | null;
    sodium_mg: number | null;
    calcium_mg: number | null;
    iron_mg: number | null;
  };
  body_context: {
    adult_attestation: boolean;
    consent_bmi_context: boolean;
    height_cm: number | null;
    weight_kg: number | null;
  };
};

type BmiContext = {
  state: "NOT_CONFIGURED" | "AVAILABLE";
  bmi: number | null;
  limitation: string;
  reference_url: string;
};

type HouseholdProfile = {
  id: string;
  display_name: string;
  relationship: string | null;
  profile: HealthProfile;
  created_at: string;
  updated_at: string;
};

type WeightEntry = {
  id: string;
  weight_kg: number;
  recorded_at: string;
  source: "USER_ENTERED";
};

type WeightSummary = {
  state: "DISABLED" | "ACTIVE";
  target_weight_kg: number | null;
  latest_weight_kg: number | null;
  change_from_first_kg: number | null;
  difference_from_target_kg: number | null;
  entries: WeightEntry[];
  method: string;
  limitation: string;
};

const wellnessGoals: ReadonlyArray<{ value: WellnessGoal; label: string }> = [
  { value: "balanced", label: "Balanced eating" },
  { value: "maintain-weight", label: "Maintain weight" },
  { value: "lose-weight-gradually", label: "Lose weight gradually" },
  { value: "gain-weight-gradually", label: "Gain weight gradually" },
  { value: "improve-nutrition", label: "Improve nutrition" },
  { value: "high-protein", label: "Higher protein preference" },
  { value: "low-sugar", label: "Lower sugar preference" },
  { value: "low-sodium", label: "Lower sodium preference" },
  { value: "custom", label: "Custom goal" },
];

const wellnessGoalLabel = (goal: WellnessGoal) =>
  wellnessGoals.find(({ value }) => value === goal)?.label ?? goal;

const formatKg = (value: number | null) =>
  value === null ? "Not recorded" : `${value.toLocaleString("en-IN")} kg`;

const emptyHealthProfile = (): HealthProfile => ({
  goal: "balanced",
  custom_goal: null,
  allergens: [],
  dietary_preferences: [],
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

async function fetchBillingAccount(): Promise<
  BillingAccount | "UNAUTHENTICATED"
> {
  const response = await fetch("/api/backend/payments/account", {
    cache: "no-store",
  });
  if (response.status === 401) return "UNAUTHENTICATED";
  if (!response.ok)
    throw new Error("Billing details are temporarily unavailable.");
  return (await response.json()) as BillingAccount;
}

export function BillingPage() {
  const router = useRouter();
  const [account, setAccount] = useState<BillingAccount | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<HealthProfile | null>(null);
  const [profileMessage, setProfileMessage] = useState("");
  const [bmiContext, setBmiContext] = useState<BmiContext | null>(null);
  const [weightSummary, setWeightSummary] = useState<WeightSummary | null>(
    null,
  );
  const [weightMessage, setWeightMessage] = useState("");
  const [weightDraft, setWeightDraft] = useState("");
  const [weightTargetDraft, setWeightTargetDraft] = useState("");
  const [editingWeightId, setEditingWeightId] = useState<string | null>(null);
  const [weightConsent, setWeightConsent] = useState(false);
  const [weightDeleteId, setWeightDeleteId] = useState<string | null>(null);
  const [weightEraseText, setWeightEraseText] = useState("");
  const [householdProfiles, setHouseholdProfiles] = useState<
    HouseholdProfile[]
  >([]);
  const [householdDraft, setHouseholdDraft] = useState<{
    id?: string;
    display_name: string;
    relationship: string;
    profile: HealthProfile;
  }>({ display_name: "", relationship: "", profile: emptyHealthProfile() });
  const [householdMessage, setHouseholdMessage] = useState("");
  const [confirmationDialog, setConfirmationDialog] = useState<
    "cancel-subscription" | "delete-account" | "delete-household" | null
  >(null);
  const [confirmationText, setConfirmationText] = useState("");
  const [householdToDelete, setHouseholdToDelete] =
    useState<HouseholdProfile | null>(null);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const result = await fetchBillingAccount();
        if (result === "UNAUTHENTICATED") router.push("/login?next=%2Faccount");
        else if (active) setAccount(result);
      } catch (reason) {
        if (active) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Billing could not be loaded.",
          );
        }
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [router]);

  useEffect(() => {
    let active = true;
    fetch("/api/backend/profile", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: unknown) => {
        if (active && payload) setProfile(payload as HealthProfile);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const refreshWeight = async () => {
    const response = await fetch("/api/backend/weight", {
      cache: "no-store",
    });
    if (!response.ok) throw new Error("Weight history could not be loaded.");
    const summary = (await response.json()) as WeightSummary;
    setWeightSummary(summary);
    setWeightTargetDraft(
      summary.target_weight_kg === null ? "" : String(summary.target_weight_kg),
    );
  };

  const refreshWeightAfterMutation = async (successMessage: string) => {
    try {
      await refreshWeight();
      setWeightMessage(successMessage);
    } catch {
      setWeightMessage(
        `${successMessage} The latest summary could not be reloaded; refresh before making another change.`,
      );
    }
  };

  useEffect(() => {
    let active = true;
    fetch("/api/backend/weight", { cache: "no-store" })
      .then((response) => {
        if (!response.ok)
          throw new Error("Weight history could not be loaded.");
        return response.json();
      })
      .then((payload: unknown) => {
        if (!active || !payload) return;
        const summary = payload as WeightSummary;
        setWeightSummary(summary);
        setWeightTargetDraft(
          summary.target_weight_kg === null
            ? ""
            : String(summary.target_weight_kg),
        );
      })
      .catch(() => {
        if (active) setWeightMessage("Weight history could not be loaded.");
      });
    return () => {
      active = false;
    };
  }, []);

  const refreshBmiContext = async () => {
    const response = await fetch("/api/backend/profile/bmi-context", {
      cache: "no-store",
    });
    if (response.ok) setBmiContext((await response.json()) as BmiContext);
  };

  useEffect(() => {
    let active = true;
    fetch("/api/backend/profile/bmi-context", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload: unknown) => {
        if (active && payload) setBmiContext(payload as BmiContext);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    fetch("/api/backend/profile/household", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : []))
      .then((payload: unknown) => {
        if (active) setHouseholdProfiles(payload as HouseholdProfile[]);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const act = async (action: "cancel" | "resume") => {
    if (!account?.subscription) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(
        `/api/backend/payments/subscriptions/${encodeURIComponent(account.subscription.provider_subscription_id)}/${action}`,
        { method: "POST" },
      );
      const payload = (await response.json()) as { detail?: string };
      if (!response.ok)
        throw new Error(payload.detail ?? `Could not ${action} subscription.`);
      const result = await fetchBillingAccount();
      if (result !== "UNAUTHENTICATED") setAccount(result);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Billing action failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const exportData = async () => {
    setError("");
    const response = await fetch("/api/backend/account/export", {
      cache: "no-store",
    });
    if (!response.ok) {
      setError("Your export could not be prepared.");
      return;
    }
    const blob = await response.blob();
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `nutrilens-export-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(href);
  };

  const deleteAccount = async () => {
    if (confirmationText !== "DELETE") return;
    setBusy(true);
    const response = await fetch("/api/backend/account", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation: confirmationText }),
    });
    if (!response.ok) {
      setError("Account deletion could not be completed.");
      setBusy(false);
      return;
    }
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/");
    router.refresh();
  };

  const saveProfile = async () => {
    if (!profile) return;
    if (profile.goal === "custom" && !profile.custom_goal?.trim()) {
      setProfileMessage("Describe your custom goal before saving.");
      return;
    }
    setBusy(true);
    setProfileMessage("");
    const response = await fetch("/api/backend/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    setProfileMessage(
      response.ok ? "Preferences saved." : "Preferences could not be saved.",
    );
    if (response.ok) await refreshBmiContext();
    setBusy(false);
  };

  const enableWeightTracking = async () => {
    if (!weightConsent) return;
    setBusy(true);
    setWeightMessage("");
    try {
      const response = await fetch("/api/backend/weight/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_weight_kg: null }),
      });
      if (!response.ok)
        throw new Error("Weight tracking could not be enabled.");
      setWeightConsent(false);
      await refreshWeightAfterMutation("Optional weight tracking enabled.");
    } catch (reason) {
      setWeightMessage(
        reason instanceof Error ? reason.message : "Weight action failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const saveWeightTarget = async () => {
    const target = weightTargetDraft === "" ? null : Number(weightTargetDraft);
    if (
      target !== null &&
      (!Number.isFinite(target) || target < 20 || target > 500)
    ) {
      setWeightMessage("Enter a target from 20 to 500 kg, or leave it blank.");
      return;
    }
    setBusy(true);
    setWeightMessage("");
    try {
      const response = await fetch("/api/backend/weight/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_weight_kg: target }),
      });
      if (!response.ok)
        throw new Error("The optional target could not be saved.");
      await refreshWeightAfterMutation(
        target === null ? "Target removed." : "Target saved.",
      );
    } catch (reason) {
      setWeightMessage(
        reason instanceof Error ? reason.message : "Weight action failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const saveWeightRecord = async () => {
    const value = Number(weightDraft);
    if (!Number.isFinite(value) || value < 20 || value > 500) {
      setWeightMessage("Enter a weight from 20 to 500 kg.");
      return;
    }
    const existing = weightSummary?.entries.find(
      ({ id }) => id === editingWeightId,
    );
    const path = existing
      ? `/api/backend/weight/entries/${encodeURIComponent(existing.id)}`
      : "/api/backend/weight/entries";
    const body = existing
      ? { weight_kg: value, recorded_at: existing.recorded_at }
      : {
          id: crypto.randomUUID(),
          weight_kg: value,
          recorded_at: new Date().toISOString(),
        };
    setBusy(true);
    setWeightMessage("");
    try {
      const response = await fetch(path, {
        method: existing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok)
        throw new Error("The weight record could not be saved.");
      setWeightDraft("");
      setEditingWeightId(null);
      await refreshWeightAfterMutation(
        existing ? "Weight record updated." : "Weight record added.",
      );
    } catch (reason) {
      setWeightMessage(
        reason instanceof Error ? reason.message : "Weight action failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const deleteWeightRecord = async () => {
    if (!weightDeleteId) return;
    setBusy(true);
    setWeightMessage("");
    try {
      const response = await fetch(
        `/api/backend/weight/entries/${encodeURIComponent(weightDeleteId)}`,
        { method: "DELETE" },
      );
      if (!response.ok)
        throw new Error("The weight record could not be deleted.");
      if (editingWeightId === weightDeleteId) {
        setEditingWeightId(null);
        setWeightDraft("");
      }
      setWeightDeleteId(null);
      await refreshWeightAfterMutation("Weight record deleted.");
    } catch (reason) {
      setWeightMessage(
        reason instanceof Error ? reason.message : "Weight action failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const disableWeightTracking = async () => {
    if (weightEraseText !== "ERASE") return;
    setBusy(true);
    setWeightMessage("");
    try {
      const response = await fetch("/api/backend/weight/settings", {
        method: "DELETE",
      });
      if (!response.ok)
        throw new Error("Weight tracking could not be disabled.");
      setWeightEraseText("");
      setWeightDraft("");
      setEditingWeightId(null);
      setWeightDeleteId(null);
      await refreshWeightAfterMutation(
        "Weight tracking disabled and NutriLens weight data erased.",
      );
    } catch (reason) {
      setWeightMessage(
        reason instanceof Error ? reason.message : "Weight action failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const setDailyTarget = (
    field: keyof HealthProfile["daily_targets"],
    value: string,
  ) => {
    if (!profile) return;
    const parsed = value === "" ? null : Number(value);
    setProfile({
      ...profile,
      daily_targets: {
        ...profile.daily_targets,
        [field]: parsed !== null && Number.isFinite(parsed) ? parsed : null,
      },
    });
  };

  const resetHouseholdDraft = () =>
    setHouseholdDraft({
      display_name: "",
      relationship: "",
      profile: emptyHealthProfile(),
    });

  const saveHouseholdProfile = async () => {
    if (!householdDraft.display_name.trim()) return;
    setBusy(true);
    setHouseholdMessage("");
    const editing = Boolean(householdDraft.id);
    const response = await fetch(
      editing
        ? `/api/backend/profile/household/${encodeURIComponent(householdDraft.id!)}`
        : "/api/backend/profile/household",
      {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          display_name: householdDraft.display_name,
          relationship: householdDraft.relationship || null,
          profile: householdDraft.profile,
        }),
      },
    );
    if (response.ok) {
      const saved = (await response.json()) as HouseholdProfile;
      setHouseholdProfiles((profiles) =>
        editing
          ? profiles.map((item) => (item.id === saved.id ? saved : item))
          : [...profiles, saved],
      );
      resetHouseholdDraft();
      setHouseholdMessage(
        editing ? "Household profile updated." : "Household profile added.",
      );
    } else {
      const payload = (await response.json().catch(() => null)) as {
        detail?: string;
      } | null;
      setHouseholdMessage(
        payload?.detail ?? "Household profile could not be saved.",
      );
    }
    setBusy(false);
  };

  const deleteHouseholdProfile = async (item: HouseholdProfile) => {
    setBusy(true);
    const response = await fetch(
      `/api/backend/profile/household/${encodeURIComponent(item.id)}`,
      { method: "DELETE" },
    );
    if (response.ok) {
      setHouseholdProfiles((profiles) =>
        profiles.filter(({ id }) => id !== item.id),
      );
      if (householdDraft.id === item.id) resetHouseholdDraft();
      setHouseholdMessage("Household profile deleted.");
    } else {
      setHouseholdMessage("Household profile could not be deleted.");
    }
    setBusy(false);
  };

  return (
    <div className="billing-shell">
      <header className="simple-nav">
        <Link className="brand-link" href="/">
          NutriLens <span>X</span>
        </Link>
        <Link href="/dashboard">Back to dashboard</Link>
      </header>
      <main className="billing-main" id="main-content" tabIndex={-1}>
        <p className="section-kicker">Account & billing</p>
        <h1>Your NutriLens plan, without surprises.</h1>
        {!account && !error && <p>Loading secure billing details…</p>}
        {error && <p className="billing-error">{error}</p>}
        {account && (
          <>
            <section className="billing-summary">
              <article>
                <span>Current plan</span>
                <strong>{account.plan}</strong>
                <small>
                  {account.subscription_status.replaceAll("_", " ")}
                </small>
              </article>
              <article>
                <span>Billing</span>
                <strong>
                  {account.subscription?.interval ?? "No recurring billing"}
                </strong>
                <small>
                  {account.subscription?.next_renewal
                    ? `Next renewal ${new Date(account.subscription.next_renewal).toLocaleDateString()}`
                    : "Renewal date not yet available"}
                </small>
              </article>
              <article>
                <span>Provider</span>
                <strong>{account.subscription?.provider ?? "None"}</strong>
                <small>{account.mode.toUpperCase()} MODE</small>
              </article>
            </section>
            <section className="billing-actions card">
              <div>
                <CreditCard />
                <div>
                  <h2>Manage subscription</h2>
                  <p>
                    Plan changes are verified by the backend and confirmed by
                    signed webhooks.
                  </p>
                </div>
              </div>
              <div>
                <Link href="/pricing">Upgrade or change plan</Link>
                {account.subscription?.status === "PAUSED" && (
                  <button disabled={busy} onClick={() => act("resume")}>
                    <RefreshCw size={15} /> Resume
                  </button>
                )}
                {account.subscription &&
                  !["CANCELLED", "EXPIRED"].includes(
                    account.subscription.status,
                  ) && (
                    <button
                      className="danger-action"
                      disabled={busy}
                      onClick={() =>
                        setConfirmationDialog("cancel-subscription")
                      }
                    >
                      Cancel at cycle end
                    </button>
                  )}
              </div>
            </section>
            <section className="payment-history card">
              <div className="billing-section-title">
                <div>
                  <h2>Payment history</h2>
                  <p>
                    No card, bank, or mandate details are stored or displayed
                    here.
                  </p>
                </div>
                <ShieldCheck />
              </div>
              {account.payments.length === 0 ? (
                <p className="empty-billing">No verified payments yet.</p>
              ) : (
                <div className="payment-list">
                  {account.payments.map((payment) => (
                    <div key={payment.provider_payment_id}>
                      <span>
                        {new Date(payment.created_at).toLocaleDateString()}
                      </span>
                      <strong>
                        {payment.amount_paise === null
                          ? "Amount pending"
                          : new Intl.NumberFormat("en-IN", {
                              style: "currency",
                              currency: payment.currency,
                            }).format(payment.amount_paise / 100)}
                      </strong>
                      <small>{payment.status}</small>
                    </div>
                  ))}
                </div>
              )}
            </section>
            {profile && (
              <section className="profile-controls card">
                <div>
                  <h2>Personalization</h2>
                  <p>
                    These preferences tune wellness guidance. Allergen matches
                    are evidence prompts, never a guarantee of safety.
                  </p>
                </div>
                <div className="profile-fields">
                  <label>
                    Primary goal
                    <select
                      value={profile.goal}
                      onChange={(event) => {
                        const goal = event.target.value as WellnessGoal;
                        setProfile({
                          ...profile,
                          goal,
                          custom_goal:
                            goal === "custom"
                              ? (profile.custom_goal ?? "")
                              : null,
                        });
                      }}
                    >
                      {wellnessGoals.map(({ value, label }) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {profile.goal === "custom" && (
                    <label>
                      Describe your custom goal
                      <input
                        maxLength={120}
                        required
                        value={profile.custom_goal ?? ""}
                        onChange={(event) =>
                          setProfile({
                            ...profile,
                            custom_goal: event.target.value,
                          })
                        }
                      />
                    </label>
                  )}
                  <p className="profile-safety-note">
                    Weight-related choices record your intent only. NutriLens
                    does not prescribe a pace, calorie deficit, diagnosis, or
                    treatment.
                  </p>
                  <label>
                    Allergens (comma separated)
                    <input
                      value={profile.allergens.join(", ")}
                      onChange={(event) =>
                        setProfile({
                          ...profile,
                          allergens: event.target.value
                            .split(",")
                            .map((item) => item.trim())
                            .filter(Boolean),
                        })
                      }
                    />
                  </label>
                  <label>
                    Dietary preferences (comma separated)
                    <input
                      value={profile.dietary_preferences.join(", ")}
                      onChange={(event) =>
                        setProfile({
                          ...profile,
                          dietary_preferences: event.target.value
                            .split(",")
                            .map((item) => item.trim())
                            .filter(Boolean),
                        })
                      }
                    />
                  </label>
                  <label className="consent-field">
                    <input
                      type="checkbox"
                      checked={profile.consent_personalization}
                      onChange={(event) =>
                        setProfile({
                          ...profile,
                          consent_personalization: event.target.checked,
                        })
                      }
                    />
                    Use my saved preferences for personalized wellness guidance
                  </label>
                  <fieldset className="target-fields">
                    <legend>Optional daily references you set</legend>
                    {(
                      [
                        ["calories", "Energy", "kcal"],
                        ["protein_g", "Protein", "g"],
                        ["fiber_g", "Fiber", "g"],
                        ["sodium_mg", "Sodium", "mg"],
                        ["calcium_mg", "Calcium", "mg"],
                        ["iron_mg", "Iron", "mg"],
                      ] as const
                    ).map(([field, label, unit]) => (
                      <label key={field}>
                        {label} ({unit})
                        <input
                          type="number"
                          min="0.01"
                          step="any"
                          value={profile.daily_targets[field] ?? ""}
                          onChange={(event) =>
                            setDailyTarget(field, event.target.value)
                          }
                        />
                      </label>
                    ))}
                    <p>
                      NutriLens only compares these user-entered references with
                      logged diary averages. It does not choose a clinical
                      target or assess adequacy.
                    </p>
                  </fieldset>
                  <fieldset className="body-context-fields">
                    <legend>Optional adult BMI context</legend>
                    <label className="consent-field">
                      <input
                        type="checkbox"
                        checked={
                          profile.body_context.adult_attestation &&
                          profile.body_context.consent_bmi_context
                        }
                        onChange={(event) =>
                          setProfile({
                            ...profile,
                            body_context: event.target.checked
                              ? {
                                  ...profile.body_context,
                                  adult_attestation: true,
                                  consent_bmi_context: true,
                                }
                              : {
                                  adult_attestation: false,
                                  consent_bmi_context: false,
                                  height_cm: null,
                                  weight_kg: null,
                                },
                          })
                        }
                      />
                      I confirm I am an adult and consent to storing these
                      measurements for BMI context
                    </label>
                    <label>
                      Height (cm)
                      <input
                        type="number"
                        min="100"
                        max="250"
                        step="any"
                        disabled={!profile.body_context.consent_bmi_context}
                        value={profile.body_context.height_cm ?? ""}
                        onChange={(event) =>
                          setProfile({
                            ...profile,
                            body_context: {
                              ...profile.body_context,
                              height_cm: event.target.value
                                ? Number(event.target.value)
                                : null,
                            },
                          })
                        }
                      />
                    </label>
                    <label>
                      Weight (kg)
                      <input
                        type="number"
                        min="20"
                        max="500"
                        step="any"
                        disabled={!profile.body_context.consent_bmi_context}
                        value={profile.body_context.weight_kg ?? ""}
                        onChange={(event) =>
                          setProfile({
                            ...profile,
                            body_context: {
                              ...profile.body_context,
                              weight_kg: event.target.value
                                ? Number(event.target.value)
                                : null,
                            },
                          })
                        }
                      />
                    </label>
                    <p>
                      {bmiContext?.state === "AVAILABLE"
                        ? `Calculated BMI: ${bmiContext.bmi}. `
                        : "No BMI is calculated until consented height and weight are saved. "}
                      {bmiContext?.limitation ??
                        "This value is a weight-for-height context only, not a diagnosis or target."}
                    </p>
                    {bmiContext?.reference_url && (
                      <a
                        href={bmiContext.reference_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        WHO formula reference
                      </a>
                    )}
                  </fieldset>
                  <div>
                    <button disabled={busy} onClick={saveProfile}>
                      Save preferences
                    </button>
                    {profileMessage && <span>{profileMessage}</span>}
                  </div>
                </div>
              </section>
            )}
            <section
              className="weight-controls card"
              aria-labelledby="weight-tracking-title"
            >
              <div className="billing-section-title">
                <div>
                  <h2 id="weight-tracking-title">Optional weight tracking</h2>
                  <p>
                    Keep private, self-reported weight records for descriptive
                    tracking. This is off until you explicitly enable it.
                  </p>
                </div>
                <Scale aria-hidden="true" />
              </div>
              {weightSummary === null ? (
                <div className="weight-loading">
                  <p>{weightMessage || "Loading optional weight settings…"}</p>
                  {weightMessage && (
                    <button
                      disabled={busy}
                      onClick={() => {
                        setWeightMessage("");
                        void refreshWeight().catch(() =>
                          setWeightMessage(
                            "Weight history could not be loaded.",
                          ),
                        );
                      }}
                    >
                      Retry
                    </button>
                  )}
                </div>
              ) : weightSummary.state === "DISABLED" ? (
                <div className="weight-disabled-state">
                  <p>
                    NutriLens does not store a weight history or target while
                    this feature is disabled.
                  </p>
                  <label className="consent-field">
                    <input
                      type="checkbox"
                      checked={weightConsent}
                      onChange={(event) =>
                        setWeightConsent(event.target.checked)
                      }
                    />
                    I choose to store self-reported weight records in my
                    NutriLens account. I understand this is not clinical advice.
                  </label>
                  <button
                    disabled={busy || !weightConsent}
                    onClick={() => void enableWeightTracking()}
                  >
                    Enable optional tracking
                  </button>
                </div>
              ) : (
                <div className="weight-active-state">
                  <div className="weight-summary-grid">
                    <div>
                      <span>Latest</span>
                      <strong>
                        {formatKg(weightSummary.latest_weight_kg)}
                      </strong>
                    </div>
                    <div>
                      <span>Change from first record</span>
                      <strong>
                        {formatKg(weightSummary.change_from_first_kg)}
                      </strong>
                    </div>
                    <div>
                      <span>Optional target difference</span>
                      <strong>
                        {formatKg(weightSummary.difference_from_target_kg)}
                      </strong>
                    </div>
                  </div>
                  <div className="weight-edit-grid">
                    <div className="weight-form-block">
                      <h3>
                        {editingWeightId ? "Edit record" : "Add a record"}
                      </h3>
                      <label>
                        Weight (kg)
                        <input
                          type="number"
                          min="20"
                          max="500"
                          step="0.1"
                          inputMode="decimal"
                          value={weightDraft}
                          onChange={(event) =>
                            setWeightDraft(event.target.value)
                          }
                        />
                      </label>
                      <div>
                        <button
                          disabled={busy || weightDraft === ""}
                          onClick={() => void saveWeightRecord()}
                        >
                          {editingWeightId ? "Save record" : "Add record"}
                        </button>
                        {editingWeightId && (
                          <button
                            disabled={busy}
                            onClick={() => {
                              setEditingWeightId(null);
                              setWeightDraft("");
                            }}
                          >
                            Cancel edit
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="weight-form-block">
                      <h3>Optional target</h3>
                      <label>
                        Target weight (kg)
                        <input
                          type="number"
                          min="20"
                          max="500"
                          step="0.1"
                          inputMode="decimal"
                          placeholder="Leave blank to remove"
                          value={weightTargetDraft}
                          onChange={(event) =>
                            setWeightTargetDraft(event.target.value)
                          }
                        />
                      </label>
                      <button
                        disabled={busy}
                        onClick={() => void saveWeightTarget()}
                      >
                        Save target
                      </button>
                    </div>
                  </div>
                  <div className="weight-history">
                    <h3>Weight history</h3>
                    {weightSummary.entries.length === 0 ? (
                      <p className="empty-billing">No records yet.</p>
                    ) : (
                      weightSummary.entries.map((entry) => (
                        <article key={entry.id}>
                          <div>
                            <strong>{formatKg(entry.weight_kg)}</strong>
                            <span>
                              {new Date(entry.recorded_at).toLocaleString(
                                "en-IN",
                              )}
                            </span>
                          </div>
                          <div>
                            <button
                              disabled={busy}
                              aria-label={`Edit ${formatKg(entry.weight_kg)} record`}
                              onClick={() => {
                                setEditingWeightId(entry.id);
                                setWeightDraft(String(entry.weight_kg));
                                setWeightDeleteId(null);
                              }}
                            >
                              Edit
                            </button>
                            {weightDeleteId === entry.id ? (
                              <>
                                <button
                                  className="danger-action"
                                  disabled={busy}
                                  aria-label={`Confirm delete ${formatKg(entry.weight_kg)} record`}
                                  onClick={() => void deleteWeightRecord()}
                                >
                                  Confirm delete
                                </button>
                                <button
                                  disabled={busy}
                                  onClick={() => setWeightDeleteId(null)}
                                >
                                  Keep
                                </button>
                              </>
                            ) : (
                              <button
                                className="danger-action"
                                disabled={busy}
                                aria-label={`Delete ${formatKg(entry.weight_kg)} record`}
                                onClick={() => setWeightDeleteId(entry.id)}
                              >
                                Delete
                              </button>
                            )}
                          </div>
                        </article>
                      ))
                    )}
                  </div>
                  <div className="weight-disable-block">
                    <h3>Disable and erase NutriLens weight data</h3>
                    <p>
                      This permanently removes your NutriLens target and weight
                      history. It does not change data in Health Connect or
                      another service.
                    </p>
                    <label>
                      Type ERASE to confirm
                      <input
                        autoComplete="off"
                        value={weightEraseText}
                        onChange={(event) =>
                          setWeightEraseText(event.target.value)
                        }
                      />
                    </label>
                    <button
                      className="danger-action"
                      disabled={busy || weightEraseText !== "ERASE"}
                      onClick={() => void disableWeightTracking()}
                    >
                      Disable and erase
                    </button>
                  </div>
                  <p className="weight-limitation">
                    {weightSummary.limitation}
                  </p>
                </div>
              )}
              {weightMessage && weightSummary !== null && (
                <p className="weight-message" aria-live="polite">
                  {weightMessage}
                </p>
              )}
            </section>
            <section className="household-controls card">
              <div className="billing-section-title">
                <div>
                  <h2>Household profiles</h2>
                  <p>
                    Keep up to 10 separate wellness contexts. A member profile
                    is never applied to your recommendations automatically.
                  </p>
                </div>
                <Users />
              </div>
              <div className="household-layout">
                <div className="household-list">
                  {householdProfiles.length === 0 ? (
                    <p className="empty-billing">No household profiles yet.</p>
                  ) : (
                    householdProfiles.map((item) => (
                      <article key={item.id}>
                        <div>
                          <strong>{item.display_name}</strong>
                          <span>
                            {[
                              item.relationship,
                              wellnessGoalLabel(item.profile.goal),
                              item.profile.custom_goal,
                            ]
                              .filter(Boolean)
                              .join(" · ")}
                          </span>
                          <small>
                            Personalization{" "}
                            {item.profile.consent_personalization
                              ? "consented"
                              : "off"}
                          </small>
                        </div>
                        <div>
                          <button
                            disabled={busy}
                            onClick={() =>
                              setHouseholdDraft({
                                id: item.id,
                                display_name: item.display_name,
                                relationship: item.relationship ?? "",
                                profile: item.profile,
                              })
                            }
                          >
                            Edit
                          </button>
                          <button
                            className="danger-action"
                            disabled={busy}
                            onClick={() => {
                              setHouseholdToDelete(item);
                              setConfirmationDialog("delete-household");
                            }}
                          >
                            Delete
                          </button>
                        </div>
                      </article>
                    ))
                  )}
                </div>
                <div className="household-form">
                  <h3>
                    {householdDraft.id ? "Edit profile" : "Add a profile"}
                  </h3>
                  <label>
                    Display name
                    <input
                      maxLength={100}
                      value={householdDraft.display_name}
                      onChange={(event) =>
                        setHouseholdDraft({
                          ...householdDraft,
                          display_name: event.target.value,
                        })
                      }
                    />
                  </label>
                  <label>
                    Relationship (optional)
                    <input
                      maxLength={50}
                      value={householdDraft.relationship}
                      onChange={(event) =>
                        setHouseholdDraft({
                          ...householdDraft,
                          relationship: event.target.value,
                        })
                      }
                    />
                  </label>
                  <label>
                    Wellness goal
                    <select
                      value={householdDraft.profile.goal}
                      onChange={(event) => {
                        const goal = event.target.value as WellnessGoal;
                        setHouseholdDraft({
                          ...householdDraft,
                          profile: {
                            ...householdDraft.profile,
                            goal,
                            custom_goal:
                              goal === "custom"
                                ? (householdDraft.profile.custom_goal ?? "")
                                : null,
                          },
                        });
                      }}
                    >
                      {wellnessGoals.map(({ value, label }) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  {householdDraft.profile.goal === "custom" && (
                    <label>
                      Describe the custom goal
                      <input
                        maxLength={120}
                        required
                        value={householdDraft.profile.custom_goal ?? ""}
                        onChange={(event) =>
                          setHouseholdDraft({
                            ...householdDraft,
                            profile: {
                              ...householdDraft.profile,
                              custom_goal: event.target.value,
                            },
                          })
                        }
                      />
                    </label>
                  )}
                  <label>
                    Allergens (comma separated)
                    <input
                      value={householdDraft.profile.allergens.join(", ")}
                      onChange={(event) =>
                        setHouseholdDraft({
                          ...householdDraft,
                          profile: {
                            ...householdDraft.profile,
                            allergens: event.target.value
                              .split(",")
                              .map((value) => value.trim())
                              .filter(Boolean),
                          },
                        })
                      }
                    />
                  </label>
                  <label className="consent-field">
                    <input
                      type="checkbox"
                      checked={householdDraft.profile.consent_personalization}
                      onChange={(event) =>
                        setHouseholdDraft({
                          ...householdDraft,
                          profile: {
                            ...householdDraft.profile,
                            consent_personalization: event.target.checked,
                          },
                        })
                      }
                    />
                    Store consent for this member’s future selected context
                  </label>
                  <div>
                    <button
                      disabled={
                        busy ||
                        !householdDraft.display_name.trim() ||
                        (householdDraft.profile.goal === "custom" &&
                          !householdDraft.profile.custom_goal?.trim())
                      }
                      onClick={() => void saveHouseholdProfile()}
                    >
                      {householdDraft.id ? "Update profile" : "Add profile"}
                    </button>
                    {householdDraft.id && (
                      <button disabled={busy} onClick={resetHouseholdDraft}>
                        Cancel edit
                      </button>
                    )}
                  </div>
                  {householdMessage && (
                    <p aria-live="polite">{householdMessage}</p>
                  )}
                  <small>
                    General wellness only. No age, life-stage, diagnosis, or
                    clinical suitability is inferred.
                  </small>
                </div>
              </div>
            </section>
            <section className="data-controls card">
              <div>
                <h2>Your data</h2>
                <p>
                  Export your stored profile, diary and pantry as JSON, or
                  permanently delete your account. Raw scan images are not
                  retained.
                </p>
              </div>
              <div>
                <button disabled={busy} onClick={exportData}>
                  Export my data
                </button>
                <button
                  className="danger-action"
                  disabled={busy}
                  onClick={() => {
                    setConfirmationText("");
                    setConfirmationDialog("delete-account");
                  }}
                >
                  Delete account
                </button>
              </div>
            </section>
          </>
        )}
      </main>
      {confirmationDialog && (
        <div className="nutrilens-dialog-backdrop">
          <div
            className="nutrilens-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="billing-confirmation-title"
          >
            <div className="dialog-heading">
              <div>
                <h2 id="billing-confirmation-title">
                  {confirmationDialog === "cancel-subscription"
                    ? "Cancel at cycle end?"
                    : confirmationDialog === "delete-account"
                      ? "Delete your account?"
                      : "Delete household profile?"}
                </h2>
                <p>
                  {confirmationDialog === "cancel-subscription"
                    ? "Your current plan stays active until the end of the paid billing cycle."
                    : confirmationDialog === "delete-account"
                      ? "This permanently removes your NutriLens account and stored application data. Raw scan images are not retained."
                      : `This removes ${householdToDelete?.display_name ?? "this"}'s household profile from your account.`}
                </p>
              </div>
            </div>
            <form
              className="dialog-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (confirmationDialog === "cancel-subscription") {
                  setConfirmationDialog(null);
                  void act("cancel");
                } else if (confirmationDialog === "delete-account") {
                  void deleteAccount();
                } else if (householdToDelete) {
                  setConfirmationDialog(null);
                  void deleteHouseholdProfile(householdToDelete);
                }
              }}
            >
              {confirmationDialog === "delete-account" && (
                <label>
                  Type DELETE to permanently continue
                  <input
                    autoFocus
                    value={confirmationText}
                    onChange={(event) =>
                      setConfirmationText(event.target.value)
                    }
                    disabled={busy}
                  />
                </label>
              )}
              <div className="dialog-actions">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => {
                    setConfirmationDialog(null);
                    setHouseholdToDelete(null);
                    setConfirmationText("");
                  }}
                >
                  Keep it
                </button>
                <button
                  className="danger-action"
                  type="submit"
                  disabled={
                    busy ||
                    (confirmationDialog === "delete-account" &&
                      confirmationText !== "DELETE")
                  }
                >
                  {confirmationDialog === "cancel-subscription"
                    ? "Cancel at cycle end"
                    : confirmationDialog === "delete-account"
                      ? "Delete account"
                      : "Delete profile"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
