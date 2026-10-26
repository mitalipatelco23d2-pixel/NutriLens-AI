import { LegalPage } from "@/components/legal-page";

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy Policy" updated="8 September 2026">
      <h2>What NutriLens collects</h2>
      <p>
        NutriLens stores account identifiers, date of birth, optional phone and
        region, preferences you choose to provide, scans, diary entries, pantry
        data, and billing metadata needed to operate the service. Optional phone
        numbers are unverified until a real provider verifies them. It does not
        store card or bank credentials.
      </p>
      <h2>How information is used</h2>
      <p>
        Information is used to provide food intelligence, personalization,
        account security, entitlement enforcement, product analytics, and
        support. Wellness data is not used to claim a diagnosis.
      </p>
      <h2>Food-label images and on-device processing</h2>
      <p>
        Supported Android versions may read label text on your device to prepare
        a scan. During the current validation rollout, and whenever an enhanced
        fallback is needed, the image is also sent securely to NutriLens for
        processing. Raw scan images are not retained after processing; the
        structured scan result may be saved to your private history. NutriLens
        does not claim that every scan remains only on your device.
      </p>
      <h2>Camera and microphone</h2>
      <p>
        Camera access is used only when you choose to capture a food image.
        Microphone access is used only when you choose voice input. You can use
        gallery upload and typed input instead where those controls are
        available.
      </p>
      <h2>Google sign-in</h2>
      <p>
        Google authenticates your identity. NutriLens receives a verified
        account identifier, email, display name, and avatar where available; it
        never receives or stores your Google password.
      </p>
      <h2>Payment processing</h2>
      <p>
        Razorpay processes payment authorization. NutriLens stores provider
        references, status, amount, currency, and lifecycle events required for
        reconciliation.
      </p>
      <h2>Your controls</h2>
      <p>
        You may request access, export where available, scan deletion, account
        deletion, and associated data deletion. Some transaction records may
        need to be retained where legally required.
      </p>
      <h2>Research access</h2>
      <p>
        Population and research tools are restricted to authorized roles. Public
        research outputs must use aggregated or de-identified information and
        must not expose an individual’s records.
      </p>
      <h2>Security and limitations</h2>
      <p>
        NutriLens uses authorization, secure transport, input validation and
        secret management. No system can promise absolute security, and this
        policy does not claim an unaudited regulatory certification.
      </p>
      <h2>Contact</h2>
      <p>
        Privacy contact details will be published before public launch by Yash
        AI Technologies.
      </p>
    </LegalPage>
  );
}
