"use client";

import Script from "next/script";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(options: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }): void;
          renderButton(
            element: HTMLElement,
            options: Record<string, string>,
          ): void;
        };
      };
    };
  }
}

export function GoogleLogin({ clientId }: { clientId: string }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [scriptStatus, setScriptStatus] = useState<
    "loading" | "ready" | "error"
  >("loading");
  const target = useRef<HTMLDivElement>(null);
  const alive = useRef(true);
  const submitting = useRef(false);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (scriptStatus !== "loading") return;
    const timeout = setTimeout(() => setScriptStatus("error"), 15_000);
    return () => clearTimeout(timeout);
  }, [scriptStatus]);

  const initializeGoogle = () => {
    if (!alive.current) return;
    const provider = window.google?.accounts?.id;
    if (!target.current || !provider) {
      setScriptStatus("error");
      return;
    }
    try {
      provider.initialize({
        client_id: clientId,
        callback: async ({ credential }) => {
          if (!alive.current || submitting.current) return;
          submitting.current = true;
          setBusy(true);
          setError("");
          try {
            const response = await fetch("/api/auth/google", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ credential }),
              signal: AbortSignal.timeout(20_000),
            });
            if (!response.ok)
              throw new Error("Sign-in could not be completed.");
            if (!alive.current) return;
            router.push("/dashboard");
            router.refresh();
          } catch (reason) {
            if (alive.current) {
              setError(
                reason instanceof Error && !(reason instanceof DOMException)
                  ? reason.message
                  : "Sign-in could not be completed. Please try again.",
              );
              setBusy(false);
            }
          } finally {
            submitting.current = false;
          }
        },
      });
      provider.renderButton(target.current, {
        theme: "outline",
        size: "large",
        text: "continue_with",
        shape: "rectangular",
        width: "360",
      });
      setScriptStatus("ready");
    } catch {
      setScriptStatus("error");
    }
  };

  return (
    <div className="google-login-wrap">
      <Script
        src="https://accounts.google.com/gsi/client"
        strategy="afterInteractive"
        onReady={initializeGoogle}
        onError={() => {
          if (alive.current) setScriptStatus("error");
        }}
      />
      <div id="google-signin" ref={target} aria-label="Continue with Google" />
      {scriptStatus === "loading" && (
        <p className="auth-status" role="status">
          Loading Google sign-in…
        </p>
      )}
      {scriptStatus === "error" && (
        <div>
          <p className="auth-error" role="alert">
            Google sign-in could not load. Check your connection or browser
            settings, then reload this page.
          </p>
          <button
            className="outline-button"
            type="button"
            onClick={() => window.location.reload()}
          >
            Reload Google sign-in
          </button>
        </div>
      )}
      {busy && (
        <p className="auth-status" role="status">
          Verifying your Google account…
        </p>
      )}
      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
