import { useEffect, useRef, useState } from 'react'
import { analyzeImage, formatBytes, validateImage } from './api.js'
import {
  displayBasis,
  formatNutrient,
  probabilityEntries,
  safeSourceUrl,
  sourceByCitation,
  statusTone,
} from './result-utils.js'

function BrandMark() {
  return (
    <span className="brand-mark" aria-hidden="true">
      <svg viewBox="0 0 48 48" role="img">
        <path d="M10 31c10-2 16-10 18-21 8 6 11 14 7 22-4 8-15 10-25 5 7-2 13-6 18-13-6 5-12 8-18 9v-2Z" />
      </svg>
    </span>
  )
}

function StatusPill({ status, children }) {
  return <span className={`status-pill ${statusTone(status)}`}>{children || status}</span>
}

function EmptyState({ title, detail }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  )
}

function MetricCard({ eyebrow, value, detail, tone = 'neutral' }) {
  return (
    <article className={`metric-card ${tone}`}>
      <span className="eyebrow">{eyebrow}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  )
}

function UploadPanel({ file, previewUrl, busy, error, onFile, onSubmit, onClear }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  function receiveFile(nextFile) {
    setDragging(false)
    onFile(nextFile || null)
  }

  return (
    <section className="upload-card" aria-labelledby="upload-heading">
      <div className="section-heading compact">
        <div>
          <span className="step-label">01 · Scan</span>
          <h2 id="upload-heading">Upload a food label</h2>
        </div>
        <span className="privacy-chip">Processed for this request</span>
      </div>
      <div
        className={`drop-zone ${dragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`}
        onDragEnter={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          receiveFile(event.dataTransfer.files?.[0])
        }}
      >
        {previewUrl ? (
          <img className="image-preview" src={previewUrl} alt="Selected food label preview" />
        ) : (
          <div className="upload-icon" aria-hidden="true">↑</div>
        )}
        <div className="drop-copy">
          <strong>{file ? file.name : 'Drop your label image here'}</strong>
          <span>{file ? `${formatBytes(file.size)} · Ready to analyze` : 'or choose a file from your device'}</span>
        </div>
        <button className="button secondary" type="button" onClick={() => inputRef.current?.click()} disabled={busy}>
          {file ? 'Choose another' : 'Browse image'}
        </button>
        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={(event) => receiveFile(event.target.files?.[0])}
          data-testid="image-input"
        />
      </div>
      <div className="upload-meta">
        <span>JPEG, PNG or WEBP</span>
        <span>Maximum 8 MB</span>
        <span>Clear, straight-on photos work best</span>
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      <div className="actions">
        <button className="button primary" type="button" onClick={onSubmit} disabled={busy || !file}>
          {busy ? <><span className="spinner" aria-hidden="true" /> Analyzing label…</> : 'Analyze nutrition label'}
        </button>
        {file && (
          <button className="button ghost" type="button" onClick={onClear} disabled={busy}>
            Remove image
          </button>
        )}
      </div>
      {busy && (
        <div className="progress-message" role="status">
          <span>Reading label</span><span>Parsing nutrition</span><span>Preparing evidence</span>
        </div>
      )}
    </section>
  )
}

function NutritionPanel({ analysis }) {
  const nutrition = analysis?.nutrition || {}
  const details = analysis?.nutrition_details || {}
  const nutrients = Object.entries(nutrition).map(([key, value]) =>
    formatNutrient(key, value, details[key]),
  )
  return (
    <section className="result-section" aria-labelledby="nutrition-heading">
      <div className="section-heading">
        <div>
          <span className="step-label">M1 · Parsed label</span>
          <h3 id="nutrition-heading">Nutrition & ingredients</h3>
        </div>
        <StatusPill status={analysis?.integration?.status}>{displayBasis(analysis?.basis)}</StatusPill>
      </div>
      {nutrients.length ? (
        <div className="nutrient-grid">
          {nutrients.map((item) => (
            <div className="nutrient" key={item.key}>
              <span>{item.label}</span><strong>{item.value}</strong><small>{item.basis}</small>
            </div>
          ))}
        </div>
      ) : <EmptyState title="No nutrition values extracted" detail="The label may be incomplete or difficult to read." />}
      <div className="label-columns">
        <TagList title="Ingredients" values={analysis?.ingredients} empty="No ingredient list found." />
        <TagList title="Allergens" values={analysis?.allergens} empty="No allergens extracted." emphasis />
        <TagList title="Additives" values={analysis?.additives} empty="No additives extracted." />
      </div>
    </section>
  )
}

