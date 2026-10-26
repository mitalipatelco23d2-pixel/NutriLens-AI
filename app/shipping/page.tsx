import type { Metadata } from "next";
import { LegalPage } from "@/components/legal-page";

export const metadata: Metadata = { title: "Shipping Policy | NutriLens X" };

export default function ShippingPage() {
  return (
    <LegalPage title="Shipping Policy" updated="27 August 2026">
      <h2>Digital service only</h2>
      <p>
        NutriLens sells access to software subscription features. It does not
        sell or ship food, supplements, devices, or other physical goods, so
        physical shipping fees and delivery tracking do not apply.
      </p>
      <h2>Digital access</h2>
      <p>
        Subscription access is updated only after NutriLens verifies the
        payment-provider signature and lifecycle event. A checkout screen by
        itself does not prove activation. Provider or network delays can delay
        the account update; the billing page remains the authoritative status.
      </p>
      <h2>Current payment mode</h2>
      <p>
        The public preview remains in Razorpay Test Mode until owner-controlled
        activation, policy approval, and live-provider verification are
        complete. Test transactions do not move real funds.
      </p>
    </LegalPage>
  );
}
