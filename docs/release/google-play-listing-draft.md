# Google Play listing draft

Status: copy and owner-independent assets prepared; not submitted.

## Store copy

**Title**  
NutriLens X

**Short description**  
Scan food labels and review structured nutrition and ingredient evidence.

**Full description**

NutriLens X helps you understand packaged-food labels and keep your own food
records in one place. Capture or choose a label image, review extracted
nutrition, ingredient and allergen evidence, and save results to your private
history.

Use NutriLens X to:

- read nutrition panels and serving information;
- review package ingredient and allergen statements;
- organize scans, pantry items and diary entries;
- explore evidence-linked food information and bounded alternatives;
- keep your records synchronized across supported NutriLens experiences.

On supported Android devices, label text may be read locally first. When the
image is unclear or enhanced processing is needed, the selected image and OCR
evidence may be sent securely to NutriLens servers. Results can contain
uncertainty; always check the physical package, especially for allergies.

NutriLens X provides general nutrition and wellness decision support. It does
not diagnose, treat, cure or prevent any medical condition and is not a medical
device.

## Classification and policy preparation

- App category: Health & Fitness.
- Health declaration: Nutrition and weight management; no medical-device claim.
- Ads: no advertising SDK is currently declared; verify final AAB.
- Target audience: general users; do not market as a children-directed app.
- Content rating: utility/wellness functionality with user-provided food images;
  complete the Play questionnaire from actual final behavior.
- Privacy policy: `https://nutrilensx.tech/privacy`.
- Support page: `https://nutrilensx.tech/contact`; final support email still
  requires an organization-owned configured address.

## Reviewer access draft

Do not provide owner credentials and do not disable authentication globally.
Before review, create a dedicated least-privilege reviewer account with verified
email, no billing privilege, no owner/admin role, and representative private test
records. Put its time-bounded credentials only in Play Console App Access
instructions. Confirm the account can reach scanning, history, pantry, diary and
assistant surfaces without exposing another user's records.

## Asset inventory

- Play icon: `play-assets/nutrilens-x-play-icon-512.png` (512×512 PNG).
- Feature graphic: `play-assets/nutrilens-x-feature-graphic-1024x500.png`.
- Android adaptive/legacy launcher icons: generated from the in-repository
  `apps/mobile/assets/branding/nutrilens-mark-master.png` source.
- Phone/tablet screenshots: pending a signed physical-device or internal-track
  run; emulator validation screenshots are not being mislabeled as physical or
  production proof.

Do not expose “v1” in customer-facing text and do not mention Azure, PaddleOCR,
workers or model-license internals in normal store copy.
