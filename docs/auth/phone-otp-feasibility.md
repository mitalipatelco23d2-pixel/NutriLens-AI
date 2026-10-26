# Phone OTP feasibility

Status: `BLOCKED_EXTERNAL_COST`

Google sign-in and email authentication remain the required production
baseline. No paid SMS service, billing account, phone-auth provider, phone
number collection, or SMS-related Android permission was added.

## Why production phone OTP is not enabled

Firebase's current official limits state that verification-code SMS requires
the pay-as-you-go Blaze plan. Its pricing page states that Phone Auth is billed
per SMS sent. Phone Number Verification likewise requires a billing account for
production use; its SIM-less test mode is suitable for development, not real
public phone ownership proof.

Therefore there is no evidence for a reliable, abuse-resistant, zero-cost
production SMS OTP path. Enabling it now would violate the no-unapproved-SMS-
spend constraint.

## Safe development path

- Provider-supplied fictional/test phone numbers or SIM-less test mode may be
  used only in isolated development.
- Tests must never send a real SMS or treat a test identity as production proof.
- Do not request `READ_SMS`, `RECEIVE_SMS`, call-log, or contacts permissions.
- Phone numbers would be personal data and require privacy/Data Safety updates
  before a real rollout.

## Reconsideration gate

Owner approval is required for a provider and billing account. Before enabling
real messages, record regional per-message rates, a hard budget/alert strategy,
rate limits per account/IP/number/device, bot and SIM-swap threat controls,
recovery rules, deletion/retention, provider processing terms, and an emergency
disable switch. Then validate with a tiny explicitly approved test budget.

## Official references

- [Firebase Authentication limits](https://firebase.google.com/docs/auth/limits)
- [Firebase pricing](https://firebase.google.com/pricing)
- [Firebase Phone Number Verification pricing](https://firebase.google.com/docs/phone-number-verification/pricing)
