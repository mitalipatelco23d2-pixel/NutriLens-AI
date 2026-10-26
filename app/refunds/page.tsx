import type { Metadata } from "next";
import { LegalPage } from "@/components/legal-page";

export const metadata: Metadata = {
  title: "Cancellation and Refunds | NutriLens X",
};

export default function RefundsPage() {
  return (
    <LegalPage title="Cancellation and Refunds" updated="27 August 2026">
      <h2>Cancellation</h2>
      <p>
        An eligible account can request cancellation from Account &amp; Billing.
        NutriLens sends a cycle-end cancellation request to the provider and
        shows the provider-confirmed lifecycle status. Access and renewal
        behavior follow that confirmed status.
      </p>
      <h2>Resuming</h2>
      <p>
        Where the provider permits it, a cycle-end cancellation can be resumed
        from Account &amp; Billing before it takes effect. NutriLens never
        treats an unverified client response as authoritative.
      </p>
      <h2>Refunds and disputes</h2>
      <p>
        No real payment is currently accepted because checkout is restricted to
        Razorpay Test Mode. Before Live Mode, NutriLens X must approve
        and publish the final refund-eligibility window, processing timeline,
        business contact, and legally required dispute terms. Live charging is
        blocked until that owner review is complete.
      </p>
    </LegalPage>
  );
}
