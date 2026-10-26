"use client";

import { ArrowLeft, Database, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

type Registry = {
  registry_version: string;
  release: string;
  download_policy: string;
  claims_boundary: string;
  models: Array<{
    model_id: string;
    name: string;
    version: string;
    task: string;
    framework: string;
    training_status: string;
    license: string;
    required: boolean;
    artifact_status: string;
    dataset_version: string | null;
    metrics: Record<string, unknown>;
  }>;
};

export function ModelRegistryPage() {
  const [registry, setRegistry] = useState<Registry | null>(null);
  const [message, setMessage] = useState("Loading the governed model registry…");

  useEffect(() => {
    let active = true;
    void fetch("/api/backend/system/models", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(
            response.status === 403
              ? "Administrator access is required."
              : response.status === 401
                ? "Sign in with an authorized NutriLens account."
                : "The model registry is unavailable.",
          );
        }
        return (await response.json()) as Registry;
      })
      .then((payload) => {
        if (active) {
          setRegistry(payload);
          setMessage("");
        }
      })
      .catch((reason: unknown) => {
        if (active) setMessage(reason instanceof Error ? reason.message : "Registry unavailable.");
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="registry-shell" id="main-content" tabIndex={-1}>
      <header>
        <Link href="/dashboard"><ArrowLeft size={16} /> Dashboard</Link>
        <span><ShieldCheck size={15} /> Administrator-only metadata</span>
      </header>
      <section className="registry-heading">
        <p className="eyebrow">R15 · DATA & AI INFRASTRUCTURE</p>
        <h1>Model registry</h1>
        <p>Inspect governed versions, training status, artifact availability, licensing, and recorded evaluation evidence.</p>
      </section>
      {message && <p className="assistant-error" role="status">{message}</p>}
      {registry && (
        <>
          <div className="registry-summary">
            <span>Registry <strong>v{registry.registry_version}</strong></span>
            <span>Release <strong>{registry.release}</strong></span>
            <span>Downloads <strong>{registry.download_policy.replaceAll("_", " ")}</strong></span>
          </div>
          <p className="compare-note"><Database size={16} /> {registry.claims_boundary}</p>
          <div className="registry-grid">
            {registry.models.map((model) => (
              <article className="card registry-model" key={model.model_id}>
                <div>
                  <span>{model.training_status.replaceAll("_", " ")}</span>
                  <em>{model.artifact_status.replaceAll("_", " ")}</em>
                </div>
                <h2>{model.name}</h2>
                <p>{model.task}</p>
                <dl>
                  <div><dt>Version</dt><dd>{model.version}</dd></div>
                  <div><dt>Framework</dt><dd>{model.framework}</dd></div>
                  <div><dt>Dataset</dt><dd>{model.dataset_version ?? "Not applicable"}</dd></div>
                  <div><dt>Evaluation</dt><dd>{Object.keys(model.metrics).length ? "Recorded" : "Not recorded"}</dd></div>
                </dl>
                <small>{model.license}</small>
              </article>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
