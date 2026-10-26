import Link from "next/link";

export function LegalPage({
  title,
  updated,
  children,
}: {
  title: string;
  updated: string;
  children: React.ReactNode;
}) {
  return (
    <div className="legal-shell">
      <header className="simple-nav">
        <Link className="brand-link" href="/">
          NutriLens <span>X</span>
        </Link>
        <Link href="/">Back to home</Link>
      </header>
      <main className="legal-main" id="main-content" tabIndex={-1}>
        <p className="section-kicker">NutriLens X</p>
        <h1>{title}</h1>
        <p className="legal-updated">Last updated: {updated}</p>
        <article>{children}</article>
      </main>
    </div>
  );
}
