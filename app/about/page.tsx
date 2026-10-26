import {
  ArrowLeft,
  Database,
  HeartHandshake,
  ScanLine,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";

export const metadata = {
  title: "About NutriLens X",
  description:
    "How NutriLens X approaches evidence-oriented food intelligence.",
};

export default function AboutPage() {
  return (
    <div className="legal-shell">
      <header className="simple-nav">
        <Link className="brand-link" href="/">
          NutriLens <span>X</span>
        </Link>
        <Link href="/">
          <ArrowLeft size={15} /> Back to home
        </Link>
      </header>
      <main className="legal-main about-main" id="main-content" tabIndex={-1}>
        <p className="section-kicker">NutriLens X</p>
        <h1>Food intelligence built around evidence and uncertainty.</h1>
        <p className="about-lede">
          NutriLens X helps people inspect food labels, understand observed
          ingredient and nutrition signals, and organize their own food records.
          It is general wellness decision support—not diagnosis, treatment, or a
          substitute for qualified care.
        </p>
        <div className="about-grid">
          <article>
            <ScanLine aria-hidden="true" />
            <h2>Observe first</h2>
            <p>
              Images, labels and barcodes are processed into explicit evidence
              with confidence and unknown states.
            </p>
          </article>
          <article>
            <Database aria-hidden="true" />
            <h2>Govern the knowledge</h2>
            <p>
              Taxonomies and reference sources are versioned, licensed,
              checksummed and kept separate from observations.
            </p>
          </article>
          <article>
            <ShieldCheck aria-hidden="true" />
            <h2>Protect the person</h2>
            <p>
              Authentication, owner-scoped records, consent boundaries and data
              deletion are part of the product architecture.
            </p>
          </article>
          <article>
            <HeartHandshake aria-hidden="true" />
            <h2>Stay useful without overclaiming</h2>
            <p>
              Critical safety evidence remains accessible, while unsupported
              health scores and medical conclusions stay out.
            </p>
          </article>
        </div>
        <section className="about-boundary">
          <h2>What NutriLens does not promise</h2>
          <p>
            NutriLens does not determine whether a person has a disease or
            deficiency, declare an ingredient toxic, prescribe a diet, or
            guarantee that a food is suitable for everyone. Labels can be
            incomplete and source evidence can change, so users should verify
            packaging and seek qualified advice for medical decisions.
          </p>
          <div>
            <Link href="/privacy">Privacy</Link>
            <Link href="/terms">Terms</Link>
            <Link href="/pricing">Plans</Link>
          </div>
        </section>
      </main>
    </div>
  );
}
