"use client";

import { ArrowLeft, BarChart3, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

type ResearchAggregate = {
  state: "AVAILABLE" | "INSUFFICIENT_COHORT";
  minimum_cohort: number;
  deidentified_user_count: number | null;
  diary_entry_count: number | null;
  nutrient_totals: {
    calories: number;
    protein_g: number;
    carbs_g: number;
    fat_g: number;
    sugar_g: number;
    sodium_mg: number;
  } | null;
  method: string;
  limitation: string;
};

type CountryCatalog = {
  countries: { m49_code: string; country: string }[];
  first_year: number;
  latest_year: number;
  source: { catalog_url: string; citation: string };
};

type CountryComparison = {
  year: number;
  records: {
    m49_code: string;
    country: string;
    values: {
      food_supply_kcal_per_capita_day: number | null;
      protein_supply_g_per_capita_day: number | null;
      fat_supply_g_per_capita_day: number | null;
    };
    quality_flags: Record<string, string>;
  }[];
  source: { catalog_url: string; citation: string };
  limitations: string[];
};

type IndicatorId =
  | "food_supply_kcal_per_capita_day"
  | "protein_supply_g_per_capita_day"
  | "fat_supply_g_per_capita_day";

type CountryTrend = {
  indicator: IndicatorId;
  unit: string;
  first_year: number;
  latest_year: number;
  series: {
    m49_code: string;
    country: string;
    points: {
      year: number;
      value: number | null;
      quality_flag: string | null;
    }[];
  }[];
  limitations: string[];
};

export function ResearchPage() {
  const [aggregate, setAggregate] = useState<ResearchAggregate | null>(null);
  const [message, setMessage] = useState(
    "Loading the privacy-preserving aggregate…",
  );
  const [catalog, setCatalog] = useState<CountryCatalog | null>(null);
  const [countryCodes, setCountryCodes] = useState<[string, string]>([
    "356",
    "840",
  ]);
  const [year, setYear] = useState(2023);
  const [comparison, setComparison] = useState<CountryComparison | null>(null);
  const [trend, setTrend] = useState<CountryTrend | null>(null);
  const [trendIndicator, setTrendIndicator] = useState<IndicatorId>(
    "food_supply_kcal_per_capita_day",
  );
  const [countryMessage, setCountryMessage] = useState(
    "Loading governed country indicators…",
  );

  useEffect(() => {
    let active = true;
    void fetch("/api/backend/research/aggregate", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(
            response.status === 403
              ? "Researcher or administrator access is required."
              : response.status === 401
                ? "Sign in with an authorized NutriLens account."
                : "Research aggregates are unavailable.",
          );
        }
        return (await response.json()) as ResearchAggregate;
      })
      .then((payload) => {
        if (active) {
          setAggregate(payload);
          setMessage("");
        }
      })
      .catch((reason: unknown) => {
        if (active)
          setMessage(
            reason instanceof Error ? reason.message : "Aggregate unavailable.",
          );
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    void fetch("/api/backend/population/countries", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok)
          throw new Error("Country indicators are unavailable.");
        return (await response.json()) as CountryCatalog;
      })
      .then((payload) => {
        if (!active) return;
        setCatalog(payload);
        setYear(payload.latest_year);
        setCountryMessage("");
      })
      .catch((reason: unknown) => {
        if (active)
          setCountryMessage(
            reason instanceof Error
              ? reason.message
              : "Country indicators are unavailable.",
          );
      });
    return () => {
      active = false;
    };
  }, []);

  async function compareCountries() {
    if (countryCodes[0] === countryCodes[1]) {
      setCountryMessage("Select two distinct countries.");
      return;
    }
    setCountryMessage("Comparing the governed records…");
    setComparison(null);
    try {
      const response = await fetch("/api/backend/population/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ m49_codes: countryCodes, year }),
      });
      if (!response.ok)
        throw new Error("No governed records exist for that selection.");
      setComparison((await response.json()) as CountryComparison);
      setCountryMessage("");
    } catch (reason: unknown) {
      setCountryMessage(
        reason instanceof Error ? reason.message : "Comparison unavailable.",
      );
    }
  }

  async function loadTrend() {
    setCountryMessage("Loading the descriptive time series…");
    setTrend(null);
    try {
      const response = await fetch("/api/backend/population/trends", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          m49_codes: countryCodes,
          indicator: trendIndicator,
          first_year: catalog?.first_year ?? 2010,
          latest_year: catalog?.latest_year ?? 2023,
        }),
      });
      if (!response.ok)
        throw new Error("The governed time series is unavailable.");
      setTrend((await response.json()) as CountryTrend);
      setCountryMessage("");
    } catch (reason: unknown) {
      setCountryMessage(
        reason instanceof Error
          ? reason.message
          : "The governed time series is unavailable.",
      );
    }
  }

  return (
    <main
      className="registry-shell research-shell"
      id="main-content"
      tabIndex={-1}
    >
      <header>
        <Link href="/dashboard">
          <ArrowLeft size={16} /> Dashboard
        </Link>
        <span>
          <ShieldCheck size={15} /> Threshold-suppressed access
        </span>
      </header>
      <section className="registry-heading">
        <p className="eyebrow">R12 · POPULATION & RESEARCH</p>
        <h1>De-identified aggregate</h1>
        <p>
          Authorized descriptive totals only. Small cohorts are suppressed and
          no individual rows, identifiers, dates, profiles, or scan contents are
          exposed.
        </p>
      </section>
      {message && (
        <p className="assistant-error" role="status">
          {message}
        </p>
      )}
      {aggregate?.state === "INSUFFICIENT_COHORT" && (
        <section className="card cohort-suppressed">
          <Users size={30} />
          <h2>Aggregate suppressed</h2>
          <p>
            At least {aggregate.minimum_cohort} distinct diary users are
            required. The current count is intentionally not returned.
          </p>
        </section>
      )}
      {aggregate?.state === "AVAILABLE" && aggregate.nutrient_totals && (
        <>
          <div className="research-kpis">
            <article className="card">
              <span>De-identified users</span>
              <strong>{aggregate.deidentified_user_count}</strong>
            </article>
            <article className="card">
              <span>Diary entries</span>
              <strong>{aggregate.diary_entry_count}</strong>
            </article>
            <article className="card">
              <span>Total energy logged</span>
              <strong>
                {Math.round(
                  aggregate.nutrient_totals.calories,
                ).toLocaleString()}{" "}
                kcal
              </strong>
            </article>
          </div>
          <section className="card research-totals">
            <h2>Logged nutrient totals</h2>
            <div>
              {Object.entries(aggregate.nutrient_totals).map(
                ([name, value]) => (
                  <span key={name}>
                    <small>{name.replaceAll("_", " ")}</small>
                    <strong>{value.toLocaleString()}</strong>
                  </span>
                ),
              )}
            </div>
          </section>
          <p className="compare-note">
            <ShieldCheck size={16} /> {aggregate.limitation}
          </p>
        </>
      )}
      <section className="card country-comparison">
        <div className="country-comparison-heading">
          <div>
            <p className="eyebrow">FAOSTAT FOOD BALANCES</p>
            <h2>Country supply comparison</h2>
          </div>
          <BarChart3 aria-hidden="true" />
        </div>
        <p>
          Compare annual national food-supply availability. These figures do not
          measure what an individual ate and are never used to rank health.
        </p>
        {catalog && (
          <div className="country-controls">
            {countryCodes.map((code, index) => (
              <label key={index}>
                Country {index + 1}
                <select
                  value={code}
                  onChange={(event) => {
                    const next: [string, string] = [...countryCodes];
                    next[index] = event.target.value;
                    setCountryCodes(next);
                  }}
                >
                  {catalog.countries.map((country) => (
                    <option key={country.m49_code} value={country.m49_code}>
                      {country.country}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <label>
              Year
              <select
                value={year}
                onChange={(event) => setYear(Number(event.target.value))}
              >
                {Array.from(
                  { length: catalog.latest_year - catalog.first_year + 1 },
                  (_, index) => catalog.latest_year - index,
                ).map((availableYear) => (
                  <option key={availableYear} value={availableYear}>
                    {availableYear}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="primary-btn"
              onClick={() => void compareCountries()}
            >
              Compare
            </button>
          </div>
        )}
        {countryMessage && (
          <p className="assistant-error" role="status">
            {countryMessage}
          </p>
        )}
        {comparison && (
          <>
            <div className="country-results">
              {comparison.records.map((record) => (
                <article key={record.m49_code}>
                  <h3>{record.country}</h3>
                  <span>
                    <small>Food energy supply</small>
                    <strong>
                      {record.values.food_supply_kcal_per_capita_day?.toLocaleString() ??
                        "—"}{" "}
                      kcal/person/day
                    </strong>
                  </span>
                  <span>
                    <small>Protein supply</small>
                    <strong>
                      {record.values.protein_supply_g_per_capita_day?.toLocaleString() ??
                        "—"}{" "}
                      g/person/day
                    </strong>
                  </span>
                  <span>
                    <small>Fat supply</small>
                    <strong>
                      {record.values.fat_supply_g_per_capita_day?.toLocaleString() ??
                        "—"}{" "}
                      g/person/day
                    </strong>
                  </span>
                  <p>
                    Source flags:{" "}
                    {Object.values(record.quality_flags).join(", ") ||
                      "None reported"}
                  </p>
                </article>
              ))}
            </div>
            <div className="country-evidence">
              {comparison.limitations.map((limitation) => (
                <p key={limitation}>{limitation}</p>
              ))}
              <a
                href={comparison.source.catalog_url}
                target="_blank"
                rel="noreferrer"
              >
                {comparison.source.citation}
              </a>
            </div>
          </>
        )}
        {catalog && (
          <div className="trend-controls">
            <label>
              Historical indicator
              <select
                value={trendIndicator}
                onChange={(event) =>
                  setTrendIndicator(event.target.value as IndicatorId)
                }
              >
                <option value="food_supply_kcal_per_capita_day">
                  Food energy supply
                </option>
                <option value="protein_supply_g_per_capita_day">
                  Protein supply
                </option>
                <option value="fat_supply_g_per_capita_day">Fat supply</option>
              </select>
            </label>
            <button
              type="button"
              className="secondary-btn"
              onClick={() => void loadTrend()}
            >
              Show {catalog.first_year}–{catalog.latest_year} history
            </button>
          </div>
        )}
        {trend && (
          <div className="country-trend">
            <h3>Descriptive history · {trend.unit}</h3>
            <div className="country-trend-scroll">
              <table>
                <thead>
                  <tr>
                    <th scope="col">Year</th>
                    {trend.series.map((series) => (
                      <th scope="col" key={series.m49_code}>
                        {series.country}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {trend.series[0].points.map((point, pointIndex) => (
                    <tr key={point.year}>
                      <th scope="row">{point.year}</th>
                      {trend.series.map((series) => {
                        const seriesPoint = series.points[pointIndex];
                        return (
                          <td
                            key={series.m49_code}
                            title={
                              seriesPoint.quality_flag
                                ? `FAOSTAT flag: ${seriesPoint.quality_flag}`
                                : undefined
                            }
                          >
                            {seriesPoint.value?.toLocaleString() ?? "—"}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>{trend.limitations.at(-1)}</p>
          </div>
        )}
      </section>
    </main>
  );
}
