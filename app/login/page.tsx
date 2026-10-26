import Link from "next/link";
import { ScanLine, ShieldCheck } from "lucide-react";

import { AccountAuth } from "@/components/account-auth";

type AuthMode = "signin" | "signup" | "forgot" | "verify" | "reset";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ mode?: string; token?: string }>;
}) {
  const query = await searchParams;
  const allowedModes = new Set<AuthMode>([
    "signin",
    "signup",
    "forgot",
    "verify",
    "reset",
  ]);
  const requestedMode = query.mode as AuthMode | undefined;
  const initialMode =
    requestedMode && allowedModes.has(requestedMode) ? requestedMode : "signin";
  return (
    <main className="login-page" id="main-content" tabIndex={-1}>
      <section className="login-story">
        <Link className="brand-link" href="/">
          <span className="logo-mark">
            <ScanLine size={18} />
          </span>
          NutriLens <span>X</span>
        </Link>
        <div>
          <p className="section-kicker">
            Understand what you’re really eating.
          </p>
          <h1>Your food choices deserve better context.</h1>
          <p>
            Sign in to keep scans, build your nutrition history and receive
            insights based on the preferences you choose to share.
          </p>
        </div>
        <span>
          <ShieldCheck size={17} /> Passwords are protected with Argon2id and
          never stored as plaintext.
        </span>
      </section>
      <section className="login-panel">
        <div className="login-card">
          <AccountAuth initialMode={initialMode} token={query.token} />
          <p className="legal-copy">
            By continuing, you agree to the <Link href="/terms">Terms</Link> and
            acknowledge the <Link href="/privacy">Privacy Policy</Link>.
          </p>
          <div className="wellness-note">
            <ShieldCheck size={18} />
            <span>
              <strong>Wellness decision support</strong>NutriLens does not
              diagnose disease or replace qualified medical advice.
            </span>
          </div>
        </div>
      </section>
    </main>
  );
}
