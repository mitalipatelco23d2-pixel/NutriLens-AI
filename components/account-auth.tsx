"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { GoogleLogin } from "@/components/google-login";
import {
  AuthCapabilities,
  parseAuthCapabilities,
} from "@/lib/auth-capabilities";

type AuthMode = "signin" | "signup" | "forgot" | "verify" | "reset";

type Props = {
  initialMode: AuthMode;
  token?: string;
};

type CapabilityState =
  | { status: "loading" | "error" }
  | { status: "ready"; value: AuthCapabilities };

async function submit(path: string, body: Record<string, unknown>) {
  const response = await fetch(`/api/auth/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const payload = (await response.json().catch(() => ({}))) as {
    detail?: string;
    error?: string;
    message?: string;
  };
  if (!response.ok) {
    throw new Error(
      payload.detail ??
        payload.error ??
        "Authentication could not be completed.",
    );
  }
  return payload;
}

export function AccountAuth({ initialMode, token }: Props) {
  const router = useRouter();
  const [mode, setMode] = useState<AuthMode>(initialMode);
  const [capabilityState, setCapabilityState] = useState<CapabilityState>({
    status: "loading",
  });
  const [capabilityAttempt, setCapabilityAttempt] = useState(0);
  const capabilities =
    capabilityState.status === "ready" ? capabilityState.value : null;
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [acceptedLegal, setAcceptedLegal] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15_000);
    void fetch("/api/auth/capabilities", {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error();
        const value = parseAuthCapabilities(await response.json());
        if (active) setCapabilityState({ status: "ready", value });
      })
      .catch(() => {
        if (active) setCapabilityState({ status: "error" });
      })
      .finally(() => clearTimeout(timeout));
    return () => {
      active = false;
      clearTimeout(timeout);
      controller.abort();
    };
  }, [capabilityAttempt]);

  useEffect(() => {
    if (initialMode !== "verify" || !token) return;
    let active = true;
    void submit("email/verify", { token })
      .then(() => {
        if (!active) return;
        setMessage("Email verified. Opening your NutriLens workspace…");
        router.push("/dashboard");
        router.refresh();
      })
      .catch((reason: unknown) => {
        if (active)
          setError(
            reason instanceof Error ? reason.message : "Verification failed.",
          );
      });
    return () => {
      active = false;
    };
  }, [initialMode, router, token]);

  const changeMode = (next: AuthMode) => {
    setMode(next);
    setError("");
    setMessage("");
    setPassword("");
    setAcceptedLegal(false);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (mode === "signin") {
        await submit("email/login", { email, password });
        router.push("/dashboard");
        router.refresh();
        return;
      }
      if (mode === "signup") {
        const result = await submit("email/signup", {
          email,
          password,
          name,
          accepted_terms: acceptedLegal,
          accepted_privacy: acceptedLegal,
        });
        setMessage(result.message ?? "Check your inbox to verify your email.");
        setPassword("");
        return;
      }
      if (mode === "forgot") {
        const result = await submit("password/forgot", { email });
        setMessage(result.message ?? "Check your inbox for a reset link.");
        return;
      }
      if (mode === "reset" && token) {
        const result = await submit("password/reset", { token, password });
        setMessage(result.message ?? "Password updated.");
        setPassword("");
        setMode("signin");
      }
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Authentication failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  const emailReady = capabilities?.email !== "NOT_CONFIGURED";
  const verificationPending =
    mode === "verify" && Boolean(token) && !message && !error;
  const title =
    mode === "signup"
      ? "Create your NutriLens account."
      : mode === "forgot"
        ? "Reset your password securely."
        : mode === "reset"
          ? "Choose a new password."
          : mode === "verify"
            ? "Verifying your email."
            : "Continue to your food intelligence workspace.";

  return (
    <div className="account-auth">
      <p className="section-kicker">Welcome to NutriLens X</p>
      <h2>{title}</h2>

      {mode !== "verify" && mode !== "reset" && (
        <>
          {capabilityState.status === "loading" ? (
            <p className="auth-status" role="status">
              Loading sign-in options…
            </p>
          ) : capabilityState.status === "error" ? (
            <div>
              <p className="auth-error" role="alert">
                Sign-in options could not be loaded. Please retry.
              </p>
              <button
                className="outline-button"
                type="button"
                onClick={() => {
                  setCapabilityState({ status: "loading" });
                  setCapabilityAttempt((attempt) => attempt + 1);
                }}
              >
                Retry sign-in options
              </button>
            </div>
          ) : capabilities?.google_client_id ? (
            <GoogleLogin clientId={capabilities.google_client_id} />
          ) : (
            <p className="auth-config">
              Google sign-in is not configured for this site.
            </p>
          )}
          <div className="auth-divider">
            <span>OR</span>
          </div>
        </>
      )}

      {mode === "verify" ? (
        <div className="auth-progress" aria-live="polite">
          {verificationPending
            ? "Checking your one-time verification link…"
            : message || error}
        </div>
      ) : (
        <form className="email-auth-form" onSubmit={handleSubmit}>
          {mode === "signup" && (
            <label>
              Name
              <input
                autoComplete="name"
                maxLength={100}
                onChange={(event) => setName(event.target.value)}
                required
                value={name}
              />
            </label>
          )}
          {mode !== "reset" && (
            <label>
              Email address
              <input
                autoComplete="email"
                inputMode="email"
                maxLength={254}
                onChange={(event) => setEmail(event.target.value)}
                required
                type="email"
                value={email}
              />
            </label>
          )}
          {mode !== "forgot" && (
            <label>
              {mode === "reset" ? "New password" : "Password"}
              <input
                autoComplete={
                  mode === "signin" ? "current-password" : "new-password"
                }
                maxLength={128}
                minLength={mode === "signin" ? 1 : 12}
                onChange={(event) => setPassword(event.target.value)}
                required
                type="password"
                value={password}
              />
              {mode !== "signin" && (
                <small>
                  12+ characters with uppercase, lowercase, number and symbol.
                </small>
              )}
            </label>
          )}
          {mode === "signup" && (
            <label className="auth-consent">
              <input
                checked={acceptedLegal}
                onChange={(event) => setAcceptedLegal(event.target.checked)}
                required
                type="checkbox"
              />
              <span>
                I am 18 or older and agree to the{" "}
                <a href="/terms" target="_blank" rel="noreferrer">
                  Terms of Use
                </a>{" "}
                and{" "}
                <a href="/privacy" target="_blank" rel="noreferrer">
                  Privacy Policy
                </a>
                .
              </span>
            </label>
          )}
          {message && (
            <p className="auth-success" role="status">
              {message}
            </p>
          )}
          {error && (
            <p className="auth-error" role="alert">
              {error}
            </p>
          )}
          {!emailReady && capabilities && (
            <p className="auth-config">
              Email authentication is being configured.
            </p>
          )}
          <button
            className="primary auth-submit"
            disabled={
              busy || !emailReady || (mode === "signup" && !acceptedLegal)
            }
            type="submit"
          >
            {busy
              ? "Please wait…"
              : mode === "signup"
                ? "Create account"
                : mode === "forgot"
                  ? "Send reset link"
                  : mode === "reset"
                    ? "Update password"
                    : "Sign in"}
          </button>
        </form>
      )}

      <div className="auth-links">
        {mode === "signin" && (
          <>
            <button onClick={() => changeMode("forgot")} type="button">
              Forgot password?
            </button>
            <span>
              New here?{" "}
              <button onClick={() => changeMode("signup")} type="button">
                Create account
              </button>
            </span>
          </>
        )}
        {mode !== "signin" && mode !== "verify" && (
          <button onClick={() => changeMode("signin")} type="button">
            Back to sign in
          </button>
        )}
      </div>

      {capabilities?.phone_otp === "READY" && (
        <button className="phone-auth-button" type="button">
          Continue with mobile number
        </button>
      )}
    </div>
  );
}
