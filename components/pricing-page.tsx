"use client";

import Link from "next/link";
import { Check, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

const plans = [
  {
    name: "FREE",
    monthly: 0,
    annual: 0,
    copy: "Start understanding everyday food.",
    features: [
      "10 complete scans / month",
      "Ingredient and nutrition intelligence",
      "Allergens and safety evidence",
      "Basic diary, pantry and analytics",
    ],
  },
  {
    name: "PLUS",
    monthly: 79,
    annual: 799,
    copy: "For regular NutriLens users.",
    features: [
      "100 scans / month",
      "Longer diary and analytics history",
      "Richer alternatives and pantry tools",
      "Expanded assistant allowance",
    ],
  },
  {
    name: "PRO",
    monthly: 149,
    annual: 1499,
    copy: "Advanced intelligence, made personal.",
    popular: true,
    features: [
      "300 scans / month",
      "Advanced personalization",
      "Detailed explainability",
      "Full nutrient trends and recommendations",
    ],
  },
  {
    name: "MAX",
    monthly: 249,
    annual: 2499,
    copy: "For power users who want full access.",
    features: [
      "1,000 scans / month",
      "Highest assistant allowance",
      "Complete consumer history",
      "Advanced exports",
    ],
  },
];

export function PricingPage() {
  const router = useRouter();
  const [annual, setAnnual] = useState(false);
  const [checkoutMessage, setCheckoutMessage] = useState("");

  const choosePlan = (plan: string) => {
    if (plan === "FREE") {
      router.push("/dashboard");
      return;
    }
    setCheckoutMessage(
      `${plan} is coming soon. No payment is being accepted during the initial public release.`,
    );
  };

  return (
    <div className="pricing-shell">
      <header className="simple-nav">
        <Link className="brand-link" href="/">
          NutriLens <span>X</span>
        </Link>
        <Link href="/">Back to home</Link>
      </header>
      <main className="pricing-main" id="main-content" tabIndex={-1}>
        <p className="section-kicker">Straightforward plans</p>
        <h1>Core food safety stays free. Upgrade for depth.</h1>
        <p>
          Choose a plan for your usage and personalization needs. All allowances
          are finite and abuse-safe.
        </p>
        <div
          className="billing-toggle"
          role="group"
          aria-label="Billing interval"
        >
          <button
            className={!annual ? "active" : ""}
            onClick={() => setAnnual(false)}
          >
            Monthly
          </button>
          <button
            className={annual ? "active" : ""}
            onClick={() => setAnnual(true)}
          >
            Yearly <span>Save up to 16%</span>
          </button>
        </div>
        <div className="pricing-grid">
          {plans.map((plan) => (
            <article
              className={plan.popular ? "price-card popular" : "price-card"}
              key={plan.name}
            >
              {plan.popular && (
                <div className="popular-label">
                  <Sparkles size={13} /> MOST POPULAR
                </div>
              )}
              <h2>{plan.name}</h2>
              <p>{plan.copy}</p>
              <div className="price">
                <span>₹</span>
                <strong>{annual ? plan.annual : plan.monthly}</strong>
                <small>{annual ? "/year" : "/month"}</small>
              </div>
              {annual && plan.monthly > 0 && (
                <p className="saving">
                  ₹{Math.round(plan.annual / 12)} effective monthly
                </p>
              )}
              <button
                className="plan-action"
                onClick={() => choosePlan(plan.name)}
              >
                {plan.name === "FREE"
                  ? "Start free"
                  : `${plan.name} coming soon`}
              </button>
              <ul>
                {plan.features.map((feature) => (
                  <li key={feature}>
                    <Check size={15} />
                    {feature}
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
        {checkoutMessage && (
          <p className="checkout-message" role="status">
            {checkoutMessage}
          </p>
        )}
        <p className="renewal-copy">
          Paid checkout is disabled until Razorpay Live approval and release
          validation are complete. No real or Test-mode payment is requested
          from public users. No literal unlimited AI inference is promised.
        </p>
      </main>
    </div>
  );
}
