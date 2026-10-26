import type { Metadata } from "next";
import { LegalPage } from "@/components/legal-page";

export const metadata: Metadata = { title: "Contact | NutriLens X" };

export default function ContactPage() {
  const supportEmail = process.env.NEXT_PUBLIC_SUPPORT_EMAIL;
  return (
    <LegalPage title="Contact Us" updated="27 August 2026">
      <h2>Product Support</h2>
      <p>NutriLens X consumer nutrition and wellness support.</p>
      <h2>Customer and billing support</h2>
      {supportEmail ? (
        <p>
          Email <a href={`mailto:${supportEmail}`}>{supportEmail}</a>. Include
          your NutriLens account email and a provider reference where relevant,
          but never send passwords, OTPs, card details, or API keys.
        </p>
      ) : (
        <p>
          The organization-owned support address is pending public launch. Paid
          Live Mode remains disabled until that address and the final business
          details are published.
        </p>
      )}
      <h2>Safety</h2>
      <p>
        NutriLens is not an emergency or medical service. For a suspected
        allergic reaction or medical emergency, contact local emergency care.
      </p>
    </LegalPage>
  );
}