function TagList({ title, values, empty, emphasis = false }) {
  const items = Array.isArray(values) ? values : []
  return (
    <div className="tag-group">
      <h4>{title} <span>{items.length}</span></h4>
      {items.length ? (
        <div className="tags">
          {items.map((value, index) => <span className={emphasis ? 'tag emphasis' : 'tag'} key={`${value}-${index}`}>{value}</span>)}
        </div>
      ) : <p className="muted">{empty}</p>}
    </div>
  )
}

function HealthOverview({ health }) {
  const nutrition = health?.nutrition_score || {}
  const risk = health?.ingredient_risk || {}
  const probabilities = probabilityEntries(risk.probabilities)
  const scoreAvailable = nutrition.available === true
  const riskAvailable = risk.available === true
  return (
    <section className="result-section" aria-labelledby="m2-heading">
      <div className="section-heading">
        <div><span className="step-label">M2 · Two separate outputs</span><h3 id="m2-heading">Health analysis</h3></div>
        <StatusPill status={health?.status}>{health?.status || 'Unavailable'}</StatusPill>
      </div>
      <div className="metric-grid">
        <MetricCard
          eyebrow="Nutrition health score"
          value={scoreAvailable ? `${health.health_score}/100` : 'Unavailable'}
          detail={scoreAvailable ? `${health.score_level || 'Scored'} · ${displayBasis(nutrition.basis)}` : nutrition.detail || 'Required nutrition data was not available.'}
          tone={scoreAvailable ? 'positive' : 'caution'}
        />
        <MetricCard
          eyebrow="Ingredient-risk classifier"
          value={riskAvailable ? risk.risk_level : 'Unavailable'}
          detail={riskAvailable ? 'Model prediction — not a medical safety assessment' : risk.detail || 'Ingredient-risk model output was not available.'}
          tone={riskAvailable ? (risk.risk_level === 'HIGH' ? 'negative' : risk.risk_level === 'MODERATE' ? 'caution' : 'positive') : 'caution'}
        />
      </div>
      {probabilities.length > 0 && (
        <div className="probability-list" aria-label="Ingredient-risk class probabilities">
          {probabilities.map(({ label, value }) => (
            <div className="probability" key={label}>
              <div><span>{label}</span><strong>{value.toFixed(1)}%</strong></div>
              <div className="bar"><span style={{ width: `${Math.min(100, Math.max(0, value))}%` }} /></div>
            </div>
          ))}
        </div>
      )}
      {(nutrition.reasons?.length > 0 || nutrition.warnings?.length > 0) && (
        <div className="reason-box">
          <h4>Why this nutrition score?</h4>
          <ul>{[...(nutrition.reasons || []), ...(nutrition.warnings || [])].map((reason, index) => <li key={`${reason}-${index}`}>{reason}</li>)}</ul>
        </div>
      )}
      {nutrition.missing_nutrients?.length > 0 && (
        <p className="inline-note"><strong>Missing for scoring:</strong> {nutrition.missing_nutrients.join(', ')}</p>
      )}
    </section>
  )
}

