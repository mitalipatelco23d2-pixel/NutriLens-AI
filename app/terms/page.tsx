import { LegalPage } from "@/components/legal-page";

export default function TermsPage() {
  return (
    <LegalPage title="Terms of Use" updated="8 September 2026">
      <h2>Wellness decision support</h2>
      <p>
        NutriLens provides nutrition and wellness information. It does not
        diagnose disease, prescribe treatment, certify food as medically safe,
        or replace a qualified professional.
      </p>
      <h2>Account responsibility</h2>
      <p>
        The current public release is for people aged 18 or older. You must
        provide an accurate date of birth when completing account setup. This
        release is not directed to children.
      </p>
      <p>
        You are responsible for activity under your account and for providing
        accurate preferences. Do not attempt to access another person’s records,
        bypass usage limits, or misuse research or administration functions.
      </p>
      <h2>Food evidence and uncertainty</h2>
      <p>
        Label extraction, ingredient resolution, nutrition estimates and
        recommendations can be incomplete. NutriLens exposes confidence and
        unknown states where evidence is insufficient. Always check the physical
        label for allergies and urgent safety decisions.
      </p>
      <h2>Subscriptions</h2>
      <p>
        Free, Plus, Pro and Max plans have configurable finite allowances. Paid
        plans renew for the selected interval until cancelled. Prices are shown
        in INR and taxes may apply. Critical allergen and safety information is
        not intentionally paywalled.
      </p>
      <h2>Payments</h2>
      <p>
        Payments are handled by Razorpay. A frontend checkout result alone does
        not activate access; verified provider signatures and subscription
        lifecycle events are authoritative.
      </p>
      <h2>Acceptable use</h2>
      <p>
        Do not upload unlawful material, probe infrastructure, automate abusive
        inference volume, or use NutriLens to make unsupported medical claims
        about others.
      </p>
      <h2>Changes and contact</h2>
      <p>
        Material changes will be reflected by an updated date. Final legal
        contact and business information will be added before public launch.
      </p>
    </LegalPage>
  );
}
