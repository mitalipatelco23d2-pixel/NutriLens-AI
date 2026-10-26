"use client";

import { ChangeEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  BarChart3,
  Bell,
  Bot,
  Camera,
  ChevronDown,
  CircleHelp,
  Clock3,
  Columns2,
  Droplets,
  Flame,
  HeartPulse,
  Home,
  Info,
  Leaf,
  Menu,
  Mic,
  PackageOpen,
  Plus,
  Scale,
  ScanLine,
  Search,
  Settings,
  ShieldCheck,
  ShoppingBasket,
  Sparkles,
  Target,
  TrendingUp,
  Upload,
  Volume2,
  Wheat,
  X,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
} from "recharts";
import { scanIdempotencyKey } from "@/lib/scan-idempotency";
import {
  knownTotal,
  nutrientText,
  servingText,
  type NutrientSnapshot,
} from "@/lib/nutrient-evidence";
import { HydrationPanel, HydrationToday } from "@/components/hydration-panel";
import { CustomRecipesPanel } from "@/components/custom-recipes-panel";
import { SessionKeepalive } from "@/components/session-keepalive";

type View =
  | "home"
  | "scan"
  | "result"
  | "history"
  | "favorites"
  | "search"
  | "diary"
  | "compare"
  | "analytics"
  | "pantry"
  | "assistant";

type R3Candidate = { value: string; confidence: number; method: string };
type ScanJob = {
  job_id: string;
  status: "QUEUED" | "PREPROCESSING" | "COMPLETE" | "FAILED" | "TIMED_OUT";
  result: R3ScanResult | null;
  error_message: string | null;
};
type R3ScanResult = {
  scan_id: string;
  trace_id: string;
  status: string;
  input_kind: string;
  image_quality: Record<
    string,
    {
      blur_score: number;
      blur_status: string;
      brightness_score: number;
      brightness_status: string;
      contrast_score: number;
      contrast_status: string;
      resolution_ok: boolean;
      quality_status: string;
      retry_recommended: boolean;
      warnings: string[];
    }
  >;
  regions: Array<{
    region_type: string;
    method: string;
    confidence: number | null;
  }>;
  barcode_results: Array<{
    symbology: string;
    value: string;
    checksum_valid: boolean | null;
  }>;
  qr_results: Array<{ value: string; safety_status: string }>;
  ocr_results: Record<
    string,
    {
      selected_engine: string | null;
      text: string;
      confidence: number | null;
      confidence_level: string;
      fallback_reason: string | null;
      attempts: Array<{ engine: string; status: string }>;
    }
  >;
  nutrition: {
    raw_table_text: string;
    basis: string;
    confidence: number | null;
    table_columns?: string[];
    serving_size_value?: number | string | null;
    serving_size_unit?: string | null;
    table_rows: Array<{ label: string; values: string[]; units: string[] }>;
  };
  ingredients: {
    raw_text: string;
    allergen_text: string;
    confidence: number | null;
    allergen_confidence: number | null;
  };
  insights?: {
    highlights: string[];
    positive_signals: string[];
    things_to_watch: string[];
    allergen_summary: string | null;
    serving_context: string | null;
    structured_highlights: Array<{
      title: string;
      description: string;
      category: "positive" | "watch" | "neutral" | "allergen" | "serving";
      icon?: string | null;
    }>;
    ask_nutri_suggestions: string[];
  } | null;
  brand_candidates: R3Candidate[];
  product_name_candidates: R3Candidate[];
  date_candidates: Array<{
    date_type: string;
    raw_text: string;
    parsed_date: string | null;
    ambiguous: boolean;
  }>;
  category_candidates: R3Candidate[];
  meal_items: Array<{
    item_id: string;
    food_candidates: R3Candidate[];
    confidence: number | null;
  }>;
  portion_estimates: Array<{
    method: string;
    estimated_amount: number | null;
    unit: string | null;
    assumptions: string[];
  }>;
  confidence_summary: {
    level: string;
    numeric_score: number | null;
    explanation: string[];
  };
  warnings: string[];
  manual_review_fields: Array<{ field: string; reason: string }>;
  corrections: Array<{
    field: string;
    corrected_value: unknown;
    corrected_at: string;
  }>;
  timings: {
    total_ms: number;
    validation_ms: number;
    preprocessing_ms: number;
    detection_ms: number;
    ocr_ms: number;
  };
  images_retained: false;
};
type R4Signal = { ingredient_text: string; matched_term: string };
type R4Result = {
  parse: {
    ingredients: { original_text: string; depth: number }[];
    warnings: string[];
  };
  additives: {
    additive: {
      matched: boolean;
      canonical_name: string | null;
      external_code: string | null;
      functional_category: string | null;
    };
  }[];
  allergens: {
    allergen: {
      matched: boolean;
      canonical_name: string | null;
      match_method: string;
      evidence_source: string | null;
      evidence_text: string | null;
    };
  }[];
  hidden_sugars: { signals: R4Signal[] };
  sodium_sources: { signals: R4Signal[] };
  oils_and_fats: { signals: R4Signal[] };
  sweeteners: { signals: R4Signal[] };
  preservatives: { signals: R4Signal[] };
  nova: {
    group_number: number | null;
    classification_method: string;
    warnings: string[];
  };
  complexity: {
    level: string;
    ingredient_count: number;
    unresolved_count: number;
  };
  confidence: {
    state: string;
    score: number;
    method: string;
    source_datasets: string[];
  };
};
type CounterfactualExplanation = {
  scan_id: string;
  state: "AVAILABLE" | "NO_OBSERVED_SIGNALS";
  factors: Array<{
    factor_id: string;
    label: string;
    observed_evidence: string[];
    hypothesis: string;
    result_change: string;
    method: string;
  }>;
  limitation: string;
};

const ACTIVE_SCAN_JOB_STORAGE_KEY = "nutrilens-active-scan-job";

const nav = [
  { id: "home" as View, label: "Overview", icon: Home },
  { id: "scan" as View, label: "Scan food", icon: ScanLine },
  { id: "diary" as View, label: "Food diary", icon: HeartPulse },
  { id: "analytics" as View, label: "My nutrition", icon: BarChart3 },
  { id: "pantry" as View, label: "Smart pantry", icon: ShoppingBasket },
  { id: "assistant" as View, label: "Ask Nutri", icon: Bot },
];

function Logo() {
  return (
    <div className="logo">
      <span className="logo-mark">
        <Leaf size={19} />
      </span>
      <span>
        nutrilens<span className="logo-x">x</span>
      </span>
    </div>
  );
}

type NotificationItem = {
  id: string;
  kind: string;
  title: string;
  body: string;
  action_href: string | null;
  read_at: string | null;
  created_at: string;
};

type AuthenticatedUser = {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  plan: string;
  subscription_status: string;
};

const initials = (name?: string) =>
  (name ?? "NutriLens user")
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");