function KnowledgePanel({ knowledge }) {
  if (!knowledge || knowledge.status !== 'available') {
    return <EmptyState title="Knowledge base unavailable" detail={knowledge?.warnings?.[0] || 'No verified local dataset was available for matching.'} />
  }
  return (
    <div className="subsection">
      <div className="subsection-title">
        <h4>Knowledge-base matches</h4>
        <StatusPill status={knowledge.status}>{knowledge.summary?.matched || 0} matched</StatusPill>
      </div>
      <p className="muted compact-copy">Deterministic matches from an unverified teammate dataset. Source labels below are not independently verified citations.</p>
      {knowledge.matched?.length ? (
        <div className="match-list">
          {knowledge.matched.map((match, index) => (
            <article className="match" key={`${match.input_ingredient}-${index}`}>
              <div><strong>{match.input_ingredient}</strong><span>{match.matched_ingredient} · {match.matched_by}</span></div>
              <p>{match.dataset_reason || match.concern_type || 'No dataset reason provided.'}</p>
              <small>Dataset source label: {match.dataset_source_label || 'Not supplied'} · citation not verified</small>
            </article>
          ))}
        </div>
      ) : <p className="muted">No ingredients matched the local dataset.</p>}
      {knowledge.unmatched?.length > 0 && <p className="inline-note"><strong>Unmatched:</strong> {knowledge.unmatched.map((item) => item.input_ingredient).join(', ')}</p>}
    </div>
  )
}

