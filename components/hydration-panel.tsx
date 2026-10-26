"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Droplets } from "lucide-react";
import styles from "./hydration-panel.module.css";

type Entry = {
  id: string;
  amount_ml: number;
  consumed_at: string;
  source: "USER_ENTERED";
};
type DaySummary = {
  day: string;
  timezone_offset_minutes: number;
  target_ml: number | null;
  total_ml: number;
  remaining_ml: number | null;
  entries: Entry[];
};
type Mutation = {
  path: string;
  method: "POST" | "PUT" | "DELETE";
  body?: string;
};

function localDay(date = new Date()) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function localTime(date: Date) {
  return `${localDay(date)}T${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function volume(amount: number) {
  return amount >= 1000
    ? `${Number((amount / 1000).toFixed(3))} L`
    : `${amount} ml`;
}

function validAmount(value: string, min: number, max: number) {
  const number = Number(value);
  return (
    value.trim() !== "" &&
    Number.isInteger(number) &&
    number >= min &&
    number <= max
  );
}

function dayQuery(day: string) {
  const [year, month, date] = day.split("-").map(Number);
  return new URLSearchParams({
    day,
    timezone_offset_minutes: String(
      -new Date(year, month - 1, date).getTimezoneOffset(),
    ),
    next_day_timezone_offset_minutes: String(
      -new Date(year, month - 1, date + 1).getTimezoneOffset(),
    ),
  });
}

function pendingKey(ownerId: string) {
  return `nutrilens.hydration.pending.v1:${encodeURIComponent(ownerId)}`;
}

function readPendingPost(ownerId: string): Mutation | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(pendingKey(ownerId));
    if (!raw || raw.length > 1024) return null;
    const stored = JSON.parse(raw) as { version?: unknown; body?: unknown };
    if (stored.version !== 1 || typeof stored.body !== "string") return null;
    const body = JSON.parse(stored.body) as Record<string, unknown>;
    if (
      typeof body.id !== "string" ||
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        body.id,
      ) ||
      typeof body.amount_ml !== "number" ||
      !Number.isInteger(body.amount_ml) ||
      body.amount_ml < 1 ||
      body.amount_ml > 5000 ||
      typeof body.consumed_at !== "string" ||
      !/(Z|[+-]\d{2}:\d{2})$/.test(body.consumed_at) ||
      !Number.isFinite(Date.parse(body.consumed_at)) ||
      Object.keys(body).some(
        (key) => !["id", "amount_ml", "consumed_at"].includes(key),
      )
    )
      return null;
    return { path: "/entries", method: "POST", body: stored.body };
  } catch {
    return null;
  }
}

function clearPendingPost(ownerId: string, mutation: Mutation) {
  if (mutation.method !== "POST") return;
  try {
    if (readPendingPost(ownerId)?.body === mutation.body)
      sessionStorage.removeItem(pendingKey(ownerId));
  } catch {
    // A retained reminder is safe: retry always reuses the original server ID.
  }
}

export function HydrationToday({ onOpen }: { onOpen: () => void }) {
  const [summary, setSummary] = useState<DaySummary | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    let active = true;
    void fetch(`/api/backend/hydration?${dayQuery(localDay())}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(20_000),
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("Water summary unavailable");
        return (await response.json()) as DaySummary;
      })
      .then((payload) => {
        if (active) setSummary(payload);
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, []);
  return (
    <section className={`card ${styles.panel}`} aria-label="Today's water">
      <div className={styles.heading}>
        <div>
          <p className="eyebrow">
            <Droplets size={15} aria-hidden="true" /> HYDRATION
          </p>
          <h2>Today&apos;s water</h2>
        </div>
        <button className="primary" onClick={onOpen}>
          Open water log
        </button>
      </div>
      {summary ? (
        <p>
          <strong>{volume(summary.total_ml)}</strong> recorded ·{" "}
          {summary.target_ml === null
            ? "No target set"
            : `${volume(summary.target_ml)} daily target · ${volume(summary.remaining_ml ?? 0)} remaining`}
        </p>
      ) : (
        <p role="status">
          {error
            ? "Water summary unavailable. Open your water log to retry."
            : "Loading your water summary…"}
        </p>
      )}
    </section>
  );
}