function Header({
  menuOpen,
  onMenu,
  user,
  onSearch,
}: {
  menuOpen: boolean;
  onMenu: () => void;
  user: AuthenticatedUser | null;
  onSearch: (query: string) => void;
}) {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  useEffect(() => {
    let active = true;
    void fetch("/api/backend/notifications?limit=20", { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : []))
      .then((payload: unknown) => {
        if (active) setNotifications(payload as NotificationItem[]);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
  const markRead = async (notification: NotificationItem) => {
    if (notification.read_at) return;
    const response = await fetch(
      `/api/backend/notifications/${encodeURIComponent(notification.id)}/read`,
      { method: "PATCH" },
    );
    if (!response.ok) return;
    const updated = (await response.json()) as NotificationItem;
    setNotifications((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
  };
  const markAllRead = async () => {
    const response = await fetch("/api/backend/notifications/read-all", {
      method: "POST",
    });
    if (!response.ok) return;
    const readAt = new Date().toISOString();
    setNotifications((current) =>
      current.map((item) => ({ ...item, read_at: item.read_at ?? readAt })),
    );
  };
  const unread = notifications.filter((item) => item.read_at === null).length;
  return (
    <header className="topbar">
      <button
        className="mobile-menu icon-btn"
        onClick={onMenu}
        aria-controls="dashboard-sidebar"
        aria-expanded={menuOpen}
        aria-label="Open menu"
      >
        <Menu />
      </button>
      <form
        className="searchbox"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          if (searchQuery.trim().length >= 2) onSearch(searchQuery.trim());
        }}
      >
        <Search size={17} aria-hidden="true" />
        <input
          aria-label="Search foods, ingredients or questions"
          placeholder="Search foods, ingredients or questions"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
        <kbd>⌘ K</kbd>
      </form>
      <div className="top-actions">
        <button className="icon-btn" aria-label="Help">
          <CircleHelp size={19} />
        </button>
        <div className="notification-wrap">
          <button
            className="icon-btn notification"
            aria-controls="notification-panel"
            aria-expanded={notificationsOpen}
            aria-haspopup="dialog"
            aria-label={`Notifications${unread ? `, ${unread} unread` : ""}`}
            onClick={() => setNotificationsOpen((current) => !current)}
          >
            <Bell size={19} />
            {unread > 0 && <i aria-hidden="true" />}
          </button>
          {notificationsOpen && (
            <div
              aria-label="Notifications"
              className="notification-panel"
              id="notification-panel"
              role="dialog"
            >
              <div>
                <strong>Notifications</strong>
                <button disabled={!unread} onClick={() => void markAllRead()}>
                  Mark all read
                </button>
              </div>
              {notifications.length === 0 && <p>No notifications yet.</p>}
              {notifications.map((item) => (
                <a
                  className={item.read_at ? "read" : ""}
                  href={item.action_href ?? "#"}
                  key={item.id}
                  onClick={() => void markRead(item)}
                >
                  <span>{item.title}</span>
                  <p>{item.body}</p>
                  <small>{new Date(item.created_at).toLocaleString()}</small>
                </a>
              ))}
            </div>
          )}
        </div>
        <div className="avatar" aria-label={user?.name ?? "Account"}>
          {initials(user?.name)}
        </div>
      </div>
    </header>
  );
}

function Sidebar({
  view,
  setView,
  open,
  close,
  user,
}: {
  view: View;
  setView: (v: View) => void;
  open: boolean;
  close: () => void;
  user: AuthenticatedUser | null;
}) {
  const [compact, setCompact] = useState(false);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const closeMenu = () => {
    close();
    window.requestAnimationFrame(() =>
      document.querySelector<HTMLButtonElement>(".mobile-menu")?.focus(),
    );
  };
  useEffect(() => {
    const media = window.matchMedia("(max-width: 800px)");
    const update = () => setCompact(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!compact || !open) return;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeMenu();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  });
  return (
    <>
      {open && (
        <button
          className="scrim"
          onClick={closeMenu}
          aria-label="Close navigation menu"
        />
      )}
      <aside
        aria-hidden={compact && !open ? true : undefined}
        aria-label="Application navigation"
        className={`sidebar ${open ? "open" : ""}`}
        id="dashboard-sidebar"
        inert={compact && !open ? true : undefined}
      >
        <div className="side-head">
          <Logo />
          <button
            className="mobile-close icon-btn"
            onClick={closeMenu}
            aria-label="Close menu"
            ref={closeButtonRef}
          >
            <X size={19} />
          </button>
        </div>
        <nav aria-label="Dashboard navigation">
          <p className="nav-caption">Workspace</p>
          {nav.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              className={
                view === id || (view === "result" && id === "scan")
                  ? "active"
                  : ""
              }
              aria-current={
                view === id || (view === "result" && id === "scan")
                  ? "page"
                  : undefined
              }
              onClick={() => {
                setView(id);
                close();
              }}
            >
              <Icon size={18} />
              <span>{label}</span>
              {id === "assistant" && <em>AI</em>}
            </button>
          ))}
          <p className="nav-caption second">Library</p>
          <button
            className={view === "history" ? "active" : ""}
            aria-current={view === "history" ? "page" : undefined}
            onClick={() => {
              setView("history");
              close();
            }}
          >
            <Clock3 size={18} />
            <span>Scan history</span>
          </button>
          <button
            className={view === "favorites" ? "active" : ""}
            aria-current={view === "favorites" ? "page" : undefined}
            onClick={() => {
              setView("favorites");
              close();
            }}
          >
            <HeartPulse size={18} />
            <span>Saved foods</span>
          </button>
          <button
            className={view === "compare" ? "active" : ""}
            aria-current={view === "compare" ? "page" : undefined}
            onClick={() => {
              setView("compare");
              close();
            }}
          >
            <Columns2 size={18} />
            <span>Compare</span>
          </button>
        </nav>
        <a className="profile-mini" href="/account">
          <div className="avatar">{initials(user?.name)}</div>
          <div>
            <strong>{user?.name ?? "Account"}</strong>
            <span>{user ? `${user.plan} plan` : "Sign in required"}</span>
          </div>
          <ChevronDown size={16} />
        </a>
        <div className="privacy">
          <ShieldCheck size={18} />
          <div>
            <strong>Private by design</strong>
            <span>Your health data stays secure.</span>
          </div>
        </div>
      </aside>
    </>
  );
}

type DashboardAnalytics = {
  diary_entries: number;
  period_days: number;
  daily_averages: NutrientSnapshot;
  insights: string[];
  goal_tracking_state: string;
  goal_progress: Array<{
    nutrient: string;
    label: string;
    unit: string;
    daily_average: number | null;
    user_target: number;
    percent_of_target: number | null;
  }>;
  goal_tracking_limitation: string;
};

type DashboardScan = {
  scan_id: string;
  created_at: string;
  status: string;
  product_name: string | null;
  brand: string | null;
  confidence: number | null;
};

type DashboardWeight = {
  state: "DISABLED" | "ACTIVE";
  target_weight_kg: number | null;
  latest_weight_kg: number | null;
  change_from_first_kg: number | null;
  difference_from_target_kg: number | null;
  limitation: string;
};

type WeightHistory = DashboardWeight & {
  entries: Array<{
    id: string;
    weight_kg: number;
    recorded_at: string;
    source: "USER_ENTERED";
  }>;
};

function dashboardWeight(payload: unknown): DashboardWeight | null {
  if (!payload || typeof payload !== "object") return null;
  const value = payload as Record<string, unknown>;
  if (value.state !== "DISABLED" && value.state !== "ACTIVE") return null;
  const nullableNumber = (candidate: unknown) =>
    candidate === null ||
    (typeof candidate === "number" && Number.isFinite(candidate));
  if (
    !nullableNumber(value.target_weight_kg) ||
    !nullableNumber(value.latest_weight_kg) ||
    !nullableNumber(value.change_from_first_kg) ||
    !nullableNumber(value.difference_from_target_kg) ||
    typeof value.limitation !== "string"
  )
    return null;
  return value as DashboardWeight;
}

function weightHistory(payload: unknown): WeightHistory | null {
  const summary = dashboardWeight(payload);
  if (!summary) return null;
  const entries = (payload as Record<string, unknown>).entries;
  if (
    !Array.isArray(entries) ||
    entries.some(
      (entry) =>
        !entry ||
        typeof entry !== "object" ||
        typeof (entry as Record<string, unknown>).id !== "string" ||
        typeof (entry as Record<string, unknown>).weight_kg !== "number" ||
        !Number.isFinite((entry as Record<string, unknown>).weight_kg) ||
        typeof (entry as Record<string, unknown>).recorded_at !== "string" ||
        !Number.isFinite(
          Date.parse((entry as Record<string, unknown>).recorded_at as string),
        ) ||
        (entry as Record<string, unknown>).source !== "USER_ENTERED",
    )
  )
    return null;
  return { ...summary, entries } as WeightHistory;
}

function weightText(value: number | null) {
  return value === null
    ? "Not recorded"
    : `${value.toLocaleString("en-IN")} kg`;
}

function LiveHomeView({
  setView,
  user,
}: {
  setView: (v: View) => void;
  user: AuthenticatedUser | null;
}) {
  const [summary, setSummary] = useState<DashboardAnalytics | null>(null);
  const [history, setHistory] = useState<DashboardScan[]>([]);
  const [weight, setWeight] = useState<DashboardWeight | null>(null);
  const [weightLoaded, setWeightLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  useEffect(() => {
    let active = true;
    Promise.all([
      fetch("/api/backend/analytics/summary?days=1", { cache: "no-store" }),
      fetch("/api/backend/scan/history?limit=3", { cache: "no-store" }),
      fetch("/api/backend/weight", { cache: "no-store" })
        .then(async (response) =>
          response.ok ? dashboardWeight(await response.json()) : null,
        )
        .catch(() => null),
    ])
      .then(async ([summaryResponse, historyResponse, weightResponse]) => {
        if (!summaryResponse.ok || !historyResponse.ok) {
          throw new Error("Your private overview could not be loaded.");
        }
        return {
          summary: (await summaryResponse.json()) as DashboardAnalytics,
          history: (await historyResponse.json()) as DashboardScan[],
          weight: weightResponse,
        };
      })
      .then((payload) => {
        if (!active) return;
        setSummary(payload.summary);
        setHistory(payload.history);
        setWeight(payload.weight);
        setWeightLoaded(true);
      })
      .catch((reason: unknown) => {
        if (active) {
          setWeightLoaded(true);
          setLoadError(
            reason instanceof Error
              ? reason.message
              : "Your private overview could not be loaded.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="page fade-in">
      <section className="welcome">
        <div>
          <p className="eyebrow">
            {new Intl.DateTimeFormat(undefined, { dateStyle: "full" }).format(
              new Date(),
            )}
          </p>
          <h1>{user ? `Welcome, ${user.name}.` : "Your private overview."}</h1>
          <p>Only authenticated diary and scan evidence appears here.</p>
        </div>
        <button className="primary" onClick={() => setView("scan")}>
          <ScanLine size={18} /> Scan a product
        </button>
      </section>

      {loadError && (
        <p className="assistant-error" role="alert">
          {loadError}
        </p>
      )}

      <section className="hero-grid">
        <article className="daily-card">
          <span className="soft-label">
            <Sparkles size={14} /> Today&apos;s logged evidence
          </span>
          <h2>
            {summary?.diary_entries ?? 0} diary{" "}
            {(summary?.diary_entries ?? 0) === 1 ? "entry" : "entries"}
          </h2>
          <p className="muted">
            {summary?.insights[0] ??
              "Add a diary entry to calculate today’s observed averages."}
          </p>
          <button className="full-text" onClick={() => setView("diary")}>
            Open diary <ArrowRight size={15} />
          </button>
        </article>

        <article className="macro-card card">
          <div className="card-title">
            <div>
              <span className="icon-well peach">
                <Flame size={18} />
              </span>
              <div>
                <h3>Today&apos;s diary averages</h3>
                <p>
                  {nutrientText(summary?.daily_averages.calories, "kcal", 0)}{" "}
                  from logged entries
                </p>
              </div>
            </div>
            <button
              className="text-button"
              onClick={() => setView("analytics")}
            >
              Details <ArrowRight size={15} />
            </button>
          </div>
          <div className="macro-grid">
            <div>
              <span className="dot protein" />
              <strong>
                {nutrientText(summary?.daily_averages.protein_g, "g")}
              </strong>
              <small>Protein</small>
            </div>
            <div>
              <span className="dot carbs" />
              <strong>
                {nutrientText(summary?.daily_averages.carbs_g, "g")}
              </strong>
              <small>Carbohydrate</small>
            </div>
            <div>
              <span className="dot fat" />
              <strong>
                {nutrientText(summary?.daily_averages.fat_g, "g")}
              </strong>
              <small>Fat</small>
            </div>
          </div>
          <div className="insight-line">
            <Info size={16} />
            <span>
              Missing nutrient evidence stays unknown, not zero, and is never
              estimated.
            </span>
          </div>
        </article>
      </section>

      <HydrationToday key={user?.id} onOpen={() => setView("diary")} />
      <section className="card weight-today-card" aria-label="Weight snapshot">
        <div className="weight-today-heading">
          <div>
            <p className="eyebrow">
              <Scale size={15} aria-hidden="true" /> OPTIONAL TRACKING
            </p>
            <h2>Weight snapshot</h2>
          </div>
          <a className="full-text" href="/account#weight-tracking-title">
            Manage weight <ArrowRight size={15} />
          </a>
        </div>
        {!weightLoaded ? (
          <p role="status">Loading your optional weight summary…</p>
        ) : weight?.state === "DISABLED" ? (
          <p>
            Weight tracking is off. NutriLens stores no weight history until you
            explicitly enable it.
          </p>
        ) : weight?.state === "ACTIVE" ? (
          <>
            <div className="weight-today-values">
              <div>
                <span>Latest</span>
                <strong>{weightText(weight.latest_weight_kg)}</strong>
              </div>
              <div>
                <span>Change from first record</span>
                <strong>{weightText(weight.change_from_first_kg)}</strong>
              </div>
              <div>
                <span>Optional target difference</span>
                <strong>{weightText(weight.difference_from_target_kg)}</strong>
              </div>
            </div>
            <p>{weight.limitation}</p>
          </>
        ) : (
          <p role="status">
            Weight summary unavailable. Manage your records from Account.
          </p>
        )}
      </section>
      <section className="content-grid">
        <article className="card quick-scan">
          <div className="scan-visual" aria-hidden="true">
            <ScanLine size={76} />
          </div>
          <div>
            <span className="soft-label">
              <Zap size={14} /> Label evidence pipeline
            </span>
            <h2>Scan a package or nutrition label.</h2>
            <p>
              NutriLens preserves unknown states and shows the evidence behind
              ingredient and nutrition findings.
            </p>
            <button className="dark-button" onClick={() => setView("scan")}>
              <Camera size={18} /> Start scanning
            </button>
          </div>
        </article>

        <article className="card focus-card">
          <div className="card-title">
            <div>
              <span className="icon-well green">
                <Target size={18} />
              </span>
              <div>
                <h3>Your references</h3>
                <p>User-entered, consent-gated progress</p>
              </div>
            </div>
          </div>
          {summary?.goal_tracking_state === "AVAILABLE" ? (
            summary.goal_progress.slice(0, 2).map((item) => (
              <div className="focus-item" key={item.nutrient}>
                <div className="focus-icon purple">
                  <Target size={20} />
                </div>
                <div>
                  <strong>{item.label}</strong>
                  <p>
                    {nutrientText(item.daily_average)} of {item.user_target}{" "}
                    {item.unit}
                  </p>
                  {item.percent_of_target != null && (
                    <progress
                      aria-label={`${item.label} progress`}
                      max={100}
                      value={Math.min(item.percent_of_target, 100)}
                    />
                  )}
                </div>
                <b>
                  {item.percent_of_target == null
                    ? "Progress unknown"
                    : `${item.percent_of_target.toFixed(0)}%`}
                </b>
              </div>
            ))
          ) : (
            <p className="muted">
              {summary?.goal_tracking_state === "DISABLED_NO_CONSENT"
                ? "Enable personalization consent to use your saved references."
                : "No daily references are configured."}
            </p>
          )}
          <p className="muted">
            {summary?.goal_tracking_limitation ??
              "NutriLens does not infer clinical targets or adequacy."}
          </p>
          <a className="full-text" href="/account">
            Edit references <ArrowRight size={15} />
          </a>
        </article>
      </section>

      <section className="section-block">
        <div className="section-heading">
          <div>
            <h2>Recent scans</h2>
            <p>Your latest owner-scoped scan records.</p>
          </div>
          <button className="text-button" onClick={() => setView("history")}>
            View history <ArrowRight size={15} />
          </button>
        </div>
        {history.length === 0 ? (
          <p className="empty-state">No saved scans yet.</p>
        ) : (
          <div className="scan-cards">
            {history.map((item) => (
              <button
                className="product-card"
                key={item.scan_id}
                onClick={() => setView("history")}
              >
                <div className="product-info">
                  <div>
                    <small>{item.brand ?? "Brand not resolved"}</small>
                    <h3>{item.product_name ?? "Unidentified food scan"}</h3>
                  </div>
                </div>
                <div className="product-foot">
                  <span>
                    {item.confidence === null
                      ? "Confidence unavailable"
                      : `${Math.round(item.confidence * 100)}% confidence`}
                    {" · "}
                    {new Date(item.created_at).toLocaleDateString()}
                  </span>
                  <ArrowRight size={17} />
                </div>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ScanView({
  onAnalyzed,
}: {
  onAnalyzed: (result: R3ScanResult) => void;
}) {
  const [preview, setPreview] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [scanKind, setScanKind] = useState<
    "product" | "meal" | "ocr" | "barcode"
  >("product");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<ScanJob["status"] | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const apiBase =
    process.env.NODE_ENV === "production"
      ? "/api/backend/scan"
      : `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/scan`;

  useEffect(() => {
    const restore = window.setTimeout(() => {
      setActiveJobId(
        window.sessionStorage.getItem(ACTIVE_SCAN_JOB_STORAGE_KEY),
      );
    }, 0);
    return () => window.clearTimeout(restore);
  }, []);

  useEffect(() => {
    if (!activeJobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const response = await fetch(`${apiBase}/jobs/${activeJobId}`, {
          cache: "no-store",
        });
        const payload = (await response.json()) as
          ScanJob | { detail?: string };
        if (!response.ok) {
          throw new Error(
            "detail" in payload && typeof payload.detail === "string"
              ? payload.detail
              : "Scan status is temporarily unavailable.",
          );
        }
        const job = payload as ScanJob;
        if (cancelled) return;
        setJobStatus(job.status);
        if (job.status === "COMPLETE" && job.result) {
          window.sessionStorage.removeItem(ACTIVE_SCAN_JOB_STORAGE_KEY);
          setActiveJobId(null);
          onAnalyzed(job.result);
          return;
        }
        if (job.status === "FAILED" || job.status === "TIMED_OUT") {
          window.sessionStorage.removeItem(ACTIVE_SCAN_JOB_STORAGE_KEY);
          setActiveJobId(null);
          setError(job.error_message ?? "The scan could not be completed.");
          return;
        }
        timer = setTimeout(poll, job.status === "QUEUED" ? 2000 : 3500);
      } catch (reason) {
        if (!cancelled) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Scan status is temporarily unavailable.",
          );
          timer = setTimeout(poll, 5000);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [activeJobId, apiBase, onAnalyzed]);
  const choose = (e: ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) {
      if (preview) URL.revokeObjectURL(preview);
      setFile(selected);
      setPreview(URL.createObjectURL(selected));
      setError(null);
    }
  };
  const analyze = async () => {
    if (!file) return;
    setLoading(true);
    setError(null);
    const form = new FormData();
    form.append(scanKind === "product" ? "files" : "file", file);
    if (scanKind === "product") form.append("view_types", "GENERAL");
    if (scanKind === "product" || scanKind === "ocr")
      form.append("languages", "en");
    try {
      const idempotencyKey = await scanIdempotencyKey(
        scanKind,
        await file.arrayBuffer(),
      );
      const response = await fetch(`${apiBase}/jobs/${scanKind}`, {
        method: "POST",
        body: form,
        headers: { "Idempotency-Key": idempotencyKey },
      });
      const payload = (await response.json()) as {
        detail?: string | { message?: string };
        error?: string;
      };
      if (!response.ok) {
        const detail = payload.detail;
        throw new Error(
          typeof detail === "string"
            ? detail
            : (detail?.message ?? payload.error ?? "The scan failed."),
        );
      }
      const job = payload as ScanJob;
      window.sessionStorage.setItem(ACTIVE_SCAN_JOB_STORAGE_KEY, job.job_id);
      setJobStatus(job.status);
      setActiveJobId(job.job_id);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The local scanner could not be reached.",
      );
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="page narrow fade-in">
      <div className="backline">
        <button className="icon-btn">
          <ArrowLeft size={20} />
        </button>
        <span>Food scanner</span>
      </div>
      <div className="scan-title">
        <span className="soft-label">
          <Sparkles size={14} /> AI-powered label analysis
        </span>
        <h1>See food clearly.</h1>
        <p>
          Upload a front-of-pack or nutrition-label image. NutriLens extracts
          the details and explains what they mean for you.
        </p>
      </div>
      <div className="scanner-layout">
        <article className="upload-card">
          <label className="scan-kind">
            Scan mode
            <select
              value={scanKind}
              onChange={(event) =>
                setScanKind(event.target.value as typeof scanKind)
              }
              disabled={loading}
            >
              <option value="product">Packaged product</option>
              <option value="meal">Prepared meal</option>
              <option value="ocr">Label OCR</option>
              <option value="barcode">Barcode / QR</option>
            </select>
          </label>
          <div
            className={`drop-zone ${preview ? "has-image" : ""}`}
            onClick={() => input.current?.click()}
          >
            {preview ? (
              <img src={preview} alt="Selected food label" />
            ) : (
              <>
                <div className="camera-orbit">
                  <ScanLine size={38} />
                  <span />
                </div>
                <h3>Drop your food label here</h3>
                <p>or choose an image from your device</p>
                <button className="outline-button">
                  <Upload size={17} /> Choose image
                </button>
                <small>JPG, PNG or WEBP · Max 10 MB</small>
              </>
            )}
            <input
              ref={input}
              type="file"
              accept="image/*"
              onChange={choose}
              hidden
            />
          </div>
          {error && (
            <div className="scan-error" role="alert">
              <Info size={17} />
              <span>{error}</span>
            </div>
          )}
          {activeJobId && !preview && (
            <div className="scan-job-progress" role="status" aria-live="polite">
              <span className="spinner" aria-hidden="true" />
              <div>
                <strong>{scanJobLabel(jobStatus)}</strong>
                <p>
                  This scan kept running securely. You can leave this page or
                  refresh again without uploading the image twice.
                </p>
              </div>
            </div>
          )}
          {preview && (
            <div className="upload-actions">
              <button
                className="outline-button"
                disabled={loading || activeJobId !== null}
                onClick={() => input.current?.click()}
              >
                Change image
              </button>
              <button
                className="primary"
                disabled={loading || activeJobId !== null}
                onClick={analyze}
              >
                {loading ? (
                  <>
                    <span className="spinner" /> Preparing your scan…
                  </>
                ) : activeJobId ? (
                  <>
                    <span className="spinner" /> {scanJobLabel(jobStatus)}
                  </>
                ) : (
                  <>
                    <Sparkles size={17} /> Analyse food
                  </>
                )}
              </button>
            </div>
          )}
        </article>
        <aside className="scan-tips card">
          <h3>For the clearest result</h3>
          <div>
            <span>01</span>
            <p>
              <strong>Keep it readable</strong>Use good lighting and avoid
              glare.
            </p>
          </div>
          <div>
            <span>02</span>
            <p>
              <strong>Fill the frame</strong>Make the label large and centred.
            </p>
          </div>
          <div>
            <span>03</span>
            <p>
              <strong>Capture both sides</strong>Use product mode again for
              another label view.
            </p>
          </div>
          <hr />
          <div className="demo-box">
            <Info size={18} />
            <p>
              <strong>Authenticated evidence only</strong>The overview and
              history use your owner-scoped API records, never placeholder
              nutrition results.
            </p>
          </div>
        </aside>
      </div>
      <div className="trust-row">
        <span>
          <ShieldCheck size={17} /> Images are processed securely
        </span>
        <span>
          <Zap size={17} /> Bounded processing and explicit unknown states
        </span>
        <span>
          <Info size={17} /> Wellness guidance, not diagnosis
        </span>
      </div>
    </div>
  );
}

function scanJobLabel(status: ScanJob["status"] | null): string {
  if (status === null) return "Resuming your scan";
  if (status === "QUEUED") return "Your scan is queued";
  if (status === "PREPROCESSING") return "Preparing image";
  return "Scanning your food";
}

function ConfidenceValue({ value }: { value: number | null }) {
  return (
    <span>
      {value === null ? "Unavailable" : `${Math.round(value * 100)}%`}
    </span>
  );
}

function R4Group({
  title,
  items,
  safety = false,
  provenance,
}: {
  title: string;
  items: string[];
  safety?: boolean;
  provenance?: string;
}) {
  const uniqueItems = [...new Set(items)];
  return (
    <div className={safety ? "r4-group safety" : "r4-group"}>
      <strong>{title}</strong>
      <p>
        {uniqueItems.length
          ? uniqueItems.join(" · ")
          : "None detected from available evidence"}
      </p>
      {provenance && <small>{provenance}</small>}
    </div>
  );
}

function R3ResultView({
  initial,
  goBack,
  onAskNutri,
}: {
  initial: R3ScanResult;
  goBack: () => void;
  onAskNutri: (question?: string) => void;
}) {
  const [result, setResult] = useState(initial);
  const [field, setField] = useState("product_name");
  const [correction, setCorrection] = useState("");
  const [saving, setSaving] = useState(false);
  const [favorite, setFavorite] = useState(false);
  const [favoriteMessage, setFavoriteMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [intelligence, setIntelligence] = useState<R4Result | null>(null);
  const [counterfactuals, setCounterfactuals] =
    useState<CounterfactualExplanation | null>(null);
  const [intelligenceError, setIntelligenceError] = useState<string | null>(
    null,
  );
  const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const apiPrefix =
    process.env.NODE_ENV === "production"
      ? "/api/backend"
      : `${apiBase}/api/v1`;
  const quality = Object.values(result.image_quality)[0];
  const ocr = Object.values(result.ocr_results)[0];
  const productName =
    result.product_name_candidates[0]?.value ??
    result.category_candidates[0]?.value ??
    "Product needs review";
  const brandName = result.brand_candidates[0]?.value;
  // Preserve package qualifiers; canonical names cannot express "may contain"
  // or "free from". Legacy bare labels must not acquire an invented "Contains".
  const allergenEvidence = result.ingredients.allergen_text.trim();
  const nutritionBasis = result.nutrition.basis
    .replaceAll("_", " ")
    .toLowerCase();
  useEffect(() => {
    let active = true;
    Promise.all([
      fetch(`${apiPrefix}/ingredient-intelligence/scan/${result.scan_id}`, {
        method: "POST",
      }),
      fetch(
        `${apiPrefix}/recommendations/scans/${result.scan_id}/counterfactuals`,
        { cache: "no-store" },
      ),
    ])
      .then(async ([intelligenceResponse, counterfactualResponse]) => {
        if (!intelligenceResponse.ok)
          throw new Error("Ingredient intelligence is unavailable.");
        const intelligencePayload =
          (await intelligenceResponse.json()) as R4Result;
        const counterfactualPayload = counterfactualResponse.ok
          ? ((await counterfactualResponse.json()) as CounterfactualExplanation)
          : null;
        return { intelligencePayload, counterfactualPayload };
      })
      .then(({ intelligencePayload, counterfactualPayload }) => {
        if (active) {
          setIntelligence(intelligencePayload);
          setCounterfactuals(counterfactualPayload);
          setIntelligenceError(null);
        }
      })
      .catch((reason: unknown) => {
        if (active)
          setIntelligenceError(
            reason instanceof Error
              ? reason.message
              : "Ingredient intelligence failed.",
          );
      });
    return () => {
      active = false;
    };
  }, [apiPrefix, result.scan_id, result.ingredients.raw_text]);
  useEffect(() => {
    let active = true;
    void fetch(`${apiPrefix}/favorites?limit=100`, { cache: "no-store" })
      .then((response) => (response.ok ? response.json() : []))
      .then((payload: unknown) => {
        if (active) {
          setFavorite(
            (payload as Array<{ scan_id: string }>).some(
              (item) => item.scan_id === result.scan_id,
            ),
          );
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [apiPrefix, result.scan_id]);
  const correct = async () => {
    if (!correction.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(
        `${apiPrefix}/scan/${result.scan_id}/corrections`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            corrections: [{ field, corrected_value: correction.trim() }],
          }),
        },
      );
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(
          typeof payload.detail === "string"
            ? payload.detail
            : "Correction failed.",
        );
      }
      setResult(payload as R3ScanResult);
      setCorrection("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Correction failed.");
    } finally {
      setSaving(false);
    }
  };
  const remove = async () => {
    setSaving(true);
    try {
      const response = await fetch(`${apiPrefix}/scan/${result.scan_id}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error("Delete failed.");
      goBack();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Delete failed.");
      setSaving(false);
    }
  };
  const toggleFavorite = async () => {
    setSaving(true);
    setFavoriteMessage("");
    const response = await fetch(`${apiPrefix}/favorites/${result.scan_id}`, {
      method: favorite ? "DELETE" : "PUT",
    });
    if (response.ok) {
      setFavorite((current) => !current);
      setFavoriteMessage(
        favorite ? "Removed from saved foods." : "Saved to your account.",
      );
    } else {
      setFavoriteMessage("Saved-food status could not be changed.");
    }
    setSaving(false);
  };
  return (
    <div className="page fade-in r3-result">
      <div className="result-top">
        <button className="back-button" onClick={goBack}>
          <ArrowLeft size={17} /> Scan another image
        </button>
        <div>
          <button className="outline-button" onClick={() => onAskNutri()}>
            <Bot size={16} /> Ask Nutri about this scan
          </button>
          <button
            className="outline-button"
            disabled={saving}
            onClick={() => void toggleFavorite()}
          >
            <HeartPulse size={16} />
            {favorite ? "Remove saved food" : "Save food"}
          </button>
          <button className="outline-button" disabled={saving} onClick={remove}>
            <X size={16} /> Delete scan
          </button>
        </div>
      </div>
      {favoriteMessage && <p role="status">{favoriteMessage}</p>}
      <section className="r3-summary card">
        <div>
          <span className="soft-label">
            <ScanLine size={14} /> Your scan result
          </span>
          {brandName && <p className="result-brand">{brandName}</p>}
          <h1>{productName}</h1>
          <p>
            {result.nutrition.table_rows.length
              ? `${result.nutrition.table_rows.length} nutrition values read · ${nutritionBasis}`
              : "Nutrition values need review"}
          </p>
        </div>
        <div
          className={`confidence-badge confidence-${result.confidence_summary.level.toLowerCase()}`}
        >
          <strong>{result.confidence_summary.level}</strong>
          <ConfidenceValue value={result.confidence_summary.numeric_score} />
          <small>technical confidence</small>
        </div>
      </section>
      <article className="card result-takeaway">
        <h2>Key takeaways</h2>
        {result.insights && result.insights.highlights.length > 0 ? (
          <ul
            className="takeaway-list"
            style={{ paddingLeft: "1.25rem", margin: "0.5rem 0" }}
          >
            {result.insights.highlights.map((highlight, idx) => (
              <li
                key={idx}
                style={{ marginBottom: "0.35rem", lineHeight: "1.4" }}
              >
                {highlight}
              </li>
            ))}
          </ul>
        ) : (
          <>
            <p>
              {result.nutrition.table_rows.length
                ? `NutriLens found a ${nutritionBasis} nutrition table with ${result.nutrition.table_rows.length} rows.`
                : "No reliable nutrition table was recovered; check the label or rescan in better light."}
            </p>
            <p>
              {result.ingredients.raw_text
                ? "Ingredient evidence was isolated from the package for review."
                : "No reliable ingredient section was recovered."}
            </p>
          </>
        )}
        {result.insights?.serving_context && (
          <p
            className="serving-context-note"
            style={{ fontSize: "0.85rem", opacity: 0.85, marginTop: "0.5rem" }}
          >
            📏 {result.insights.serving_context}
          </p>
        )}
      </article>
      {result.insights &&
        (result.insights.positive_signals.length > 0 ||
          result.insights.things_to_watch.length > 0) && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
              gap: "0.75rem",
              margin: "0.5rem 0",
            }}
          >
            {result.insights.positive_signals.length > 0 && (
              <article
                className="card"
                style={{
                  borderColor: "#10b981",
                  background: "rgba(16, 185, 129, 0.05)",
                }}
              >
                <h3
                  style={{
                    color: "#10b981",
                    fontSize: "0.95rem",
                    fontWeight: 600,
                    display: "flex",
                    alignItems: "center",
                    gap: "0.4rem",
                    margin: "0 0 0.4rem 0",
                  }}
                >
                  <span>✅</span> Positive signals
                </h3>
                <ul
                  style={{
                    paddingLeft: "1.2rem",
                    fontSize: "0.85rem",
                    margin: 0,
                  }}
                >
                  {result.insights.positive_signals.map((sig, idx) => (
                    <li key={idx} style={{ marginBottom: "0.2rem" }}>
                      {sig}
                    </li>
                  ))}
                </ul>
              </article>
            )}
            {result.insights.things_to_watch.length > 0 && (
              <article
                className="card"
                style={{
                  borderColor: "#f59e0b",
                  background: "rgba(245, 158, 11, 0.05)",
                }}
              >
                <h3
                  style={{
                    color: "#d97706",
                    fontSize: "0.95rem",
                    fontWeight: 600,
                    display: "flex",
                    alignItems: "center",
                    gap: "0.4rem",
                    margin: "0 0 0.4rem 0",
                  }}
                >
                  <span>⚠️</span> Things to watch
                </h3>
                <ul
                  style={{
                    paddingLeft: "1.2rem",
                    fontSize: "0.85rem",
                    margin: 0,
                  }}
                >
                  {result.insights.things_to_watch.map((watch, idx) => (
                    <li key={idx} style={{ marginBottom: "0.2rem" }}>
                      {watch}
                    </li>
                  ))}
                </ul>
              </article>
            )}
          </div>
        )}
      {result.insights && result.insights.ask_nutri_suggestions.length > 0 && (
        <article
          className="card"
          style={{
            padding: "0.85rem 1rem",
            margin: "0.5rem 0",
            background: "rgba(99, 102, 241, 0.04)",
            borderColor: "rgba(99, 102, 241, 0.2)",
          }}
        >
          <p
            style={{
              fontSize: "0.85rem",
              fontWeight: 600,
              color: "#6366f1",
              margin: "0 0 0.5rem 0",
              display: "flex",
              alignItems: "center",
              gap: "0.4rem",
            }}
          >
            <Bot size={15} /> Ask Nutri about this scan
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem" }}>
            {result.insights.ask_nutri_suggestions.map((suggestion, idx) => (
              <button
                key={idx}
                type="button"
                className="outline-button"
                style={{
                  fontSize: "0.8rem",
                  padding: "0.35rem 0.75rem",
                  borderRadius: "1rem",
                  cursor: "pointer",
                }}
                onClick={() => onAskNutri(suggestion)}
              >
                💬 {suggestion}
              </button>
            ))}
          </div>
        </article>
      )}
      {allergenEvidence && (
        <article className="card explicit-allergen" role="alert">
          <ShieldCheck size={20} />
          <div>
            <h2>{allergenEvidence}</h2>
            <p>Package allergen statement / OCR</p>
            <p>
              Check the original label. OCR cannot establish allergy safety.
            </p>
          </div>
        </article>
      )}
      <div className="r3-grid">
        <article className="card technical-card">
          <details>
            <summary>Image quality details</summary>
            {quality ? (
              <div className="r3-facts">
                <span>
                  Blur <b>{quality.blur_status}</b>
                  <small>{quality.blur_score.toFixed(1)}</small>
                </span>
                <span>
                  Brightness <b>{quality.brightness_status}</b>
                  <small>{quality.brightness_score.toFixed(1)}</small>
                </span>
                <span>
                  Contrast <b>{quality.contrast_status}</b>
                  <small>{quality.contrast_score.toFixed(1)}</small>
                </span>
                <span>
                  Resolution <b>{quality.resolution_ok ? "OK" : "RETRY"}</b>
                  <small>{quality.quality_status}</small>
                </span>
              </div>
            ) : (
              <p>No quality result.</p>
            )}
          </details>
        </article>
        <article className="card technical-card">
          <details>
            <summary>OCR and processing details</summary>
            <div className="r3-meta">
              <span>
                Processing status <b>{result.status.replaceAll("_", " ")}</b>
              </span>
              <span>
                Processing time <b>{Math.round(result.timings.total_ms)} ms</b>
              </span>
              <span>
                Selected engine{" "}
                <b>{ocr?.selected_engine ?? "None available"}</b>
              </span>
              <span>
                OCR confidence{" "}
                <b>
                  <ConfidenceValue value={ocr?.confidence ?? null} />
                </b>
              </span>
              <span>
                Attempts{" "}
                <b>
                  {ocr?.attempts
                    .map((attempt) => `${attempt.engine}: ${attempt.status}`)
                    .join(" · ")}
                </b>
              </span>
            </div>
            <pre>{ocr?.text || "No text was recognized."}</pre>
            {result.warnings.map((warning) => (
              <p key={warning} className="technical-warning">
                <Info size={16} /> {warning}
              </p>
            ))}
          </details>
        </article>
        <article className="card">
          <h2>Nutrition table</h2>
          <p className="r3-caption">
            Basis: {result.nutrition.basis} · confidence{" "}
            <ConfidenceValue value={result.nutrition.confidence} />
          </p>
          {result.nutrition.table_rows.length ? (
            <div className="r3-table-wrap">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Nutrient</th>
                    {(result.nutrition.table_columns?.length
                      ? result.nutrition.table_columns
                      : (result.nutrition.table_rows[0]?.values.map(
                          (_, index) => `Value ${index + 1}`,
                        ) ?? [])
                    ).map((column) => (
                      <th scope="col" key={column}>
                        {column.replaceAll("_", " ")}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.nutrition.table_rows.map((row, index) => (
                    <tr key={`${row.label}-${index}`}>
                      <th scope="row">{row.label}</th>
                      {row.values.map((value, valueIndex) => (
                        <td key={`${row.label}-${valueIndex}`}>
                          {value} {row.units[valueIndex] ?? ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p>No nutrition rows extracted.</p>
          )}
        </article>
        <article className="card">
          <h2>Ingredient intelligence</h2>
          <p>
            {result.ingredients.raw_text || "No ingredient region extracted."}
          </p>
          {intelligenceError && <p className="r4-error">{intelligenceError}</p>}
          {intelligence && (
            <div className="r4-intelligence">
              <div className="r4-summary">
                <span>
                  <b>{intelligence.complexity.ingredient_count}</b> ingredients
                </span>
                <span>
                  <b>{intelligence.complexity.level}</b> complexity
                </span>
                <span>
                  <b>{intelligence.nova.group_number ?? "Unknown"}</b> NOVA
                </span>
                <span>
                  <b>{intelligence.confidence.state}</b> evidence confidence
                </span>
              </div>
              <div className="r4-groups">
                <R4Group
                  title={
                    intelligence.allergens.some(
                      (item) =>
                        item.allergen.matched &&
                        item.allergen.match_method === "EXPLICIT_STATEMENT",
                    )
                      ? "Contains"
                      : "Allergens"
                  }
                  items={intelligence.allergens
                    .filter((item) => item.allergen.matched)
                    .map(
                      (item) =>
                        item.allergen.canonical_name ?? "Unknown allergen",
                    )}
                  safety
                  provenance={
                    intelligence.allergens.some(
                      (item) =>
                        item.allergen.matched &&
                        item.allergen.evidence_source ===
                          "PACKAGE_ALLERGEN_STATEMENT_OCR",
                    )
                      ? "Package allergen statement / OCR"
                      : undefined
                  }
                />
                <R4Group
                  title="Additives & preservatives"
                  items={[
                    ...intelligence.additives
                      .filter((item) => item.additive.matched)
                      .map(
                        (item) =>
                          item.additive.external_code ??
                          item.additive.canonical_name ??
                          "Additive",
                      ),
                    ...intelligence.preservatives.signals.map(
                      (item) => item.ingredient_text,
                    ),
                  ]}
                />
                <R4Group
                  title="Sugar & sweeteners"
                  items={[
                    ...intelligence.hidden_sugars.signals,
                    ...intelligence.sweeteners.signals,
                  ].map((item) => item.ingredient_text)}
                />
                <R4Group
                  title="Sodium sources"
                  items={intelligence.sodium_sources.signals.map(
                    (item) => item.ingredient_text,
                  )}
                />
                <R4Group
                  title="Oil & fat sources"
                  items={intelligence.oils_and_fats.signals.map(
                    (item) => item.ingredient_text,
                  )}
                />
              </div>
              <details>
                <summary>Why this result?</summary>
                <p>
                  Method: {intelligence.confidence.method}. Sources:{" "}
                  {intelligence.confidence.source_datasets.join(", ") ||
                    "No governed taxonomy match"}
                  . Unresolved ingredients remain explicit rather than being
                  guessed.
                </p>
                {counterfactuals?.state === "AVAILABLE" && (
                  <div className="counterfactual-list">
                    <strong>Observed-signal counterfactuals</strong>
                    {counterfactuals.factors.map((factor) => (
                      <div key={factor.factor_id}>
                        <b>{factor.label}</b>
                        <p>{factor.hypothesis}</p>
                        <p>{factor.result_change}</p>
                        <small>
                          Evidence: {factor.observed_evidence.join(" · ")}
                        </small>
                      </div>
                    ))}
                    <small>{counterfactuals.limitation}</small>
                  </div>
                )}
                {counterfactuals?.state === "NO_OBSERVED_SIGNALS" && (
                  <p>
                    No recognized label-signal category is available for a
                    bounded counterfactual.
                  </p>
                )}
              </details>
            </div>
          )}
        </article>
        <article className="card technical-card">
          <details>
            <summary>Codes and region details</summary>
            <div className="r3-meta">
              <span>
                Barcodes{" "}
                <b>
                  {result.barcode_results
                    .map((code) => `${code.symbology} ${code.value}`)
                    .join(" · ") || "None"}
                </b>
              </span>
              <span>
                QR payloads{" "}
                <b>
                  {result.qr_results
                    .map((code) => `${code.value} (${code.safety_status})`)
                    .join(" · ") || "None"}
                </b>
              </span>
              <span>
                Regions{" "}
                <b>
                  {result.regions
                    .map((region) => `${region.region_type} · ${region.method}`)
                    .join("; ") || "None"}
                </b>
              </span>
            </div>
          </details>
        </article>
        <article className="card technical-card">
          <details>
            <summary>Candidates and portions</summary>
            <div className="r3-meta">
              <span>
                Brand{" "}
                <b>
                  {result.brand_candidates
                    .map((item) => item.value)
                    .join(" · ") || "Unknown"}
                </b>
              </span>
              <span>
                Product{" "}
                <b>
                  {result.product_name_candidates
                    .map((item) => item.value)
                    .join(" · ") || "Unknown"}
                </b>
              </span>
              <span>
                Category{" "}
                <b>
                  {result.category_candidates
                    .map((item) => item.value)
                    .join(" · ") || "Unknown"}
                </b>
              </span>
              <span>
                Dates{" "}
                <b>
                  {result.date_candidates
                    .map(
                      (item) =>
                        `${item.date_type}: ${item.parsed_date ?? item.raw_text}${
                          item.ambiguous ? " (ambiguous)" : ""
                        }`,
                    )
                    .join(" · ") || "None"}
                </b>
              </span>
              <span>
                Meal items{" "}
                <b>
                  {result.meal_items
                    .flatMap((item) =>
                      item.food_candidates.map((candidate) => candidate.value),
                    )
                    .join(" · ") || "None"}
                </b>
              </span>
              <span>
                Portion{" "}
                <b>
                  {result.portion_estimates
                    .map((item) => item.method)
                    .join(" · ") || "Not applicable"}
                </b>
              </span>
            </div>
          </details>
        </article>
      </div>
      <article className="card correction-card">
        <div>
          <h2>Manual correction</h2>
          <p>
            Corrections stay in this ephemeral scan and never become training
            labels automatically.
          </p>
        </div>
        <div className="correction-form">
          <select
            value={field}
            onChange={(event) => setField(event.target.value)}
          >
            {[
              "product_name",
              "brand",
              "barcode",
              "nutrition_text",
              "ingredient_text",
              "detected_region",
              "food_category",
              "meal_item",
              "serving_amount",
            ].map((option) => (
              <option key={option} value={option}>
                {option.replaceAll("_", " ")}
              </option>
            ))}
          </select>
          <input
            value={correction}
            onChange={(event) => setCorrection(event.target.value)}
            placeholder="Corrected value"
          />
          <button
            className="primary"
            onClick={correct}
            disabled={saving || !correction.trim()}
          >
            {saving ? "Saving…" : "Save correction"}
          </button>
        </div>
        {error && <p className="scan-error">{error}</p>}
        {result.corrections.length > 0 && (
          <small>
            {result.corrections.length} correction(s) stored · images retained:{" "}
            {String(result.images_retained)}
          </small>
        )}
      </article>
    </div>
  );
}

type DiaryEntry = {
  id: string;
  name: string;
  eaten_at: string;
  serving_grams: number | null;
  scan_id: string | null;
  source?: string;
  recipe_id?: string | null;
  recipe_version?: number | null;
  recipe_servings?: number | null;
  nutrients: NutrientSnapshot;
};

type MealComparison = {
  candidates: Array<{
    entry_id: string;
    name: string;
    eaten_at: string;
    serving_grams: number | null;
    logged_serving: DiaryEntry["nutrients"];
    per_100g: DiaryEntry["nutrients"] | null;
  }>;
  compared_nutrients: string[];
  method: string;
  limitation: string;
};

function DiaryView({ ownerId }: { ownerId: string }) {
  const [entries, setEntries] = useState<DiaryEntry[]>([]);
  const [name, setName] = useState("");
  const [calories, setCalories] = useState("");
  const [protein, setProtein] = useState("");
  const [sodium, setSodium] = useState("");
  const [fiber, setFiber] = useState("");
  const [calcium, setCalcium] = useState("");
  const [iron, setIron] = useState("");
  const [potassium, setPotassium] = useState("");
  const [vitaminC, setVitaminC] = useState("");
  const [message, setMessage] = useState("Loading your private diary…");
  const [saving, setSaving] = useState(false);
  const [selectedEntryIds, setSelectedEntryIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<MealComparison | null>(null);
  const [comparing, setComparing] = useState(false);
  const [editingDiaryEntry, setEditingDiaryEntry] = useState<DiaryEntry | null>(
    null,
  );
  const [editedDiaryName, setEditedDiaryName] = useState("");
  const [diaryEditError, setDiaryEditError] = useState("");
  const [savingDiaryEdit, setSavingDiaryEdit] = useState(false);

  useEffect(() => {
    let active = true;
    void fetch("/api/backend/diary", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(
            response.status === 401
              ? "Sign in to sync your private diary."
              : "Diary entries are unavailable right now.",
          );
        }
        return (await response.json()) as DiaryEntry[];
      })
      .then((payload) => {
        if (active) {
          setEntries(payload);
          setMessage(
            payload.length
              ? "Synced with your account."
              : "No diary entries yet.",
          );
        }
      })
      .catch((reason: unknown) => {
        if (active)
          setMessage(
            reason instanceof Error ? reason.message : "Diary unavailable.",
          );
      });
    return () => {
      active = false;
    };
  }, []);

  const addEntry = async () => {
    if (!name.trim()) return;
    setSaving(true);
    const response = await fetch("/api/backend/diary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: name.trim(),
        nutrients: {
          calories: calories.trim() ? Number(calories) : null,
          protein_g: protein.trim() ? Number(protein) : null,
          sodium_mg: sodium.trim() ? Number(sodium) : null,
          fiber_g: fiber.trim() ? Number(fiber) : null,
          calcium_mg: calcium.trim() ? Number(calcium) : null,
          iron_mg: iron.trim() ? Number(iron) : null,
          potassium_mg: potassium.trim() ? Number(potassium) : null,
          vitamin_c_mg: vitaminC.trim() ? Number(vitaminC) : null,
        },
      }),
    });
    if (response.ok) {
      const created = (await response.json()) as DiaryEntry;
      setEntries((current) => [created, ...current]);
      setName("");
      setCalories("");
      setProtein("");
      setSodium("");
      setFiber("");
      setCalcium("");
      setIron("");
      setPotassium("");
      setVitaminC("");
      setMessage("Entry saved to your NutriLens account.");
    } else {
      setMessage(
        response.status === 401
          ? "Sign in to add entries."
          : "Entry could not be saved.",
      );
    }
    setSaving(false);
  };

  const removeEntry = async (entry: DiaryEntry) => {
    const response = await fetch(
      `/api/backend/diary/${encodeURIComponent(entry.id)}`,
      {
        method: "DELETE",
      },
    );
    if (!response.ok) {
      setMessage("Entry could not be removed.");
      return;
    }
    setEntries((current) =>
      current.filter((candidate) => candidate.id !== entry.id),
    );
    setMessage("Entry removed.");
  };
  const openDiaryEdit = (entry: DiaryEntry) => {
    setEditingDiaryEntry(entry);
    setEditedDiaryName(entry.name);
    setDiaryEditError("");
  };
  const editEntry = async () => {
    const entry = editingDiaryEntry;
    const updatedName = editedDiaryName.trim();
    if (!entry || !updatedName) {
      setDiaryEditError("Add a meal name to continue.");
      return;
    }
    if (updatedName === entry.name) {
      setEditingDiaryEntry(null);
      return;
    }
    setSavingDiaryEdit(true);
    setDiaryEditError("");
    const response = await fetch(
      `/api/backend/diary/${encodeURIComponent(entry.id)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: updatedName }),
      },
    );
    setSavingDiaryEdit(false);
    if (!response.ok) {
      setDiaryEditError("Entry could not be updated.");
      return;
    }
    const updated = (await response.json()) as DiaryEntry;
    setEntries((current) =>
      current.map((candidate) =>
        candidate.id === updated.id ? updated : candidate,
      ),
    );
    setMessage("Entry updated.");
    setEditingDiaryEntry(null);
  };
  const toggleComparisonEntry = (entryId: string) => {
    setSelectedEntryIds((current) =>
      current.includes(entryId)
        ? current.filter((candidate) => candidate !== entryId)
        : current.length < 5
          ? [...current, entryId]
          : current,
    );
    setComparison(null);
  };
  const compareEntries = async () => {
    if (selectedEntryIds.length < 2) return;
    setComparing(true);
    const response = await fetch("/api/backend/diary/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry_ids: selectedEntryIds }),
    });
    if (response.ok) {
      setComparison((await response.json()) as MealComparison);
      setMessage("Comparison uses only your recorded diary values.");
    } else {
      setMessage("Selected meals could not be compared.");
    }
    setComparing(false);
  };

  return (
    <div className="page narrow fade-in">
      <section className="welcome">
        <div>
          <p className="eyebrow">PERSONAL NUTRITION</p>
          <h1>Your food diary.</h1>
          <p>
            Log label-reported nutrition; the backend keeps your account history
            authoritative.
          </p>
        </div>
      </section>
      <HydrationPanel key={ownerId} ownerId={ownerId} />
      <div className="diary-layout">
        <article className="card diary-form">
          <div className="section-heading">
            <div>
              <h2>Add an entry</h2>
              <p>
                Use the serving and nutrition values you actually consumed.
                Leave unknown nutrients blank.
              </p>
            </div>
          </div>
          <label>
            Food or meal
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={200}
            />
          </label>
          <div className="diary-fields">
            {[
              ["Calories", calories, setCalories, "kcal"],
              ["Protein", protein, setProtein, "g"],
              ["Sodium", sodium, setSodium, "mg"],
              ["Fiber", fiber, setFiber, "g"],
              ["Calcium", calcium, setCalcium, "mg"],
              ["Iron", iron, setIron, "mg"],
              ["Potassium", potassium, setPotassium, "mg"],
              ["Vitamin C", vitaminC, setVitaminC, "mg"],
            ].map(([label, value, setter, unit]) => (
              <label key={label as string}>
                {label as string}
                <span>
                  <input
                    min="0"
                    step="0.1"
                    type="number"
                    value={value as string}
                    onChange={(event) =>
                      (setter as (value: string) => void)(event.target.value)
                    }
                  />
                  {unit as string}
                </span>
              </label>
            ))}
          </div>
          <button
            className="primary"
            disabled={saving || !name.trim()}
            onClick={() => void addEntry()}
          >
            <Plus size={16} /> {saving ? "Saving…" : "Add to diary"}
          </button>
          <small className="sync-note" role="status">
            {message}
          </small>
        </article>
        <article className="card diary-list">
          <div className="section-heading">
            <div>
              <h2>Recent entries</h2>
              <p>{entries.length} entries in your plan history window.</p>
            </div>
            <button
              className="dark-button"
              disabled={selectedEntryIds.length < 2 || comparing}
              onClick={() => void compareEntries()}
            >
              {comparing
                ? "Comparing…"
                : `Compare ${selectedEntryIds.length || "meals"}`}
            </button>
          </div>
          {entries.length === 0 && (
            <p className="history-state">
              Your recent entries will appear here.
            </p>
          )}
          {entries.map((entry) => (
            <div className="diary-entry" key={entry.id}>
              <div>
                <strong>{entry.name}</strong>
                <span>
                  {new Date(entry.eaten_at).toLocaleString()} ·{" "}
                  {servingText(entry)}
                </span>
              </div>
              <b>{nutrientText(entry.nutrients.calories, "kcal", 0)}</b>
              <span>
                Protein: {nutrientText(entry.nutrients.protein_g, "g")} ·{" "}
                Sodium: {nutrientText(entry.nutrients.sodium_mg, "mg")}
              </span>
              <span>
                Fiber: {nutrientText(entry.nutrients.fiber_g, "g")} · Calcium:{" "}
                {nutrientText(entry.nutrients.calcium_mg, "mg")} · Iron:{" "}
                {nutrientText(entry.nutrients.iron_mg, "mg")}
              </span>
              <div className="diary-entry-actions">
                <label className="comparison-selector">
                  <input
                    type="checkbox"
                    checked={selectedEntryIds.includes(entry.id)}
                    disabled={
                      !selectedEntryIds.includes(entry.id) &&
                      selectedEntryIds.length >= 5
                    }
                    onChange={() => toggleComparisonEntry(entry.id)}
                  />
                  Compare
                </label>
                <button
                  className="text-button"
                  onClick={() => openDiaryEdit(entry)}
                >
                  Edit
                </button>
                <button
                  className="text-button"
                  onClick={() => void removeEntry(entry)}
                >
                  Remove
                </button>
              </div>
            </div>
          ))}
          {comparison && (
            <section className="meal-comparison" aria-live="polite">
              <div className="section-heading">
                <div>
                  <h3>Recorded meal comparison</h3>
                  <p>Logged serving values with a size-normalized reference.</p>
                </div>
              </div>
              <div className="meal-comparison-grid">
                {comparison.candidates.map((candidate) => (
                  <article key={candidate.entry_id}>
                    <strong>{candidate.name}</strong>
                    <span>{servingText(candidate)}</span>
                    <b>
                      {nutrientText(candidate.logged_serving.calories, "kcal")}
                    </b>
                    <span>
                      Protein:{" "}
                      {nutrientText(candidate.logged_serving.protein_g, "g")}
                    </span>
                    <span>
                      Fiber:{" "}
                      {nutrientText(candidate.logged_serving.fiber_g, "g")}
                    </span>
                    <span>
                      Sodium:{" "}
                      {nutrientText(candidate.logged_serving.sodium_mg, "mg")}
                    </span>
                    <small>
                      {candidate.serving_grams == null ? (
                        "Per 100 g unavailable: serving mass is unknown."
                      ) : (
                        <>
                          Per 100 g:{" "}
                          {nutrientText(candidate.per_100g?.calories, "kcal")} ·{" "}
                          Protein:{" "}
                          {nutrientText(candidate.per_100g?.protein_g, "g")}
                        </>
                      )}
                    </small>
                  </article>
                ))}
              </div>
              <p className="history-state">{comparison.limitation}</p>
            </section>
          )}
        </article>
      </div>
      {editingDiaryEntry && (
        <div className="nutrilens-dialog-backdrop">
          <div
            className="nutrilens-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="diary-edit-title"
          >
            <div className="dialog-heading">
              <div>
                <h2 id="diary-edit-title">Edit diary entry</h2>
                <p>Update the private name used for this recorded meal.</p>
              </div>
              <button
                type="button"
                className="icon-btn"
                aria-label="Close dialog"
                disabled={savingDiaryEdit}
                onClick={() => setEditingDiaryEntry(null)}
              >
                <X size={18} />
              </button>
            </div>
            <form
              className="dialog-form"
              onSubmit={(event) => {
                event.preventDefault();
                void editEntry();
              }}
            >
              <label>
                Food or meal name
                <input
                  autoFocus
                  maxLength={200}
                  value={editedDiaryName}
                  onChange={(event) => setEditedDiaryName(event.target.value)}
                  disabled={savingDiaryEdit}
                />
              </label>
              {diaryEditError && (
                <p className="dialog-error" role="alert">
                  {diaryEditError}
                </p>
              )}
              <div className="dialog-actions">
                <button
                  type="button"
                  disabled={savingDiaryEdit}
                  onClick={() => setEditingDiaryEntry(null)}
                >
                  Cancel
                </button>
                <button
                  className="primary"
                  type="submit"
                  disabled={savingDiaryEdit}
                >
                  {savingDiaryEdit ? "Saving…" : "Save changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function AnalyticsView() {
  const [analyticsNow] = useState(() => Date.now());
  const [period, setPeriod] = useState<7 | 30 | 90>(7);
  const [metric, setMetric] = useState<"calories" | "protein" | "sugar">(
    "calories",
  );
  const [trend, setTrend] = useState<
    Array<{
      date: string;
      day: string;
      calories: number | null;
      protein: number | null;
      sugar: number | null;
    }>
  >([]);
  const [selectedDrilldownDate, setSelectedDrilldownDate] = useState("");
  const [drilldown, setDrilldown] = useState<{
    period_days: number;
    selected_date: string | null;
    entries: DiaryEntry[];
    limitation: string;
  } | null>(null);
  const [patterns, setPatterns] = useState<{
    period_days: number;
    state: "AVAILABLE" | "INSUFFICIENT_HISTORY";
    observed_days: number;
    minimum_observed_days: number;
    observations: Array<{
      kind: string;
      label: string;
      evidence: string;
      supporting_records: number;
    }>;
    limitation: string;
  } | null>(null);
  const [periodComparison, setPeriodComparison] = useState<{
    state: "AVAILABLE" | "INSUFFICIENT_HISTORY";
    period_days: number;
    current: { logged_days: number; diary_entries: number };
    previous: { logged_days: number; diary_entries: number };
    stories: Array<{
      kind: string;
      title: string;
      evidence: string;
      supporting_records: number;
    }>;
    limitation: string;
  } | null>(null);
  const [weightSummary, setWeightSummary] = useState<WeightHistory | null>(
    null,
  );
  const [weightSummaryLoaded, setWeightSummaryLoaded] = useState(false);
  const chartData = trend;
  const totals = useMemo(
    () => knownTotal(chartData.map((point) => point[metric])),
    [chartData, metric],
  );
  const [summary, setSummary] = useState<{
    diary_entries: number;
    period_days: number;
    daily_averages: NutrientSnapshot;
    insights: string[];
    goal_tracking_state: "AVAILABLE" | "NOT_CONFIGURED" | "DISABLED_NO_CONSENT";
    goal_progress: Array<{
      nutrient: string;
      label: string;
      unit: string;
      daily_average: number | null;
      user_target: number;
      percent_of_target: number | null;
    }>;
    goal_tracking_limitation: string;
  } | null>(null);
  const macroSplit = useMemo(() => {
    const averages = summary?.daily_averages;
    if (
      averages?.protein_g == null ||
      averages.carbs_g == null ||
      averages.fat_g == null
    )
      return [];
    const proteinKcal = averages.protein_g * 4;
    const carbsKcal = averages.carbs_g * 4;
    const fatKcal = averages.fat_g * 9;
    const total = proteinKcal + carbsKcal + fatKcal;
    const percentage = (value: number) =>
      total > 0 ? Math.round((value / total) * 100) : 0;
    return [
      { name: "Protein", value: percentage(proteinKcal), color: "#0b8f6a" },
      { name: "Carbs", value: percentage(carbsKcal), color: "#e3b55a" },
      { name: "Fat", value: percentage(fatKcal), color: "#9b82d4" },
    ];
  }, [summary]);
  const hasMacroEvidence = macroSplit.some((item) => item.value > 0);
  const weightWindow = useMemo(() => {
    if (weightSummary?.state !== "ACTIVE") return [];
    const cutoff = analyticsNow - period * 24 * 60 * 60 * 1000;
    return weightSummary.entries
      .filter((entry) => Date.parse(entry.recorded_at) >= cutoff)
      .toSorted(
        (left, right) =>
          Date.parse(left.recorded_at) - Date.parse(right.recorded_at),
      )
      .map((entry) => ({
        ...entry,
        day: new Date(entry.recorded_at).toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        }),
      }));
  }, [analyticsNow, period, weightSummary]);
  const weightWindowChange =
    weightWindow.length > 1
      ? Number(
          (weightWindow.at(-1)!.weight_kg - weightWindow[0].weight_kg).toFixed(
            2,
          ),
        )
      : null;
  useEffect(() => {
    let active = true;
    void fetch("/api/backend/weight?limit=365", { cache: "no-store" })
      .then(async (response) =>
        response.ok ? weightHistory(await response.json()) : null,
      )
      .then((payload) => {
        if (!active) return;
        setWeightSummary(payload);
        setWeightSummaryLoaded(true);
      })
      .catch(() => {
        if (active) setWeightSummaryLoaded(true);
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    Promise.all([
      fetch(`/api/backend/analytics/summary?days=${period}`, {
        cache: "no-store",
      }),
      fetch(`/api/backend/analytics/trend?days=${period}`, {
        cache: "no-store",
      }),
      fetch(
        `/api/backend/analytics/drilldown?days=${period}${
          selectedDrilldownDate
            ? `&date=${encodeURIComponent(selectedDrilldownDate)}`
            : ""
        }`,
        { cache: "no-store" },
      ),
      fetch(`/api/backend/analytics/patterns?days=${period}`, {
        cache: "no-store",
      }),
      fetch(`/api/backend/analytics/compare?days=${period}`, {
        cache: "no-store",
      }),
    ])
      .then(
        async ([
          summaryResponse,
          trendResponse,
          drilldownResponse,
          patternsResponse,
          comparisonResponse,
        ]) => {
          const summaryPayload = summaryResponse.ok
            ? await summaryResponse.json()
            : null;
          const trendPayload = trendResponse.ok
            ? ((await trendResponse.json()) as Array<{
                date: string;
                calories: number | null;
                protein_g: number | null;
                sugar_g: number | null;
              }>)
            : null;
          const drilldownPayload = drilldownResponse.ok
            ? ((await drilldownResponse.json()) as typeof drilldown)
            : null;
          const patternsPayload = patternsResponse.ok
            ? ((await patternsResponse.json()) as typeof patterns)
            : null;
          const comparisonPayload = comparisonResponse.ok
            ? ((await comparisonResponse.json()) as typeof periodComparison)
            : null;
          return {
            summaryPayload,
            trendPayload,
            drilldownPayload,
            patternsPayload,
            comparisonPayload,
          };
        },
      )
      .then(
        ({
          summaryPayload,
          trendPayload,
          drilldownPayload,
          patternsPayload,
          comparisonPayload,
        }) => {
          if (!active) return;
          if (summaryPayload) setSummary(summaryPayload as typeof summary);
          if (trendPayload) {
            setTrend(
              trendPayload.map((point) => ({
                date: point.date,
                day: new Date(`${point.date}T00:00:00`).toLocaleDateString(
                  undefined,
                  {
                    weekday: "short",
                  },
                ),
                calories: point.calories,
                protein: point.protein_g,
                sugar: point.sugar_g,
              })),
            );
          }
          if (drilldownPayload) setDrilldown(drilldownPayload);
          if (patternsPayload) setPatterns(patternsPayload);
          if (comparisonPayload) setPeriodComparison(comparisonPayload);
        },
      )
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [period, selectedDrilldownDate]);
  return (
    <div className="page fade-in">
      <section className="welcome">
        <div>
          <p className="eyebrow">PERSONAL NUTRITION</p>
          <h1>Your nutrition, in focus.</h1>
          <p>Patterns that help you make the next choice easier.</p>
        </div>
        <div className="analytics-actions">
          <div className="metric-switch" aria-label="Analytics period">
            {([7, 30, 90] as const).map((days) => (
              <button
                className={period === days ? "active" : ""}
                key={days}
                onClick={() => {
                  setPeriod(days);
                  setSelectedDrilldownDate("");
                }}
              >
                <Clock3 size={15} /> {days} days
              </button>
            ))}
          </div>
          <a className="dark-button" href="/api/backend/analytics/export.csv">
            Download CSV
          </a>
        </div>
      </section>
      <div className="kpi-grid">
        <div className="card kpi">
          <span className="icon-well green">
            <TrendingUp />
          </span>
          <p>Diary entries</p>
          <strong>
            {summary?.diary_entries ?? 0} <small>logged</small>
          </strong>
          <em>
            {summary
              ? `${summary.period_days}-day entitlement window`
              : "Sign in to sync"}
          </em>
        </div>
        <div className="card kpi">
          <span className="icon-well peach">
            <Flame />
          </span>
          <p>Daily average</p>
          <strong>
            {nutrientText(summary?.daily_averages.calories, "kcal", 0)}
          </strong>
          <em className="neutral">From logged diary evidence</em>
        </div>
        <div className="card kpi">
          <span className="icon-well purple">
            <Wheat />
          </span>
          <p>Daily fibre</p>
          <strong>{nutrientText(summary?.daily_averages.fiber_g, "g")}</strong>
          <em className="neutral">From logged label evidence</em>
        </div>
        <div className="card kpi">
          <span className="icon-well blue">
            <Droplets />
          </span>
          <p>Daily calcium</p>
          <strong>
            {nutrientText(summary?.daily_averages.calcium_mg, "mg", 0)}
          </strong>
          <em className="neutral">
            Daily iron: {nutrientText(summary?.daily_averages.iron_mg, "mg")}
          </em>
        </div>
      </div>
      <article className="card analytics-drilldown">
        <div className="section-heading">
          <div>
            <span className="soft-label">Source records</span>
            <h2>Explore the entries behind these totals.</h2>
            <p>
              {drilldown?.limitation ?? "Loading your private diary records…"}
            </p>
          </div>
          <label>
            Day
            <select
              value={selectedDrilldownDate}
              onChange={(event) => setSelectedDrilldownDate(event.target.value)}
            >
              <option value="">All days</option>
              {trend
                .filter(
                  (point) =>
                    point.calories == null ||
                    point.protein == null ||
                    point.sugar == null ||
                    point.calories > 0 ||
                    point.protein > 0 ||
                    point.sugar > 0,
                )
                .map((point) => (
                  <option key={point.date} value={point.date}>
                    {new Date(`${point.date}T00:00:00`).toLocaleDateString()}
                  </option>
                ))}
            </select>
          </label>
        </div>
        {drilldown?.entries.length ? (
          <div className="drilldown-records">
            {drilldown.entries.map((entry) => (
              <div key={entry.id}>
                <strong>{entry.name}</strong>
                <span>{new Date(entry.eaten_at).toLocaleString()}</span>
                <span>{servingText(entry)}</span>
                <b>{nutrientText(entry.nutrients.calories, "kcal")}</b>
                <span>
                  Protein: {nutrientText(entry.nutrients.protein_g, "g")}
                </span>
                <span>
                  Sodium: {nutrientText(entry.nutrients.sodium_mg, "mg")}
                </span>
              </div>
            ))}
          </div>
        ) : (
          <p className="history-state">No diary entries in this selection.</p>
        )}
      </article>
      <article className="card analytics-comparison">
        <div className="section-heading">
          <div>
            <span className="soft-label">Adjacent period comparison</span>
            <h2>What changed in the records you logged?</h2>
            <p>
              {periodComparison?.limitation ??
                "Loading adjacent equal-window evidence…"}
            </p>
          </div>
          {periodComparison && (
            <span className="soft-label">
              {periodComparison.period_days} days vs previous{" "}
              {periodComparison.period_days}
            </span>
          )}
        </div>
        {periodComparison?.state === "AVAILABLE" ? (
          <div className="analytics-story-grid">
            {periodComparison.stories.map((story) => (
              <div key={`${story.kind}:${story.title}`}>
                <strong>{story.title}</strong>
                <span>{story.evidence}</span>
                <small>{story.supporting_records} supporting records</small>
              </div>
            ))}
          </div>
        ) : (
          <p className="history-state">
            Add diary entries in both adjacent {period}-day windows to compare
            them.
          </p>
        )}
      </article>
      <article className="card analytics-patterns">
        <div className="section-heading">
          <div>
            <span className="soft-label">Descriptive patterns</span>
            <h2>Longer-term signals in your logged history.</h2>
            <p>
              {patterns?.limitation ??
                "Loading bounded pattern evidence from your diary…"}
            </p>
          </div>
          {patterns && (
            <span className="soft-label">
              {patterns.observed_days}/{patterns.period_days} logged days
            </span>
          )}
        </div>
        {patterns?.state === "AVAILABLE" ? (
          <div className="pattern-observations">
            {patterns.observations.map((observation) => (
              <div key={`${observation.kind}:${observation.label}`}>
                <strong>{observation.label}</strong>
                <span>{observation.evidence}</span>
                <small>
                  {observation.supporting_records} supporting records
                </small>
              </div>
            ))}
          </div>
        ) : (
          <p className="history-state">
            Log entries on at least {patterns?.minimum_observed_days ?? 7}{" "}
            distinct days to enable descriptive pattern evidence.
          </p>
        )}
      </article>
      <article className="card story-card">
        <span className="icon-well blue">
          <Target />
        </span>
        <div>
          <span className="soft-label">Your references</span>
          <h2>Goal progress without an inferred target.</h2>
          {summary?.goal_tracking_state === "AVAILABLE" ? (
            <div className="goal-progress-list">
              {summary.goal_progress.map((item) => (
                <div key={item.nutrient}>
                  <span>
                    {item.label}: {nutrientText(item.daily_average)} of{" "}
                    {item.user_target.toLocaleString()} {item.unit} ·{" "}
                    {item.percent_of_target == null
                      ? "Progress unknown"
                      : `${item.percent_of_target.toFixed(0)}%`}
                  </span>
                  {item.percent_of_target != null && (
                    <progress
                      aria-label={`${item.label} progress`}
                      max={100}
                      value={Math.min(item.percent_of_target, 100)}
                    />
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p>
              {summary?.goal_tracking_state === "DISABLED_NO_CONSENT"
                ? "Enable personalization consent to compare diary evidence with your own references."
                : "Add optional daily references in Account to track them here."}
            </p>
          )}
          <p>
            {summary?.goal_tracking_limitation ??
              "NutriLens does not infer clinical nutrition targets."}
          </p>
        </div>
        <a className="dark-button" href="/account">
          Edit references <ArrowRight size={16} />
        </a>
      </article>
      <article
        aria-labelledby="analytics-weight-title"
        className="card analytics-weight-card"
      >
        <div className="section-heading">
          <div>
            <span className="soft-label">Optional self-reported records</span>
            <h2 id="analytics-weight-title">Weight history</h2>
            <p>
              Descriptive records in the selected {period}-day window. No pace,
              outcome or calorie prescription is inferred.
            </p>
          </div>
          <a className="full-text" href="/account#weight-tracking-title">
            Manage records <ArrowRight size={15} />
          </a>
        </div>
        {!weightSummaryLoaded ? (
          <p className="history-state" role="status">
            Loading optional weight history…
          </p>
        ) : weightSummary?.state === "DISABLED" ? (
          <p className="history-state">
            Weight tracking is off. No history is stored until you explicitly
            enable it.
          </p>
        ) : weightSummary?.state === "ACTIVE" && weightWindow.length ? (
          <>
            <div className="analytics-weight-summary">
              <div>
                <span>Latest in window</span>
                <strong>{weightText(weightWindow.at(-1)!.weight_kg)}</strong>
              </div>
              <div>
                <span>Selected-window change</span>
                <strong>{weightText(weightWindowChange)}</strong>
              </div>
              <div>
                <span>Records</span>
                <strong>{weightWindow.length}</strong>
              </div>
            </div>
            <div
              className="analytics-weight-chart"
              aria-label={`${period}-day self-reported weight chart`}
              role="img"
            >
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={weightWindow}>
                  <CartesianGrid vertical={false} stroke="#edf0ed" />
                  <XAxis dataKey="day" axisLine={false} tickLine={false} />
                  <Tooltip />
                  <Area
                    connectNulls={false}
                    dataKey="weight_kg"
                    fill="#dcefe6"
                    stroke="#0b8f6a"
                    strokeWidth={3}
                    type="monotone"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
            <p className="history-state">{weightSummary.limitation}</p>
          </>
        ) : weightSummary?.state === "ACTIVE" ? (
          <p className="history-state">
            No self-reported weight records fall inside this {period}-day
            window.
          </p>
        ) : (
          <p className="history-state" role="status">
            Weight history is temporarily unavailable. Nutrition analytics are
            unaffected.
          </p>
        )}
      </article>
      <div className="analytics-grid">
        <article className="card chart-card">
          <div className="section-heading">
            <div>
              <h2>Nutrition rhythm</h2>
              <p>Your daily intake across the selected evidence window.</p>
            </div>
            <div className="metric-switch">
              {(["calories", "protein", "sugar"] as const).map((m) => (
                <button
                  className={metric === m ? "active" : ""}
                  onClick={() => setMetric(m)}
                  key={m}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <defs>
                  <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#0b8f6a" stopOpacity={0.26} />
                    <stop offset="100%" stopColor="#0b8f6a" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="#edf0ed" />
                <XAxis dataKey="day" axisLine={false} tickLine={false} />
                <Tooltip />
                <Area
                  connectNulls={false}
                  type="monotone"
                  dataKey={metric}
                  stroke="#0b8f6a"
                  strokeWidth={3}
                  fill="url(#area)"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="chart-summary">
            <span>{period}-day total</span>
            <strong>
              {nutrientText(totals, metric === "calories" ? "kcal" : "g")}
            </strong>
          </div>
          {totals === null && (
            <p>
              Some logged entries lack this nutrient. Gaps and the unknown total
              are not zeros.
            </p>
          )}
        </article>
        <article className="card balance-card">
          <h2>Macro balance</h2>
          <p>Average energy split across logged diary evidence</p>
          <div className="donut-wrap">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={macroSplit}
                  dataKey="value"
                  innerRadius={62}
                  outerRadius={82}
                  startAngle={90}
                  endAngle={-270}
                >
                  {macroSplit.map((item) => (
                    <Cell fill={item.color} key={item.name} />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
            <div>
              <strong>{hasMacroEvidence ? "Logged" : "Unknown"}</strong>
              <span>energy split</span>
            </div>
          </div>
          <div className="legend">
            <span>
              <i className="protein" />
              Protein{" "}
              <b>{macroSplit[0] ? `${macroSplit[0].value}%` : "Unknown"}</b>
            </span>
            <span>
              <i className="carbs" />
              Carbs{" "}
              <b>{macroSplit[1] ? `${macroSplit[1].value}%` : "Unknown"}</b>
            </span>
            <span>
              <i className="fat" />
              Fat <b>{macroSplit[2] ? `${macroSplit[2].value}%` : "Unknown"}</b>
            </span>
          </div>
        </article>
      </div>
      <article className="card story-card">
        <span className="icon-well green">
          <Sparkles />
        </span>
        <div>
          <span className="soft-label">Period insight</span>
          <h2>
            {summary
              ? "What your logged evidence shows."
              : "Your private trends sync here."}
          </h2>
          <p>
            {summary?.insights.join(" ") ??
              "Sign in and add diary entries to replace illustrative charts with evidence from your account."}
          </p>
        </div>
        <button className="dark-button">
          Explore insight <ArrowRight size={16} />
        </button>
      </article>
    </div>
  );
}

type PantryUiItem = {
  id?: string;
  name: string;
  amount: string;
  quantity: number;
  unit: string;
  expiresOn: string | null;
  days: number;
  status: string;
  lowStockThreshold: number | null;
  itemRole: "INGREDIENT" | "LEFTOVER";
};

type ShoppingListUiItem = {
  id: string;
  name: string;
  checked: boolean;
  source: "MANUAL" | "LOW_STOCK" | "CUSTOM_RECIPE";
  quantity?: number | null;
  unit?: string | null;
  recipe_id?: string | null;
};

type RecipeRecommendation = {
  recipe_id: string;
  title: string;
  available_ingredients: string[];
  missing_required: string[];
  optional_available: string[];
  coverage: number;
  steps: string[];
  source_version: string;
  method: string;
  available_substitutions: Array<{
    missing_ingredient: string;
    available_alternative: string;
    function: string;
    limitation: string;
  }>;
  preparation_complexity: {
    band: "BASIC" | "MODERATE" | "INVOLVED";
    written_steps: number;
    required_ingredients: number;
    limitation: string;
  };
};

type UseSoonSuggestion = {
  recipe: RecipeRecommendation;
  attention_items: Array<{
    pantry_item_id: string;
    name: string;
    reasons: Array<"USER_MARKED_LEFTOVER" | "EXPIRES_TODAY" | "EXPIRING_SOON">;
  }>;
};

type RecipeNutritionDraft = {
  id: number;
  name: string;
  servings: string;
  calories: string;
  protein_g: string;
  carbs_g: string;
  fat_g: string;
  fiber_g: string;
  sodium_mg: string;
};

type RecipeNutritionResult = {
  candidates: Array<{
    name: string;
    servings: number;
    per_serving: {
      calories: number;
      protein_g: number;
      carbs_g: number;
      fat_g: number;
      fiber_g: number;
      sodium_mg: number;
    };
  }>;
  limitation: string;
};

const newRecipeDraft = (id: number, name = ""): RecipeNutritionDraft => ({
  id,
  name,
  servings: "1",
  calories: "",
  protein_g: "",
  carbs_g: "",
  fat_g: "",
  fiber_g: "",
  sodium_mg: "",
});

function RecipeNutritionComparison() {
  const [drafts, setDrafts] = useState<RecipeNutritionDraft[]>([
    newRecipeDraft(1, "Recipe one"),
    newRecipeDraft(2, "Recipe two"),
  ]);
  const [nextId, setNextId] = useState(3);
  const [result, setResult] = useState<RecipeNutritionResult | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const nutrientFields = [
    ["calories", "Energy (kcal)"],
    ["protein_g", "Protein (g)"],
    ["carbs_g", "Carbs (g)"],
    ["fat_g", "Fat (g)"],
    ["fiber_g", "Fiber (g)"],
    ["sodium_mg", "Sodium (mg)"],
  ] as const;

  const compare = async () => {
    setBusy(true);
    setMessage("");
    setResult(null);
    const response = await fetch("/api/backend/recipes/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        candidates: drafts.map((draft) => ({
          name: draft.name,
          servings: Number(draft.servings),
          source_label: "User-entered recipe totals",
          nutrients: Object.fromEntries(
            nutrientFields.map(([field]) => [field, Number(draft[field] || 0)]),
          ),
        })),
      }),
    });
    if (response.ok) {
      setResult((await response.json()) as RecipeNutritionResult);
    } else {
      const payload = (await response.json().catch(() => null)) as {
        detail?: string;
      } | null;
      setMessage(payload?.detail ?? "Recipe comparison could not be prepared.");
    }
    setBusy(false);
  };

  return (
    <div className="recipe-nutrition-comparison">
      <div>
        <h3>Compare recipe nutrition</h3>
        <button
          disabled={drafts.length >= 5}
          onClick={() => {
            setDrafts([...drafts, newRecipeDraft(nextId)]);
            setNextId(nextId + 1);
          }}
        >
          Add recipe
        </button>
      </div>
      <p>
        Enter totals for each complete recipe and its yield. NutriLens
        normalizes the supplied evidence per serving.
      </p>
      <div className="recipe-nutrition-drafts">
        {drafts.map((draft) => (
          <fieldset key={draft.id}>
            <legend>Recipe {drafts.indexOf(draft) + 1}</legend>
            <label>
              Name
              <input
                maxLength={200}
                value={draft.name}
                onChange={(event) =>
                  setDrafts(
                    drafts.map((item) =>
                      item.id === draft.id
                        ? { ...item, name: event.target.value }
                        : item,
                    ),
                  )
                }
              />
            </label>
            <label>
              Servings yielded
              <input
                type="number"
                min="0.01"
                max="1000"
                step="any"
                value={draft.servings}
                onChange={(event) =>
                  setDrafts(
                    drafts.map((item) =>
                      item.id === draft.id
                        ? { ...item, servings: event.target.value }
                        : item,
                    ),
                  )
                }
              />
            </label>
            {nutrientFields.map(([field, label]) => (
              <label key={field}>
                {label}, whole recipe
                <input
                  type="number"
                  min="0"
                  step="any"
                  value={draft[field]}
                  onChange={(event) =>
                    setDrafts(
                      drafts.map((item) =>
                        item.id === draft.id
                          ? { ...item, [field]: event.target.value }
                          : item,
                      ),
                    )
                  }
                />
              </label>
            ))}
            {drafts.length > 2 && (
              <button
                onClick={() =>
                  setDrafts(drafts.filter((item) => item.id !== draft.id))
                }
              >
                Remove
              </button>
            )}
          </fieldset>
        ))}
      </div>
      <button
        className="primary"
        disabled={
          busy ||
          drafts.some(
            (draft) => !draft.name.trim() || !(Number(draft.servings) > 0),
          )
        }
        onClick={() => void compare()}
      >
        {busy ? "Comparing…" : "Compare per serving"}
      </button>
      {message && <p role="alert">{message}</p>}
      {result && (
        <div className="recipe-nutrition-results">
          {result.candidates.map((candidate) => (
            <article key={candidate.name}>
              <strong>{candidate.name}</strong>
              <span>{candidate.per_serving.calories} kcal</span>
              <span>{candidate.per_serving.protein_g} g protein</span>
              <span>{candidate.per_serving.fiber_g} g fiber</span>
              <span>{candidate.per_serving.sodium_mg} mg sodium</span>
            </article>
          ))}
          <small>{result.limitation}</small>
        </div>
      )}
    </div>
  );
}

function PantryView({ ownerId }: { ownerId: string }) {
  const [todayMs] = useState(() => Date.now());
  const [items, setItems] = useState<PantryUiItem[]>([]);
  const [recipes, setRecipes] = useState<RecipeRecommendation[]>([]);
  const [useSoon, setUseSoon] = useState<UseSoonSuggestion[]>([]);
  const [syncMessage, setSyncMessage] = useState(
    "Loading your private pantry…",
  );
  const [shopping, setShopping] = useState<ShoppingListUiItem[]>([]);
  const [shoppingRefresh, setShoppingRefresh] = useState(0);
  const [dialog, setDialog] = useState<
    "add-pantry" | "edit-pantry" | "add-shopping" | null
  >(null);
  const [editingItem, setEditingItem] = useState<PantryUiItem | null>(null);
  const [pantryDraft, setPantryDraft] = useState({
    name: "",
    quantity: "1",
    lowStockThreshold: "",
    itemRole: "INGREDIENT" as "INGREDIENT" | "LEFTOVER",
    expiresOn: "",
  });
  const [shoppingName, setShoppingName] = useState("");
  const [dialogError, setDialogError] = useState("");
  const [dialogBusy, setDialogBusy] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let active = true;
    fetch("/api/backend/pantry", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(
            response.status === 401
              ? "Sign in to sync your private pantry."
              : "Pantry items are unavailable right now.",
          );
        }
        return (await response.json()) as Array<{
          id: string;
          name: string;
          quantity: number;
          unit: string;
          expires_on: string | null;
          low_stock_threshold: number | null;
          item_role: "INGREDIENT" | "LEFTOVER";
        }>;
      })
      .then((payload) => {
        if (!active || payload === null) return;
        const today = new Date();
        setItems(
          payload.map((item) => ({
            id: item.id,
            name: item.name,
            amount: `${item.quantity} ${item.unit}`,
            quantity: item.quantity,
            unit: item.unit,
            expiresOn: item.expires_on,
            days: item.expires_on
              ? Math.max(
                  0,
                  Math.ceil(
                    (new Date(item.expires_on).getTime() - today.getTime()) /
                      86_400_000,
                  ),
                )
              : 365,
            status: item.expires_on ? "Tracked" : "No expiry",
            lowStockThreshold: item.low_stock_threshold,
            itemRole: item.item_role,
          })),
        );
        setSyncMessage("Synced securely with your NutriLens account.");
      })
      .catch((reason: unknown) => {
        if (active) {
          setSyncMessage(
            reason instanceof Error ? reason.message : "Pantry unavailable.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    void fetch("/api/backend/shopping-list", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Shopping list unavailable.");
        return (await response.json()) as ShoppingListUiItem[];
      })
      .then((payload) => {
        if (active) setShopping(payload);
      })
      .catch(() => {
        if (active) setShopping([]);
      });
    return () => {
      active = false;
    };
  }, [shoppingRefresh]);
  const pantryFingerprint = items
    .map(
      (item) =>
        `${item.id}:${item.name}:${item.expiresOn}:${item.itemRole}:${item.quantity}`,
    )
    .sort()
    .join("|");
  useEffect(() => {
    let active = true;
    void Promise.all([
      fetch("/api/backend/recipes/recommendations", { cache: "no-store" }),
      fetch("/api/backend/recipes/use-soon", { cache: "no-store" }),
    ])
      .then(async ([recommendationsResponse, useSoonResponse]) => ({
        recommendations: recommendationsResponse.ok
          ? ((await recommendationsResponse.json()) as RecipeRecommendation[])
          : [],
        useSoon: useSoonResponse.ok
          ? ((await useSoonResponse.json()) as {
              suggestions: UseSoonSuggestion[];
            })
          : { suggestions: [] },
      }))
      .then((payload) => {
        if (active) {
          setRecipes(pantryFingerprint ? payload.recommendations : []);
          setUseSoon(pantryFingerprint ? payload.useSoon.suggestions : []);
        }
      })
      .catch(() => {
        if (active) {
          setRecipes([]);
          setUseSoon([]);
        }
      });
    return () => {
      active = false;
    };
  }, [pantryFingerprint]);
  useEffect(() => {
    if (!dialog) return;
    const focusFirstControl = () => {
      dialogRef.current
        ?.querySelector<HTMLElement>(
          "input:not([disabled]), select:not([disabled])",
        )
        ?.focus();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !dialogBusy) {
        setDialog(null);
        setDialogError("");
        return;
      }
      if (event.key !== "Tab") return;
      const controls = Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled]), select:not([disabled])",
        ) ?? [],
      );
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    const frame = window.requestAnimationFrame(focusFirstControl);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [dialog, dialogBusy]);
  const removeItem = async (item: PantryUiItem) => {
    if (item.id) {
      const response = await fetch(
        `/api/backend/pantry/${encodeURIComponent(item.id)}`,
        {
          method: "DELETE",
        },
      );
      if (!response.ok) {
        setSyncMessage("The pantry item could not be removed.");
        return;
      }
    }
    setItems((current) => current.filter((candidate) => candidate !== item));
  };
  const closeDialog = () => {
    if (dialogBusy) return;
    setDialog(null);
    setEditingItem(null);
    setDialogError("");
  };
  const openAddPantryDialog = () => {
    setPantryDraft({
      name: "",
      quantity: "1",
      lowStockThreshold: "",
      itemRole: "INGREDIENT",
      expiresOn: "",
    });
    setDialogError("");
    setDialog("add-pantry");
  };
  const openEditPantryDialog = (item: PantryUiItem) => {
    setEditingItem(item);
    setPantryDraft({
      name: item.name,
      quantity: String(item.quantity),
      lowStockThreshold:
        item.lowStockThreshold === null ? "" : String(item.lowStockThreshold),
      itemRole: item.itemRole,
      expiresOn: item.expiresOn ?? "",
    });
    setDialogError("");
    setDialog("edit-pantry");
  };
  const savePantryItem = async () => {
    const parsedQuantity = Number(pantryDraft.quantity);
    if (!(parsedQuantity > 0)) {
      setDialogError("Quantity must be greater than zero.");
      return;
    }
    const parsedThreshold = pantryDraft.lowStockThreshold.trim()
      ? Number(pantryDraft.lowStockThreshold)
      : null;
    if (parsedThreshold !== null && !(parsedThreshold > 0)) {
      setDialogError("Low-stock threshold must be greater than zero.");
      return;
    }
    if (dialog === "add-pantry" && !pantryDraft.name.trim()) {
      setDialogError("Add an item name to continue.");
      return;
    }
    const payload = {
      quantity: parsedQuantity,
      low_stock_threshold: parsedThreshold,
      item_role: pantryDraft.itemRole,
      expires_on: pantryDraft.expiresOn.trim() || null,
    };
    setDialogBusy(true);
    setDialogError("");
    if (dialog === "add-pantry") {
      const response = await fetch("/api/backend/pantry", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...payload,
          name: pantryDraft.name.trim(),
          unit: "item",
        }),
      });
      setDialogBusy(false);
      if (!response.ok) {
        setDialogError(
          response.status === 401
            ? "Sign in to sync pantry items."
            : "The item could not be added.",
        );
        return;
      }
      const created = (await response.json()) as { id: string; name: string };
      setItems((current) => [
        ...current,
        {
          id: created.id,
          name: created.name,
          amount: `${parsedQuantity} item`,
          quantity: parsedQuantity,
          unit: "item",
          expiresOn: payload.expires_on,
          days: payload.expires_on
            ? Math.max(
                0,
                Math.ceil(
                  (new Date(payload.expires_on).getTime() - todayMs) /
                    86_400_000,
                ),
              )
            : 365,
          status: payload.expires_on ? "Tracked" : "No expiry",
          lowStockThreshold: parsedThreshold,
          itemRole: pantryDraft.itemRole,
        },
      ]);
      setSyncMessage("Item saved to your NutriLens account.");
      closeDialog();
      return;
    }
    const item = editingItem;
    if (!item?.id) {
      setDialogBusy(false);
      return;
    }
    const response = await fetch(
      `/api/backend/pantry/${encodeURIComponent(item.id)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    setDialogBusy(false);
    if (!response.ok) {
      setDialogError("The pantry item could not be updated.");
      return;
    }
    const updated = (await response.json()) as {
      expires_on: string | null;
      quantity: number;
      low_stock_threshold: number | null;
      item_role: "INGREDIENT" | "LEFTOVER";
    };
    const days = updated.expires_on
      ? Math.max(
          0,
          Math.ceil(
            (new Date(updated.expires_on).getTime() - todayMs) / 86_400_000,
          ),
        )
      : 365;
    setItems((current) =>
      current.map((candidate) =>
        candidate.id === item.id
          ? {
              ...candidate,
              expiresOn: updated.expires_on,
              quantity: updated.quantity,
              amount: `${updated.quantity} ${candidate.unit}`,
              lowStockThreshold: updated.low_stock_threshold,
              itemRole: updated.item_role,
              days,
              status: updated.expires_on ? "Tracked" : "No expiry",
            }
          : candidate,
      ),
    );
    setSyncMessage("Pantry item updated.");
    closeDialog();
  };
  const openShoppingDialog = () => {
    setShoppingName("");
    setDialogError("");
    setDialog("add-shopping");
  };
  const addShoppingItem = async () => {
    if (!shoppingName.trim()) {
      setDialogError("Add an item name to continue.");
      return;
    }
    setDialogBusy(true);
    setDialogError("");
    const response = await fetch("/api/backend/shopping-list", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: shoppingName.trim() }),
    });
    setDialogBusy(false);
    if (!response.ok) {
      setDialogError("The shopping item could not be saved.");
      return;
    }
    const created = (await response.json()) as ShoppingListUiItem;
    setShopping((current) => [...current, created]);
    closeDialog();
  };
  const toggleShoppingItem = async (item: ShoppingListUiItem) => {
    const response = await fetch(
      `/api/backend/shopping-list/${encodeURIComponent(item.id)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ checked: !item.checked }),
      },
    );
    if (!response.ok) return;
    const updated = (await response.json()) as ShoppingListUiItem;
    setShopping((current) =>
      current.map((candidate) =>
        candidate.id === updated.id ? updated : candidate,
      ),
    );
  };
  const removeShoppingItem = async (item: ShoppingListUiItem) => {
    const response = await fetch(
      `/api/backend/shopping-list/${encodeURIComponent(item.id)}`,
      { method: "DELETE" },
    );
    if (response.ok) {
      setShopping((current) =>
        current.filter((candidate) => candidate.id !== item.id),
      );
    }
  };
  const generateShoppingList = async () => {
    const response = await fetch("/api/backend/shopping-list/from-low-stock", {
      method: "POST",
    });
    if (!response.ok) {
      setSyncMessage("Low-stock items could not be added.");
      return;
    }
    const payload = (await response.json()) as {
      generated_count: number;
      items: ShoppingListUiItem[];
      limitation: string;
    };
    setShopping(payload.items);
    setSyncMessage(
      payload.generated_count
        ? `${payload.generated_count} low-stock item(s) added. ${payload.limitation}`
        : `No new low-stock items were added. ${payload.limitation}`,
    );
  };
  return (
    <div className="page fade-in">
      <section className="welcome">
        <div>
          <p className="eyebrow">SMART KITCHEN</p>
          <h1>Your pantry, thinking ahead.</h1>
          <p>Use what you have, waste less and cook with confidence.</p>
        </div>
        <button className="primary" onClick={openAddPantryDialog}>
          <Plus size={18} /> Add item
        </button>
      </section>
      <p className="sync-note">{syncMessage}</p>
      <div className="pantry-summary">
        <div>
          <PackageOpen />
          <span>
            <strong>{items.length}</strong> items tracked
          </span>
        </div>
        <div>
          <Clock3 />
          <span>
            <strong>
              {
                items.filter(
                  (item) =>
                    item.lowStockThreshold !== null &&
                    item.quantity <= item.lowStockThreshold,
                ).length
              }
            </strong>{" "}
            low stock
          </span>
        </div>
        <div>
          <ShoppingBasket />
          <span>
            <strong>{shopping.filter((item) => !item.checked).length}</strong>{" "}
            on your list
          </span>
        </div>
      </div>
      <div className="pantry-layout">
        <article className="card pantry-list">
          <div className="section-heading">
            <div>
              <h2>Pantry inventory</h2>
              <p>Sorted by what needs attention first.</p>
            </div>
            <button className="icon-btn">
              <Settings size={18} />
            </button>
          </div>
          {items.length === 0 && (
            <div className="pantry-empty">
              <PackageOpen size={28} aria-hidden="true" />
              <div>
                <strong>Your pantry is ready when you are.</strong>
                <p>
                  Add what you have at home to get private, practical
                  suggestions.
                </p>
              </div>
              <button className="primary" onClick={openAddPantryDialog}>
                <Plus size={17} /> Add pantry item
              </button>
            </div>
          )}
          {items.map((item, i) => (
            <div className="pantry-item" key={`${item.name}-${i}`}>
              <span className={`food-icon food-${i % 5}`}>
                {["🥣", "🥬", "🍞", "🥛", "🌾"][i % 5]}
              </span>
              <div>
                <strong>{item.name}</strong>
                <small>{item.amount}</small>
                {item.lowStockThreshold !== null && (
                  <small>
                    Alert at ≤ {item.lowStockThreshold} {item.unit}
                  </small>
                )}
                {item.itemRole === "LEFTOVER" && (
                  <small>User-marked leftover</small>
                )}
              </div>
              <span className={`expiry ${item.days < 3 ? "urgent" : ""}`}>
                {item.expiresOn ? `${item.days} days` : "No expiry"}
              </span>
              <button
                className="text-button"
                onClick={() => openEditPantryDialog(item)}
              >
                Edit
              </button>
              <button
                className="text-button"
                onClick={() => void removeItem(item)}
              >
                Use
              </button>
            </div>
          ))}
        </article>
        <aside>
          <article className="card recipe-card">
            <span className="soft-label">
              <Sparkles size={14} /> Cook with what you have
            </span>
            <div className="recipe-art">
              <span>
                {recipes[0]
                  ? `${Math.round(recipes[0].coverage * 100)}% matched`
                  : "No match yet"}
              </span>
              <strong>🥗</strong>
            </div>
            <h2>{recipes[0]?.title ?? "Add pantry items for a match"}</h2>
            <p>
              {recipes[0]
                ? recipes[0].missing_required.length
                  ? `Still needed: ${recipes[0].missing_required.join(", ")}.`
                  : `Available required ingredients: ${recipes[0].available_ingredients.join(", ")}.`
                : "Recipes are ranked only after your private pantry has synced."}
            </p>
            <div className="recipe-tags">
              {recipes[0]?.optional_available.map((ingredient) => (
                <span key={ingredient}>{ingredient}</span>
              ))}
              {recipes[0] && <span>Template v{recipes[0].source_version}</span>}
              {recipes[0] && (
                <span>
                  {recipes[0].preparation_complexity.band.toLowerCase()}{" "}
                  structure · {recipes[0].preparation_complexity.written_steps}{" "}
                  written steps
                </span>
              )}
            </div>
            {recipes[0] && (
              <small>{recipes[0].preparation_complexity.limitation}</small>
            )}
            {recipes[0]?.available_substitutions.map((substitution) => (
              <p
                key={`${substitution.missing_ingredient}:${substitution.available_alternative}`}
              >
                Available swap: {substitution.available_alternative} for{" "}
                {substitution.missing_ingredient} ({substitution.function}).{" "}
                {substitution.limitation}
              </p>
            ))}
            {recipes[0] && <small>{recipes[0].steps.join(" ")}</small>}
            {useSoon.length > 0 && (
              <div className="use-soon-recipes">
                <h3>Use-soon template matches</h3>
                {useSoon.map((suggestion) => (
                  <div key={suggestion.recipe.recipe_id}>
                    <strong>{suggestion.recipe.title}</strong>
                    <span>
                      Uses attention items:{" "}
                      {suggestion.attention_items
                        .map((item) => item.name)
                        .join(", ")}
                    </span>
                  </div>
                ))}
                <small>
                  Check packaging, storage, allergens and food condition. Never
                  use expired or spoiled food.
                </small>
              </div>
            )}
            {recipes.length > 1 && (
              <div className="recipe-comparison">
                <h3>Compare pantry coverage</h3>
                {recipes.map((recipe) => (
                  <div key={recipe.recipe_id}>
                    <span>{recipe.title}</span>
                    <strong>{Math.round(recipe.coverage * 100)}%</strong>
                  </div>
                ))}
                <small>
                  Coverage compares ingredient availability only, not nutrition
                  quality or medical suitability.
                </small>
              </div>
            )}
          </article>
          <article className="card shopping-card">
            <div className="section-heading">
              <div>
                <h2>Smart shopping list</h2>
                <p>Private checklist synced to your account</p>
              </div>
              <button
                className="icon-btn"
                aria-label="Add shopping item"
                onClick={openShoppingDialog}
              >
                <Plus size={18} />
              </button>
            </div>
            {shopping.length === 0 && (
              <p className="history-state">No checklist items yet.</p>
            )}
            <button
              className="text-button"
              onClick={() => void generateShoppingList()}
            >
              Add user-defined low-stock items
            </button>
            {shopping.map((item) => (
              <div className="shopping-item" key={item.id}>
                <input
                  type="checkbox"
                  checked={item.checked}
                  aria-label={`Mark ${item.name} as ${item.checked ? "not purchased" : "purchased"}`}
                  onChange={() => void toggleShoppingItem(item)}
                />
                <span>{item.name}</span>
                {item.source === "LOW_STOCK" && (
                  <small>Low-stock threshold</small>
                )}
                {item.source === "CUSTOM_RECIPE" && (
                  <small>
                    Recipe ingredient
                    {item.quantity != null && item.unit
                      ? ` · ${item.quantity} ${item.unit}`
                      : ""}
                  </small>
                )}
                <button
                  type="button"
                  className="text-button"
                  aria-label={`Remove ${item.name} from shopping list`}
                  onClick={() => void removeShoppingItem(item)}
                >
                  Remove
                </button>
              </div>
            ))}
          </article>
        </aside>
        <RecipeNutritionComparison />
      </div>
      <CustomRecipesPanel
        key={ownerId}
        ownerId={ownerId}
        onShoppingChanged={() => setShoppingRefresh((current) => current + 1)}
      />
      {dialog && (
        <div
          className="nutrilens-dialog-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeDialog();
          }}
        >
          <div
            ref={dialogRef}
            className="nutrilens-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="pantry-dialog-title"
          >
            <div className="dialog-heading">
              <div>
                <h2 id="pantry-dialog-title">
                  {dialog === "add-shopping"
                    ? "Add shopping item"
                    : dialog === "edit-pantry"
                      ? "Edit pantry item"
                      : "Add pantry item"}
                </h2>
                <p>
                  {dialog === "add-shopping"
                    ? "This private checklist item will sync to your account."
                    : "Only you can see and manage this pantry item."}
                </p>
              </div>
              <button
                type="button"
                className="icon-btn"
                aria-label="Close dialog"
                onClick={closeDialog}
                disabled={dialogBusy}
              >
                <X size={18} />
              </button>
            </div>
            {dialog === "add-shopping" ? (
              <form
                className="dialog-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void addShoppingItem();
                }}
              >
                <label>
                  Item name
                  <input
                    maxLength={200}
                    value={shoppingName}
                    onChange={(event) => setShoppingName(event.target.value)}
                    placeholder="e.g. Oats"
                    disabled={dialogBusy}
                  />
                </label>
                {dialogError && (
                  <p className="dialog-error" role="alert">
                    {dialogError}
                  </p>
                )}
                <div className="dialog-actions">
                  <button
                    type="button"
                    onClick={closeDialog}
                    disabled={dialogBusy}
                  >
                    Cancel
                  </button>
                  <button
                    className="primary"
                    type="submit"
                    disabled={dialogBusy}
                  >
                    {dialogBusy ? "Saving…" : "Add item"}
                  </button>
                </div>
              </form>
            ) : (
              <form
                className="dialog-form pantry-dialog-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  void savePantryItem();
                }}
              >
                {dialog === "add-pantry" && (
                  <label>
                    Item name
                    <input
                      maxLength={200}
                      value={pantryDraft.name}
                      onChange={(event) =>
                        setPantryDraft((current) => ({
                          ...current,
                          name: event.target.value,
                        }))
                      }
                      placeholder="e.g. Chickpeas"
                      disabled={dialogBusy}
                    />
                  </label>
                )}
                <label>
                  Quantity
                  <input
                    type="number"
                    min="0.01"
                    max="100000"
                    step="any"
                    value={pantryDraft.quantity}
                    onChange={(event) =>
                      setPantryDraft((current) => ({
                        ...current,
                        quantity: event.target.value,
                      }))
                    }
                    disabled={dialogBusy}
                  />
                </label>
                <label>
                  Low-stock alert threshold <small>Optional</small>
                  <input
                    type="number"
                    min="0.01"
                    max="100000"
                    step="any"
                    value={pantryDraft.lowStockThreshold}
                    onChange={(event) =>
                      setPantryDraft((current) => ({
                        ...current,
                        lowStockThreshold: event.target.value,
                      }))
                    }
                    placeholder="Leave blank to disable"
                    disabled={dialogBusy}
                  />
                </label>
                <label>
                  Item type
                  <select
                    value={pantryDraft.itemRole}
                    onChange={(event) =>
                      setPantryDraft((current) => ({
                        ...current,
                        itemRole: event.target.value as
                          "INGREDIENT" | "LEFTOVER",
                      }))
                    }
                    disabled={dialogBusy}
                  >
                    <option value="INGREDIENT">Ingredient</option>
                    <option value="LEFTOVER">Prepared leftover</option>
                  </select>
                </label>
                <label>
                  Expiry date <small>Optional</small>
                  <input
                    type="date"
                    value={pantryDraft.expiresOn}
                    onChange={(event) =>
                      setPantryDraft((current) => ({
                        ...current,
                        expiresOn: event.target.value,
                      }))
                    }
                    disabled={dialogBusy}
                  />
                </label>
                {dialogError && (
                  <p className="dialog-error" role="alert">
                    {dialogError}
                  </p>
                )}
                <div className="dialog-actions">
                  <button
                    type="button"
                    onClick={closeDialog}
                    disabled={dialogBusy}
                  >
                    Cancel
                  </button>
                  <button
                    className="primary"
                    type="submit"
                    disabled={dialogBusy}
                  >
                    {dialogBusy
                      ? "Saving…"
                      : dialog === "edit-pantry"
                        ? "Save changes"
                        : "Add item"}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function AssistantView({
  scanId,
  user,
  initialQuestion,
}: {
  scanId: string | null;
  user: AuthenticatedUser;
  initialQuestion: string;
}) {
  type Citation = {
    evidence_id: string;
    title: string;
    authority: string;
    url: string;
  };
  type Message = { role: "ai" | "user"; text: string; citations?: Citation[] };
  type BrowserSpeechRecognition = {
    continuous: boolean;
    interimResults: boolean;
    lang: string;
    start: () => void;
    stop: () => void;
    onresult:
      | ((event: {
          results: ArrayLike<ArrayLike<{ transcript: string }>>;
        }) => void)
      | null;
    onerror: ((event: { error: string }) => void) | null;
    onend: (() => void) | null;
  };
  type BrowserSpeechRecognitionConstructor = new () => BrowserSpeechRecognition;
  const firstName = user.name.trim().split(/\s+/)[0] || "";
  const displayName = firstName.includes("@") ? "there" : firstName;
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "ai",
      text: `Hi ${displayName} — I’m Nutri, your food intelligence assistant. Ask me about a scanned product, an ingredient, or what to eat next.`,
    },
  ]);
  const [value, setValue] = useState(initialQuestion);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [listening, setListening] = useState(false);
  const [readAloud, setReadAloud] = useState(false);
  const [voiceNotice, setVoiceNotice] = useState("");
  const recognitionRef = useRef<BrowserSpeechRecognition | null>(null);

  useEffect(() => {
    return () => {
      recognitionRef.current?.stop();
      window.speechSynthesis?.cancel();
    };
  }, []);

  const startListening = () => {
    const voiceWindow = window as typeof window & {
      SpeechRecognition?: BrowserSpeechRecognitionConstructor;
      webkitSpeechRecognition?: BrowserSpeechRecognitionConstructor;
    };
    const Recognition =
      voiceWindow.SpeechRecognition ?? voiceWindow.webkitSpeechRecognition;
    if (!Recognition) {
      setVoiceNotice(
        "Voice input is unavailable in this browser. You can keep typing.",
      );
      return;
    }
    window.speechSynthesis?.cancel();
    const recognition = new Recognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = document.documentElement.lang || "en-IN";
    recognition.onresult = (event) => {
      const transcript = event.results[0]?.[0]?.transcript?.trim();
      if (transcript) setValue(transcript);
    };
    recognition.onerror = (event) => {
      setVoiceNotice(
        event.error === "not-allowed"
          ? "Microphone access was not granted. You can keep typing."
          : "Voice input stopped before a question was captured.",
      );
    };
    recognition.onend = () => setListening(false);
    recognitionRef.current = recognition;
    setVoiceNotice(
      "Listening on this device. Only the transcript is sent when you choose Ask.",
    );
    setListening(true);
    recognition.start();
  };

  const stopListening = () => recognitionRef.current?.stop();

  const speak = (text: string) => {
    if (!("speechSynthesis" in window)) {
      setVoiceNotice("Read aloud is unavailable in this browser.");
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = document.documentElement.lang || "en-IN";
    window.speechSynthesis.speak(utterance);
  };
  const send = async (text = value) => {
    if (!text.trim()) return;
    setMessages((current) => [...current, { role: "user", text }]);
    setValue("");
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/backend/assistant/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, scan_id: scanId }),
      });
      const payload = (await response.json()) as {
        answer?: string;
        citations?: Citation[];
        remaining_today?: number;
        detail?: string;
        error?: string;
      };
      if (!response.ok) {
        throw new Error(
          response.status === 401
            ? "Sign in to use your private NutriLens assistant."
            : (payload.detail ??
                payload.error ??
                "Nutri could not answer right now."),
        );
      }
      const answer = payload.answer ?? "Evidence is unavailable.";
      setMessages((current) => [
        ...current,
        {
          role: "ai",
          text: `${answer} ${payload.remaining_today ?? 0} requests remain today.`,
          citations: payload.citations,
        },
      ]);
      if (readAloud) speak(answer);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Nutri could not answer right now.",
      );
    } finally {
      setLoading(false);
    }
  };
  return (
    <div className="assistant-page fade-in">
      <div className="assistant-head">
        <div className="nutri-avatar">
          <Leaf />
        </div>
        <div>
          <h2>Ask Nutri</h2>
          <span>
            <i /> AI nutrition assistant
          </span>
        </div>
        <button
          className={`icon-btn ${readAloud ? "active" : ""}`}
          aria-pressed={readAloud}
          aria-label="Read assistant answers aloud"
          onClick={() => {
            window.speechSynthesis?.cancel();
            setReadAloud(!readAloud);
            setVoiceNotice(
              readAloud
                ? "Automatic read aloud is off."
                : "Automatic read aloud is on for this session.",
            );
          }}
        >
          <Volume2 />
        </button>
      </div>
      <div className="chat-area">
        <div className="chat-intro">
          <span className="soft-label">
            <Sparkles size={14} /> Personal, explainable answers
          </span>
          <h1>What would you like to know?</h1>
          <p>
            I use your goals and NutriLens food intelligence to keep answers
            relevant and clear.
          </p>
          <div className="prompt-grid">
            {[
              "Is my breakfast balanced?",
              "Why is palm oil flagged?",
              "Plan a high-protein dinner",
              "Compare my last two scans",
            ].map((q) => (
              <button key={q} disabled={loading} onClick={() => void send(q)}>
                {q}
                <ArrowRight size={15} />
              </button>
            ))}
          </div>
        </div>
        <div className="messages">
          {messages.map((m, i) => (
            <div className={`message ${m.role}`} key={i}>
              {m.role === "ai" && (
                <div className="nutri-avatar">
                  <Leaf />
                </div>
              )}
              <div className="message-body">
                <p>{m.text}</p>
                {m.citations && m.citations.length > 0 && (
                  <div
                    className="assistant-citations"
                    aria-label="Evidence sources"
                  >
                    {m.citations.map((citation) => (
                      <a
                        href={citation.url}
                        key={citation.evidence_id}
                        rel="noreferrer"
                        target="_blank"
                      >
                        {citation.authority}: {citation.title}
                      </a>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
      {error && (
        <p className="assistant-error" role="alert">
          {error}
        </p>
      )}
      {voiceNotice && (
        <p className="voice-notice" aria-live="polite">
          {voiceNotice}
        </p>
      )}
      <div className="composer">
        <div>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void send()}
            placeholder="Ask about food, ingredients or your goals…"
            disabled={loading}
          />
          <button
            className={`voice ${listening ? "active" : ""}`}
            disabled={loading}
            aria-label={listening ? "Stop listening" : "Dictate question"}
            aria-pressed={listening}
            onClick={listening ? stopListening : startListening}
          >
            {listening ? <X /> : <Mic />}
          </button>
          <button
            className="send"
            disabled={loading}
            onClick={() => void send()}
          >
            <ArrowRight />
          </button>
        </div>
        <small>
          NutriLens provides wellness guidance, not medical diagnosis.
        </small>
      </div>
    </div>
  );
}

type ScanHistoryItem = {
  scan_id: string;
  created_at: string;
  input_kind: string;
  status: string;
  product_name: string | null;
  brand: string | null;
  confidence: number | null;
};

function ScanHistoryView({ onOpen }: { onOpen: (scan: R3ScanResult) => void }) {
  const [items, setItems] = useState<ScanHistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void fetch("/api/backend/scan/history?limit=50")
      .then(async (response) => {
        const payload = (await response.json()) as
          ScanHistoryItem[] | { detail?: string };
        if (!response.ok) {
          throw new Error(
            response.status === 401
              ? "Sign in to view your private scan history."
              : "Scan history is unavailable right now.",
          );
        }
        if (active) setItems(payload as ScanHistoryItem[]);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(
            reason instanceof Error
              ? reason.message
              : "Scan history is unavailable.",
          );
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const openScan = async (scanId: string) => {
    setError("");
    const response = await fetch(
      `/api/backend/scan/${encodeURIComponent(scanId)}`,
    );
    if (!response.ok) {
      setError("This scan could not be reopened. It may have been deleted.");
      return;
    }
    onOpen((await response.json()) as R3ScanResult);
  };

  return (
    <div className="page narrow fade-in">
      <div className="history-heading">
        <div>
          <p className="eyebrow">Private library</p>
          <h1>Scan history</h1>
          <p>
            Compact summaries from your account. Original image bytes are never
            retained.
          </p>
        </div>
        <span>{items.length} saved scans</span>
      </div>
      {loading && <p className="history-state">Loading your scans…</p>}
      {error && (
        <p className="assistant-error" role="alert">
          {error}
        </p>
      )}
      {!loading && !error && items.length === 0 && (
        <div className="card history-state">
          No saved scans yet. Scan a label to begin.
        </div>
      )}
      <div className="history-list">
        {items.map((item) => (
          <article className="card history-item" key={item.scan_id}>
            <div className="history-icon">
              <ScanLine />
            </div>
            <div>
              <strong>{item.product_name ?? "Unidentified food scan"}</strong>
              <span>
                {[item.brand, item.input_kind.replaceAll("_", " ")]
                  .filter(Boolean)
                  .join(" · ")}
              </span>
              <small>{new Date(item.created_at).toLocaleString()}</small>
            </div>
            <div className="history-meta">
              <span>
                {item.confidence == null
                  ? "Unknown confidence"
                  : `${Math.round(item.confidence * 100)}% confidence`}
              </span>
              <button
                className="outline-button"
                onClick={() => void openScan(item.scan_id)}
              >
                Open <ArrowRight size={14} />
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

type FavoriteItem = {
  scan_id: string;
  product_name: string | null;
  brand: string | null;
  saved_at: string;
};

type SearchItem = {
  kind: "SCAN" | "INGREDIENT" | "ADDITIVE" | "ALLERGEN";
  id: string;
  title: string;
  subtitle: string;
  score: number;
};

function SearchView({
  query,
  onOpen,
}: {
  query: string;
  onOpen: (scan: R3ScanResult) => void;
}) {
  const [items, setItems] = useState<SearchItem[]>([]);
  const [message, setMessage] = useState("Searching your private library…");
  const [limitation, setLimitation] = useState("");
  useEffect(() => {
    let active = true;
    void fetch(`/api/backend/search?q=${encodeURIComponent(query)}`, {
      cache: "no-store",
    })
      .then(async (response) => {
        const payload = (await response.json()) as {
          items?: SearchItem[];
          limitation?: string;
          detail?: string;
        };
        if (!response.ok)
          throw new Error(payload.detail ?? "Search is unavailable.");
        return payload;
      })
      .then((payload) => {
        if (active) {
          setItems(payload.items ?? []);
          setLimitation(payload.limitation ?? "");
          setMessage(payload.items?.length ? "" : "No matching records found.");
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setMessage(
            reason instanceof Error ? reason.message : "Search is unavailable.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [query]);
  const openScan = async (scanId: string) => {
    const response = await fetch(
      `/api/backend/scan/${encodeURIComponent(scanId)}`,
    );
    if (!response.ok) {
      setMessage("This scan could not be reopened.");
      return;
    }
    onOpen((await response.json()) as R3ScanResult);
  };
  return (
    <div className="page narrow fade-in">
      <div className="history-heading">
        <div>
          <p className="eyebrow">Bounded universal search</p>
          <h1>Results for “{query}”</h1>
          <p>{limitation}</p>
        </div>
        <span>{items.length} matches</span>
      </div>
      {message && (
        <p className="history-state" role="status">
          {message}
        </p>
      )}
      <div className="history-list">
        {items.map((item) => (
          <article
            className="card history-item"
            key={`${item.kind}:${item.id}`}
          >
            <div className="history-icon">
              {item.kind === "SCAN" ? <ScanLine /> : <Search />}
            </div>
            <div>
              <strong>{item.title}</strong>
              <span>{item.subtitle}</span>
              <small>
                {item.kind.toLowerCase()} · {Math.round(item.score * 100)}%
                lexical match
              </small>
            </div>
            {item.kind === "SCAN" && (
              <button
                className="outline-button"
                onClick={() => void openScan(item.id)}
              >
                Open <ArrowRight size={14} />
              </button>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}

function FavoritesView({ onOpen }: { onOpen: (scan: R3ScanResult) => void }) {
  const [items, setItems] = useState<FavoriteItem[]>([]);
  const [message, setMessage] = useState("Loading saved foods…");
  useEffect(() => {
    let active = true;
    void fetch("/api/backend/favorites?limit=100", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Saved foods are unavailable.");
        return (await response.json()) as FavoriteItem[];
      })
      .then((payload) => {
        if (active) {
          setItems(payload);
          setMessage(payload.length ? "" : "No saved foods yet.");
        }
      })
      .catch((reason: unknown) => {
        if (active) {
          setMessage(
            reason instanceof Error
              ? reason.message
              : "Saved foods are unavailable.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);
  const open = async (scanId: string) => {
    const response = await fetch(
      `/api/backend/scan/${encodeURIComponent(scanId)}`,
    );
    if (!response.ok) {
      setMessage("This saved scan no longer exists.");
      return;
    }
    onOpen((await response.json()) as R3ScanResult);
  };
  const remove = async (scanId: string) => {
    const response = await fetch(
      `/api/backend/favorites/${encodeURIComponent(scanId)}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      setMessage("Saved food could not be removed.");
      return;
    }
    setItems((current) => current.filter((item) => item.scan_id !== scanId));
    setMessage("Removed from saved foods.");
  };
  return (
    <div className="page narrow fade-in">
      <div className="history-heading">
        <div>
          <p className="eyebrow">Private library</p>
          <h1>Saved foods</h1>
          <p>Owner-scoped scan references saved to your account.</p>
        </div>
        <span>{items.length} saved foods</span>
      </div>
      {message && (
        <p className="history-state" role="status">
          {message}
        </p>
      )}
      <div className="history-list">
        {items.map((item) => (
          <article className="card history-item" key={item.scan_id}>
            <div className="history-icon">
              <HeartPulse />
            </div>
            <div>
              <strong>{item.product_name ?? "Unidentified food scan"}</strong>
              <span>{item.brand ?? "Brand not resolved"}</span>
              <small>Saved {new Date(item.saved_at).toLocaleString()}</small>
            </div>
            <div className="history-meta">
              <button
                className="outline-button"
                onClick={() => void open(item.scan_id)}
              >
                Open <ArrowRight size={14} />
              </button>
              <button
                className="text-button"
                onClick={() => void remove(item.scan_id)}
              >
                Remove
              </button>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}

type ComparisonResult = {
  candidates: Array<{
    scan_id: string;
    product_name: string;
    rank: number;
    signal_burden: number;
    signal_counts: Record<string, number>;
    evidence: string[];
    limitations: string[];
  }>;
  recommended_scan_id: string | null;
  profile_used: boolean;
  method: string;
  disclaimer: string;
};

function CompareView() {
  const [history, setHistory] = useState<ScanHistoryItem[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<ComparisonResult | null>(null);
  const [message, setMessage] = useState("Loading your private scan history…");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    void fetch("/api/backend/scan/history?limit=50", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(
            response.status === 401
              ? "Sign in to compare your scans."
              : "Scan history is unavailable right now.",
          );
        }
        return (await response.json()) as ScanHistoryItem[];
      })
      .then((payload) => {
        if (active) {
          setHistory(payload);
          setMessage(
            payload.length < 2 ? "At least two saved scans are required." : "",
          );
        }
      })
      .catch((reason: unknown) => {
        if (active)
          setMessage(
            reason instanceof Error
              ? reason.message
              : "Comparison unavailable.",
          );
      });
    return () => {
      active = false;
    };
  }, []);

  const toggle = (scanId: string) => {
    setResult(null);
    setSelected((current) =>
      current.includes(scanId)
        ? current.filter((candidate) => candidate !== scanId)
        : current.length < 5
          ? [...current, scanId]
          : current,
    );
  };

  const compare = async () => {
    if (selected.length < 2) return;
    setBusy(true);
    setMessage("");
    const response = await fetch("/api/backend/recommendations/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scan_ids: selected }),
    });
    if (response.ok) {
      setResult((await response.json()) as ComparisonResult);
    } else {
      setMessage("The selected scans could not be compared.");
    }
    setBusy(false);
  };

  return (
    <div className="page narrow fade-in">
      <section className="welcome">
        <div>
          <p className="eyebrow">EXPLAINABLE COMPARISON</p>
          <h1>Compare saved scans.</h1>
          <p>
            Select two to five scans. Ranking uses observed label signals—not a
            health score.
          </p>
        </div>
        <button
          className="primary"
          disabled={busy || selected.length < 2}
          onClick={() => void compare()}
        >
          <Columns2 size={16} />{" "}
          {busy ? "Comparing…" : `Compare ${selected.length}`}
        </button>
      </section>
      {message && (
        <p className="assistant-error" role="status">
          {message}
        </p>
      )}
      <div className="compare-selector">
        {history.map((item) => (
          <label className="card" key={item.scan_id}>
            <input
              checked={selected.includes(item.scan_id)}
              disabled={
                !selected.includes(item.scan_id) && selected.length >= 5
              }
              type="checkbox"
              onChange={() => toggle(item.scan_id)}
            />
            <span>
              <strong>{item.product_name ?? "Unidentified food scan"}</strong>
              <small>{new Date(item.created_at).toLocaleString()}</small>
            </span>
          </label>
        ))}
      </div>
      {result && (
        <section className="compare-results">
          <div className="compare-note">
            <ShieldCheck size={17} />
            <span>
              {result.disclaimer}{" "}
              {result.profile_used
                ? "Consented preferences were applied."
                : "Saved preferences were not used."}
            </span>
          </div>
          {result.candidates.map((candidate) => (
            <article className="card compare-result" key={candidate.scan_id}>
              <span className="compare-rank">#{candidate.rank}</span>
              <div>
                <h2>{candidate.product_name}</h2>
                <p>
                  {candidate.evidence.join(" · ") ||
                    "No priority signals were observed."}
                </p>
                {candidate.limitations.map((limitation) => (
                  <small key={limitation}>{limitation}</small>
                ))}
              </div>
              <div>
                <strong>{candidate.signal_burden}</strong>
                <span>observed burden</span>
                {candidate.scan_id === result.recommended_scan_id && (
                  <em>Lower observed burden</em>
                )}
              </div>
            </article>
          ))}
        </section>
      )}
    </div>
  );
}

export function NutriLensApp() {
  const router = useRouter();
  const [view, setView] = useState<View>("home");
  const [scanResult, setScanResult] = useState<R3ScanResult | null>(null);
  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [menu, setMenu] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  useEffect(() => {
    const restore = window.setTimeout(() => {
      if (window.sessionStorage.getItem(ACTIVE_SCAN_JOB_STORAGE_KEY)) {
        setView("scan");
      }
    }, 0);
    return () => window.clearTimeout(restore);
  }, []);
  useEffect(() => {
    let active = true;
    void fetch("/api/backend/auth/me", { cache: "no-store" })
      .then(async (response) => {
        if (response.status === 401) {
          router.replace("/login?next=%2Fdashboard");
          return null;
        }
        if (!response.ok) throw new Error("Account session is unavailable.");
        return (await response.json()) as AuthenticatedUser;
      })
      .then((account) => {
        if (active) setUser(account);
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setAuthChecked(true);
      });
    return () => {
      active = false;
    };
  }, [router]);
  const showScan = (result: R3ScanResult) => {
    setScanResult(result);
    setView("result");
    window.scrollTo({ top: 0, behavior: "smooth" });
  };
  const showSearch = (query: string) => {
    setSearchQuery(query);
    setView("search");
  };
  if (!authChecked || !user) {
    return (
      <main className="login-page" id="main-content" tabIndex={-1}>
        <p>Checking your secure NutriLens session…</p>
      </main>
    );
  }
  return (
    <div className="app-shell">
      <SessionKeepalive />
      <Sidebar
        view={view}
        setView={setView}
        open={menu}
        close={() => setMenu(false)}
        user={user}
      />
      <main className="main" id="main-content" tabIndex={-1}>
        <Header
          menuOpen={menu}
          onMenu={() => setMenu(true)}
          onSearch={showSearch}
          user={user}
        />
        {view === "home" && <LiveHomeView setView={setView} user={user} />}{" "}
        {view === "scan" && <ScanView onAnalyzed={showScan} />}{" "}
        {view === "history" && <ScanHistoryView onOpen={showScan} />}{" "}
        {view === "favorites" && <FavoritesView onOpen={showScan} />}{" "}
        {view === "search" && searchQuery && (
          <SearchView query={searchQuery} onOpen={showScan} />
        )}{" "}
        {view === "diary" && <DiaryView ownerId={user.id} />}{" "}
        {view === "compare" && <CompareView />}{" "}
        {view === "result" && scanResult && (
          <R3ResultView
            initial={scanResult}
            goBack={() => setView("scan")}
            onAskNutri={(question = "") => {
              setAssistantQuestion(question);
              setView("assistant");
            }}
          />
        )}{" "}
        {view === "analytics" && <AnalyticsView />}{" "}
        {view === "pantry" && <PantryView key={user.id} ownerId={user.id} />}{" "}
        {view === "assistant" && (
          <AssistantView
            scanId={scanResult?.scan_id ?? null}
            user={user}
            initialQuestion={assistantQuestion}
          />
        )}
      </main>
    </div>
  );
}