function ShapPanel({ attribution }) {
  const available = attribution?.available === true
  return (
    <div className="subsection">
      <div className="subsection-title"><h4>Model attribution</h4><StatusPill status={attribution?.status}>{attribution?.status || 'Unavailable'}</StatusPill></div>
      {!available ? (
        <EmptyState title={attribution?.status === 'disabled' ? 'SHAP is disabled' : 'SHAP unavailable'} detail={attribution?.detail || 'No model attribution was produced.'} />
      ) : (
        <>
          <p className="muted compact-copy">TF-IDF token attributions for the existing {attribution.explained_class} prediction. These are model contributions, not ingredient-level medical causality.</p>
          <div className="attribution-summary">
            <span>Baseline <strong>{formatProbability(attribution.baseline?.probability)}</strong></span>
            <span>Prediction <strong>{formatProbability(attribution.predicted_probability)}</strong></span>
            <span>Runtime <strong>{attribution.runtime_ms ?? '—'} ms</strong></span>
          </div>
          <div className="feature-list">
            {(attribution.features || []).map((feature, index) => (
              <div className="feature" key={`${feature.tfidf_token}-${index}`}>
                <code>{feature.tfidf_token}</code>
                <span className={feature.contribution >= 0 ? 'up' : 'down'}>{feature.contribution >= 0 ? '+' : ''}{Number(feature.contribution).toFixed(4)}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

function formatProbability(value) {
  return Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(1)}%` : '—'
}

function RagPanel({ rag }) {
  const sources = sourceByCitation(rag?.sources)
  if (!rag || rag.available !== true) {
    const title = rag?.status === 'disabled' ? 'Source-grounded RAG is disabled' : rag?.status === 'insufficient_evidence' ? 'Not enough source evidence' : 'Source-grounded answer unavailable'
    return (
      <div className="subsection">
        <div className="subsection-title"><h4>Source-grounded answer</h4><StatusPill status={rag?.status}>{rag?.status || 'Unavailable'}</StatusPill></div>
        <EmptyState title={title} detail={rag?.detail || 'No generative answer was produced. Other analysis remains available.'} />
      </div>
    )
  }
  return (
    <div className="subsection rag-panel">
      <div className="subsection-title"><h4>Source-grounded answer</h4><StatusPill status={rag.status}>RAG available</StatusPill></div>
      <p className="rag-answer">{rag.answer}</p>
      <div className="claims">
        {(rag.claims || []).map((claim, index) => (
          <article className="claim" key={`${claim.text}-${index}`}>
            <p>{claim.text}</p>
            <div className="citation-row">
              {(claim.citation_ids || []).map((citationId) => {
                const source = sources[citationId]
                const sourceUrl = safeSourceUrl(source?.canonical_url)
                return source && sourceUrl ? (
                  <a key={citationId} href={sourceUrl} target="_blank" rel="noreferrer noopener">
                    [{citationId}] {source.organization || source.title}
                  </a>
                ) : <span key={citationId}>[{citationId}]</span>
              })}
            </div>
          </article>
        ))}
      </div>
      {(rag.sources || []).length > 0 && (
        <details className="source-details">
          <summary>View evidence excerpts and source details</summary>
          {(rag.sources || []).map((source) => (
            <article key={source.citation_id}>
              {safeSourceUrl(source.canonical_url) ? (
                <a href={safeSourceUrl(source.canonical_url)} target="_blank" rel="noreferrer noopener">[{source.citation_id}] {source.title}</a>
              ) : <strong>[{source.citation_id}] {source.title}</strong>}
              <span>{source.organization} · {source.revision_date || source.publication_date || 'Date not supplied'}</span>
              {(source.evidence_excerpts || []).map((excerpt, index) => <blockquote key={`${source.citation_id}-${index}`}>{excerpt}</blockquote>)}
            </article>
          ))}
        </details>
      )}
      <p className="disclaimer">{rag.disclaimer}</p>
    </div>
  )
}

function ExplanationPanel({ explanation }) {
  if (!explanation) return <section className="result-section"><EmptyState title="Explanation unavailable" detail="The core label analysis may still be useful." /></section>
  const recommendations = explanation.recommendations || {}
  return (
    <section className="result-section" aria-labelledby="m5-heading">
      <div className="section-heading">
        <div><span className="step-label">M5 · Explain & support</span><h3 id="m5-heading">Evidence and next steps</h3></div>
        <StatusPill status={explanation.status}>{explanation.status || 'Unavailable'}</StatusPill>
      </div>
      <div className="explanation-stack">
        <div className="subsection">
          <div className="subsection-title"><h4>General recommendations</h4><StatusPill status={recommendations.status}>{recommendations.status || 'Unavailable'}</StatusPill></div>
          {recommendations.items?.length ? (
            <div className="recommendation-list">
              {recommendations.items.map((item, index) => (
                <article className="recommendation" key={`${item.category}-${index}`}>
                  <StatusPill status={item.priority === 'HIGH' ? 'unavailable' : item.priority === 'MEDIUM' ? 'partial' : 'neutral'}>{item.priority}</StatusPill>
                  <div><strong>{item.message}</strong><p>{item.reason}</p></div>
                </article>
              ))}
            </div>
          ) : <p className="muted">No basis-supported recommendations were generated.</p>}
          {recommendations.omissions?.length > 0 && <ul className="omissions">{recommendations.omissions.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>}
          {recommendations.disclaimer && <p className="disclaimer">{recommendations.disclaimer}</p>}
        </div>
        <KnowledgePanel knowledge={explanation.knowledge_base} />
        <ShapPanel attribution={explanation.model_attribution} />
        <RagPanel rag={explanation.rag} />
      </div>
    </section>
  )
}

function TechnicalPanel({ result }) {
  return (
    <section className="result-section technical" aria-labelledby="technical-heading">
      <div className="section-heading">
        <div><span className="step-label">Request details</span><h3 id="technical-heading">OCR & integration status</h3></div>
        <code>{result.request_id}</code>
      </div>
      <div className="technical-grid">
        <div><span>OCR engine</span><strong>{result.ocr?.engine || 'Unavailable'}</strong></div>
        <div><span>Confidence</span><strong>{Number.isFinite(result.ocr?.confidence) ? `${Math.round(result.ocr.confidence * 100)}%` : 'Not reported'}</strong></div>
        <div><span>Rotation</span><strong>{result.ocr ? `${result.ocr.rotation}°` : 'Not reported'}</strong></div>
        {Object.entries(result.integrations || {}).map(([name, integration]) => (
          <div key={name}><span>{name}</span><strong>{integration.status}</strong><small>{integration.provider}</small></div>
        ))}
      </div>
      <p className="privacy-note">Raw OCR text is intentionally not returned by the stable analysis response. Parsed label fields are shown above.</p>
      {result.warnings?.length > 0 && (
        <div className="warning-box"><strong>Review these limitations</strong><ul>{result.warnings.map((warning, index) => <li key={`${warning}-${index}`}>{warning}</li>)}</ul></div>
      )}
    </section>
  )
}

function Results({ result }) {
  return (
    <div className="results" id="analysis-results">
      <div className="results-banner">
        <div>
          <span className="step-label">02 · Review</span>
          <h2>{result.status === 'success' ? 'Analysis complete' : 'Partial analysis available'}</h2>
          <p>{result.status === 'success' ? 'Your label was processed across the available NutriLens components.' : 'Some components could not complete. Available results are shown with their limitations.'}</p>
        </div>
        <StatusPill status={result.status}>{result.status === 'success' ? 'Complete' : 'Partial result'}</StatusPill>
      </div>
      <HealthOverview health={result.health} />
      <NutritionPanel analysis={result.analysis} />
      <ExplanationPanel explanation={result.explanation} />
      <TechnicalPanel result={result} />
    </div>
  )
}

export default function App() {
  const [file, setFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  function chooseFile(nextFile) {
    setResult(null)
    const validationError = validateImage(nextFile)
    setError(validationError || '')
    if (validationError) {
      setFile(null)
      setPreviewUrl('')
      return
    }
    setFile(nextFile)
    setPreviewUrl(URL.createObjectURL(nextFile))
  }

  async function submit() {
    const validationError = validateImage(file)
    if (validationError) {
      setError(validationError)
      return
    }
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const payload = await analyzeImage(file)
      setResult(payload)
      window.setTimeout(() => document.getElementById('analysis-results')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 0)
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'Analysis failed unexpectedly.')
    } finally {
      setBusy(false)
    }
  }

  function clear() {
    setFile(null)
    setPreviewUrl('')
    setResult(null)
    setError('')
  }

  return (
    <>
      <header className="site-header">
        <a className="brand" href="#top" aria-label="NutriLens AI home"><BrandMark /><span>NutriLens <strong>AI</strong></span></a>
        <nav aria-label="Page navigation"><a href="#how-it-works">How it works</a><a href="#notice">About results</a></nav>
        <span className="header-badge">Private by design</span>
      </header>
      <main id="top">
        <section className="hero">
          <div className="hero-copy">
            <span className="kicker">Food labels, made understandable</span>
            <h1>See what’s inside.<br /><em>Understand why it matters.</em></h1>
            <p>Upload a packaged-food label to extract nutrition facts, review two separate health signals, and explore source-linked explanations when available.</p>
            <div className="trust-row"><span>✓ No account required</span><span>✓ Separate score & risk outputs</span><span>✓ Limitations shown clearly</span></div>
          </div>
          <aside className="hero-note">
            <span>NutriLens workflow</span>
            <ol><li><strong>Read</strong><small>OCR & label parsing</small></li><li><strong>Assess</strong><small>Nutrition score & model risk</small></li><li><strong>Explain</strong><small>Evidence, attribution & guidance</small></li></ol>
          </aside>
        </section>

        <UploadPanel file={file} previewUrl={previewUrl} busy={busy} error={error} onFile={chooseFile} onSubmit={submit} onClear={clear} />
        {result && <Results result={result} />}

        <section className="how-it-works" id="how-it-works">
          <div className="section-heading"><div><span className="step-label">Designed for transparency</span><h2>One scan, clearly separated results</h2></div></div>
          <div className="how-grid">
            <article><span>01</span><h3>Extract</h3><p>Tesseract OCR and the M1 parser turn visible label text into structured nutrition and ingredient fields.</p></article>
            <article><span>02</span><h3>Assess</h3><p>M2 returns a nutrition-based score and a separate ingredient-risk model prediction. Neither is silently substituted.</p></article>
            <article><span>03</span><h3>Explain</h3><p>M5 adds basis-aware guidance, optional model attribution, and source-grounded RAG when each component is available.</p></article>
          </div>
        </section>

        <section className="notice" id="notice">
          <BrandMark />
          <div><h2>Informational, not medical advice</h2><p>NutriLens reports automated OCR, rules, and machine-learning outputs that may be incomplete or wrong. It does not diagnose conditions, establish ingredient safety, or replace advice from a qualified health professional. Always verify the original package label.</p></div>
        </section>
      </main>
      <footer><span>NutriLens AI · Student project</span><span>Built to keep evidence, model output, and recommendations distinct.</span></footer>
    </>
  )
}
