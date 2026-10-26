import Link from "next/link";
import {
  ArrowRight,
  Bot,
  CheckCircle2,
  ScanLine,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

export default function Home() {
  return (
    <div className="marketing-shell">
      <header className="marketing-nav">
        <Link className="brand-link" href="/">
          <span className="logo-mark">
            <ScanLine size={18} />
          </span>
          NutriLens <span>X</span>
        </Link>
        <nav aria-label="Primary navigation">
          <a href="#features">Features</a>
          <a href="#how-it-works">How it works</a>
          <Link href="/pricing">Pricing</Link>
          <Link href="/about">About</Link>
        </nav>
        <div className="nav-actions">
          <Link href="/login">Log in</Link>
          <Link className="primary-link" href="/login">
            Start scanning <ArrowRight size={16} />
          </Link>
        </div>
      </header>

      <main id="main-content" tabIndex={-1}>
        <section className="marketing-hero">
          <div className="hero-copy">
            <p className="launch-pill">
              <Sparkles size={14} /> Evidence-oriented food intelligence
            </p>
            <h1>
              Understand what you’re <em>really</em> eating.
            </h1>
            <p className="hero-lede">
              Scan food. Decode ingredients. Understand nutrition. Make choices
              that fit you.
            </p>
            <div className="hero-actions">
              <Link className="hero-primary" href="/dashboard">
                Try the scanner <ScanLine size={18} />
              </Link>
              <a className="hero-secondary" href="#how-it-works">
                See how it works
              </a>
            </div>
            <div className="hero-trust">
              <span>
                <ShieldCheck size={16} /> Safety information stays accessible
              </span>
              <span>
                <CheckCircle2 size={16} /> Explainable results
              </span>
            </div>
          </div>
          <div
            className="product-preview"
            aria-label="NutriLens product result preview"
          >
            <div className="preview-top">
              <span>Product intelligence</span>
              <b>Example label evidence</b>
            </div>
            <div className="preview-product">
              <div className="preview-pack">
                OAT
                <br />
                CRUNCH<small>wholegrain bites</small>
              </div>
              <div>
                <p>Breakfast cereal</p>
                <h2>Oat Crunch Bites</h2>
                <span className="evidence-badge">
                  Evidence confidence · High
                </span>
              </div>
              <div className="preview-score">
                <strong>3</strong>
                <small>observed signals</small>
              </div>
            </div>
            <div className="preview-findings">
              <div>
                <span className="finding-icon good">✓</span>
                <p>
                  <b>Whole-grain base</b>
                  <small>Recognised oat ingredients</small>
                </p>
              </div>
              <div>
                <span className="finding-icon watch">!</span>
                <p>
                  <b>2 sugar sources</b>
                  <small>Sucrose and malt extract</small>
                </p>
              </div>
              <div>
                <span className="finding-icon neutral">4</span>
                <p>
                  <b>NOVA estimate</b>
                  <small>Taxonomy + ingredient evidence</small>
                </p>
              </div>
            </div>
            <button type="button">
              Why this result? <ArrowRight size={15} />
            </button>
          </div>
        </section>

        <section className="signal-strip" aria-label="Platform coverage">
          <span>15 integrated modules</span>
          <span>90+ reconciled capabilities</span>
          <span>Web + Android</span>
          <span>Privacy-first architecture</span>
        </section>

        <section className="marketing-section" id="features">
          <p className="section-kicker">One scan. A clearer decision.</p>
          <h2>Food labels are dense. NutriLens makes them useful.</h2>
          <div className="feature-grid">
            <article>
              <ScanLine />
              <h3>See what’s actually there</h3>
              <p>
                Extract ingredients, nutrition panels and barcodes from the food
                in front of you.
              </p>
            </article>
            <article>
              <Sparkles />
              <h3>Understand the evidence</h3>
              <p>
                Trace additives, allergens, sugar, sodium, fats and processing
                signals to governed sources.
              </p>
            </article>
            <article>
              <Bot />
              <h3>Make it personal</h3>
              <p>
                Connect results to your declared goals, diary patterns, pantry
                and practical alternatives.
              </p>
            </article>
          </div>
        </section>

        <section className="how-section" id="how-it-works">
          <div>
            <p className="section-kicker">How it works</p>
            <h2>From package to perspective in three steps.</h2>
          </div>
          <ol>
            <li>
              <b>01</b>
              <span>
                <strong>Scan or upload</strong>Use a product photo, nutrition
                panel, ingredient list or barcode.
              </span>
            </li>
            <li>
              <b>02</b>
              <span>
                <strong>Decode the label</strong>Observation flows into governed
                ingredient and nutrition intelligence.
              </span>
            </li>
            <li>
              <b>03</b>
              <span>
                <strong>Choose with context</strong>Review evidence, personal
                fit and better alternatives without medical overclaims.
              </span>
            </li>
          </ol>
        </section>

        <section className="marketing-cta">
          <p>Food intelligence that respects uncertainty.</p>
          <h2>Know more about the next thing you eat.</h2>
          <Link href="/login">
            Get started free <ArrowRight size={17} />
          </Link>
        </section>
      </main>

      <footer className="marketing-footer">
        <span>NutriLens X</span>
        <div>
          <Link href="/privacy">Privacy</Link>
          <Link href="/terms">Terms</Link>
          <Link href="/shipping">Shipping</Link>
          <Link href="/refunds">Cancellation &amp; refunds</Link>
          <Link href="/contact">Contact</Link>
          <Link href="/pricing">Pricing</Link>
          <Link href="/about">About</Link>
        </div>
      </footer>
    </div>
  );
}
