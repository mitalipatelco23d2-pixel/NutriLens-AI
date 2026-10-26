"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { refreshBrowserSession } from "@/lib/session-keepalive";

const REFRESH_AFTER_MS = 10 * 60 * 1000;
const ACTIVE_WITHIN_MS = 20 * 60 * 1000;
const CHECK_EVERY_MS = 60 * 1000;
const STORAGE_KEY = "nutrilens-session-refreshed-at:v1";
const LOCK_NAME = "nutrilens-session-refresh";

function lastRefreshAt() {
  try {
    const value = Number(window.localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(value) ? value : 0;
  } catch {
    return 0;
  }
}

function recordRefresh(at: number) {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(at));
  } catch {
    // A blocked storage API must not prevent the HttpOnly session rotation.
  }
}

export function SessionKeepalive() {
  const router = useRouter();

  useEffect(() => {
    let stopped = false;
    let inFlight = false;
    let lastActivityAt = Date.now();
    let observedRefreshAt = lastRefreshAt();

    const rotateIfDue = async () => {
      if (
        stopped ||
        inFlight ||
        Date.now() - observedRefreshAt < REFRESH_AFTER_MS
      ) {
        return;
      }
      inFlight = true;
      const rotate = async () => {
        observedRefreshAt = Math.max(observedRefreshAt, lastRefreshAt());
        if (Date.now() - observedRefreshAt < REFRESH_AFTER_MS) return;
        const outcome = await refreshBrowserSession();
        if (stopped) return;
        if (outcome === "refreshed" || outcome === "current") {
          observedRefreshAt = Date.now();
          recordRefresh(observedRefreshAt);
        } else if (outcome === "expired") {
          router.replace("/login?next=%2Fdashboard");
        }
      };
      try {
        if (navigator.locks) {
          await navigator.locks.request(LOCK_NAME, rotate);
        } else {
          await rotate();
        }
      } catch {
        // Network or browser scheduling failures leave the existing session
        // untouched. A later activity/timer tick can safely retry.
      } finally {
        inFlight = false;
      }
    };

    const noteActivity = () => {
      lastActivityAt = Date.now();
      void rotateIfDue();
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") noteActivity();
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) observedRefreshAt = lastRefreshAt();
    };
    const timer = window.setInterval(() => {
      if (Date.now() - lastActivityAt <= ACTIVE_WITHIN_MS) {
        void rotateIfDue();
      }
    }, CHECK_EVERY_MS);

    for (const event of ["pointerdown", "keydown", "touchstart", "focus"]) {
      window.addEventListener(event, noteActivity, { passive: true });
    }
    window.addEventListener("storage", onStorage);
    document.addEventListener("visibilitychange", onVisibilityChange);
    void rotateIfDue();

    return () => {
      stopped = true;
      window.clearInterval(timer);
      for (const event of ["pointerdown", "keydown", "touchstart", "focus"]) {
        window.removeEventListener(event, noteActivity);
      }
      window.removeEventListener("storage", onStorage);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [router]);

  return null;
}