export function HydrationPanel({ ownerId }: { ownerId: string }) {
  const [recovered] = useState(() => readPendingPost(ownerId));
  const [day, setDay] = useState(() =>
    recovered?.body
      ? localDay(
          new Date(
            (JSON.parse(recovered.body) as { consumed_at: string }).consumed_at,
          ),
        )
      : localDay(),
  );
  const [summary, setSummary] = useState<DaySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [amount, setAmount] = useState("");
  const [target, setTarget] = useState("");
  const [editing, setEditing] = useState<Entry | null>(null);
  const [editAmount, setEditAmount] = useState("");
  const [editTime, setEditTime] = useState("");
  const [retry, setRetry] = useState<Mutation | null>(recovered);
  const lock = useRef(false);
  const alive = useRef(false);
  const requestNumber = useRef(0);

  const refresh = useCallback(async () => {
    const number = ++requestNumber.current;
    try {
      const query = dayQuery(day);
      const response = await fetch(`/api/backend/hydration?${query}`, {
        cache: "no-store",
        signal: AbortSignal.timeout(20_000),
      });
      if (!response.ok) {
        throw new Error(
          response.status === 401
            ? "Your session expired. Sign in again to view your water log."
            : "Your water log could not be loaded. Please retry.",
        );
      }
      const next = (await response.json()) as DaySummary;
      if (alive.current && number === requestNumber.current) {
        setSummary(next);
        setTarget(next.target_ml === null ? "" : String(next.target_ml));
      }
    } finally {
      if (alive.current && number === requestNumber.current) setLoading(false);
    }
  }, [day]);

  useEffect(() => {
    let active = true;
    alive.current = true;
    void refresh().catch((reason: unknown) => {
      if (active)
        setError(
          reason instanceof Error
            ? reason.message
            : "Your water log could not be loaded.",
        );
    });
    return () => {
      active = false;
      alive.current = false;
      requestNumber.current += 1;
    };
  }, [refresh]);

  const mutate = async (mutation: Mutation) => {
    if (lock.current) return;
    lock.current = true;
    setSaving(true);
    setError("");
    setNotice("");
    let confirmed = false;
    try {
      if (mutation.method === "POST") {
        try {
          sessionStorage.setItem(
            pendingKey(ownerId),
            JSON.stringify({ version: 1, body: mutation.body }),
          );
        } catch {
          throw new Error(
            "Browser storage is unavailable. Enable storage for this site before retrying so an interrupted save can be recovered.",
          );
        }
      }
      const response = await fetch(`/api/backend/hydration${mutation.path}`, {
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
      if (definitive) clearPendingPost(ownerId, mutation);
      if (!alive.current) return;
      // A repeated delete is already complete when the entry is absent.
      if (
        !response.ok &&
        !(mutation.method === "DELETE" && response.status === 404)
      ) {
        if (
          response.status < 500 &&
          response.status !== 408 &&
          response.status !== 429
        ) {
          setRetry(null);
          confirmed = true;
        }
        throw new Error(
          response.status === 401
            ? "Your session expired. Sign in again before saving."
            : response.status === 409
              ? "This entry was changed or deleted. Refresh your water log before adding another."
              : response.status === 429
                ? "Please wait a moment, then retry this change."
                : "Your change could not be confirmed. Please retry.",
        );
      }
      confirmed = true;
      setRetry(null);
      setEditing(null);
      setAmount("");
      setNotice("Water log saved.");
      try {
        await refresh();
      } catch {
        if (alive.current)
          setError(
            "Your change was saved, but the latest water log could not be loaded. Refresh the log to see it.",
          );
      }
    } catch (reason) {
      if (alive.current) {
        if (!confirmed) setRetry(mutation);
        setError(
          reason instanceof Error &&
            !(reason instanceof TypeError) &&
            !(reason instanceof DOMException)
            ? reason.message
            : "Your change could not be confirmed. Please retry.",
        );
      }
    } finally {
      lock.current = false;
      if (alive.current) setSaving(false);
    }
  };

  const add = (amountMl: number) => {
    if (lock.current || retry) return;
    const now = new Date();
    const consumed = day === localDay(now) ? now : new Date(`${day}T12:00:00`);
    void mutate({
      path: "/entries",
      method: "POST",
      body: JSON.stringify({
        id: crypto.randomUUID(),
        amount_ml: amountMl,
        consumed_at: consumed.toISOString(),
      }),
    });
  };
  const busy = loading || saving;
  const disabled = busy || retry !== null || summary?.day !== day;

  return (
    <section
      className={`card ${styles.panel}`}
      aria-label="Water log"
      aria-busy={busy}
    >
      <div className={styles.heading}>
        <div>
          <p className="eyebrow">
            <Droplets size={15} aria-hidden="true" /> HYDRATION
          </p>
          <h2>Your water log</h2>
          <p>Record what you drink and choose your own daily target.</p>
        </div>
        <label>
          Water log date
          <input
            type="date"
            value={day}
            min="2000-01-01"
            max={localDay()}
            disabled={busy || retry !== null}
            onChange={(event) => {
              if (!event.target.value || event.target.value === day) return;
              setLoading(true);
              setDay(event.target.value);
              setError("");
              setNotice("");
              setEditing(null);
            }}
          />
        </label>
      </div>
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {loading && <p role="status">Loading your water log…</p>}
      {retry && (
        <div className={styles.retry}>
          <p>
            A change is awaiting confirmation. Retry sends the same change
            without adding a second entry.
          </p>
          <button
            className="primary"
            disabled={busy}
            onClick={() => void mutate(retry)}
          >
            Retry pending change
          </button>
        </div>
      )}
      {summary?.day === day && (
        <>
          <div className={styles.summary}>
            <div>
              <strong>{volume(summary.total_ml)}</strong>
              <span>Recorded for this day</span>
            </div>
            <div>
              <strong>
                {summary.target_ml === null
                  ? "No target set"
                  : volume(summary.target_ml)}
              </strong>
              <span>Your current daily target</span>
            </div>
            {summary.remaining_ml !== null && (
              <div>
                <strong>{volume(summary.remaining_ml)}</strong>
                <span>Remaining to your target</span>
              </div>
            )}
          </div>
          {summary.target_ml !== null && (
            <progress
              aria-label="Water target progress"
              value={Math.min(summary.total_ml, summary.target_ml)}
              max={summary.target_ml}
            />
          )}
          <fieldset disabled={disabled} className={styles.controls}>
            <legend>Add water</legend>
            <div className={styles.row}>
              <button className="outline-button" onClick={() => add(250)}>
                +250 ml
              </button>
              <button className="outline-button" onClick={() => add(500)}>
                +500 ml
              </button>
            </div>
            <form
              className={styles.row}
              onSubmit={(event) => {
                event.preventDefault();
                if (validAmount(amount, 1, 5000)) add(Number(amount));
              }}
            >
              <label>
                Custom amount (ml)
                <input
                  type="number"
                  min="1"
                  max="5000"
                  step="1"
                  value={amount}
                  onChange={(event) => setAmount(event.target.value)}
                  required
                />
              </label>
              <button className="primary" type="submit">
                Add water
              </button>
            </form>
            {day !== localDay() && (
              <p>
                Past-day entries are recorded at 12:00 local time. Use Edit to
                set the actual time.
              </p>
            )}
          </fieldset>
          <details className={styles.target}>
            <summary>Set or change your daily target</summary>
            <p>This is a target you choose, not a recommended intake.</p>
            <form
              className={styles.row}
              onSubmit={(event) => {
                event.preventDefault();
                if (validAmount(target, 100, 10000))
                  void mutate({
                    path: "/target",
                    method: "PUT",
                    body: JSON.stringify({ target_ml: Number(target) }),
                  });
              }}
            >
              <label>
                Daily water target (ml)
                <input
                  type="number"
                  min="100"
                  max="10000"
                  step="1"
                  value={target}
                  disabled={disabled}
                  onChange={(event) => setTarget(event.target.value)}
                  required
                />
              </label>
              <button type="submit" className="primary" disabled={disabled}>
                Save target
              </button>
              <button
                type="button"
                className="outline-button"
                disabled={disabled || summary.target_ml === null}
                onClick={() =>
                  void mutate({
                    path: "/target",
                    method: "PUT",
                    body: JSON.stringify({ target_ml: null }),
                  })
                }
              >
                Clear target
              </button>
            </form>
          </details>
          <h3>Entries</h3>
          {summary.entries.length === 0 ? (
            <p>No water recorded for this day.</p>
          ) : (
            <ul className={styles.entries}>
              {summary.entries.map((entry) => (
                <li key={entry.id}>
                  {editing?.id === entry.id ? (
                    <form
                      className={styles.row}
                      onSubmit={(event) => {
                        event.preventDefault();
                        const timestamp = new Date(editTime);
                        if (
                          validAmount(editAmount, 1, 5000) &&
                          Number.isFinite(timestamp.getTime())
                        )
                          void mutate({
                            path: `/entries/${encodeURIComponent(entry.id)}`,
                            method: "PUT",
                            body: JSON.stringify({
                              amount_ml: Number(editAmount),
                              consumed_at:
                                editTime ===
                                localTime(new Date(entry.consumed_at))
                                  ? entry.consumed_at
                                  : timestamp.toISOString(),
                            }),
                          });
                      }}
                    >
                      <label>
                        Entry amount (ml)
                        <input
                          type="number"
                          min="1"
                          max="5000"
                          step="1"
                          value={editAmount}
                          disabled={disabled}
                          onChange={(event) =>
                            setEditAmount(event.target.value)
                          }
                          required
                        />
                      </label>
                      <label>
                        Time consumed
                        <input
                          type="datetime-local"
                          value={editTime}
                          max={localTime(new Date())}
                          disabled={disabled}
                          onChange={(event) => setEditTime(event.target.value)}
                          required
                        />
                      </label>
                      <button
                        className="primary"
                        type="submit"
                        disabled={disabled}
                      >
                        Save entry
                      </button>
                      <button
                        className="outline-button"
                        type="button"
                        disabled={busy || retry !== null}
                        onClick={() => setEditing(null)}
                      >
                        Cancel edit
                      </button>
                    </form>
                  ) : (
                    <>
                      <div>
                        <strong>{volume(entry.amount_ml)}</strong>
                        <time dateTime={entry.consumed_at}>
                          {new Date(entry.consumed_at).toLocaleTimeString([], {
                            hour: "numeric",
                            minute: "2-digit",
                          })}
                        </time>
                      </div>
                      <div className={styles.row}>
                        <button
                          className="outline-button"
                          disabled={disabled}
                          aria-label={`Edit ${entry.amount_ml} ml entry`}
                          onClick={() => {
                            setEditing(entry);
                            setEditAmount(String(entry.amount_ml));
                            setEditTime(localTime(new Date(entry.consumed_at)));
                          }}
                        >
                          Edit
                        </button>
                        <button
                          className="outline-button"
                          disabled={disabled}
                          aria-label={`Delete ${entry.amount_ml} ml entry`}
                          onClick={() =>
                            void mutate({
                              path: `/entries/${encodeURIComponent(entry.id)}`,
                              method: "DELETE",
                            })
                          }
                        >
                          Delete
                        </button>
                      </div>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
      <button
        className="outline-button"
        disabled={busy}
        onClick={() => {
          setError("");
          setLoading(true);
          void refresh().catch(() =>
            setError("Your water log could not be loaded. Please retry."),
          );
        }}
      >
        Refresh water log
      </button>
    </section>
  );
}
