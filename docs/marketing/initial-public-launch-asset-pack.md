# NutriLens X initial public launch asset pack

Status: `READY_MARKETING` as draft copy only. Publication remains gated on the
release readiness decision. Nothing in this file has been published.

Owner: Yash AI Technologies
Public product name: NutriLens X
Core positioning: **Understand what your food label actually means.**

## Truth boundary for every asset

The current evidence supports saying that NutriLens X can accept an authenticated
food-label scan, preserve an owner-scoped durable job, extract structured
nutrition, ingredient and explicit allergen evidence, and retain a private
result. An Android physical-device shadow run recovered a per-100-ml nutrition
table and a milk allergen statement from a real package. Authentication and
private account records exist on the public service.

The following must not be implied until the corresponding release gate is green:

- no Play Store availability claim or Play link before the listing is live;
- no “instant,” “always accurate,” or broad speed promise: the enhanced server
  fallback remains asynchronous and can be materially slower;
- no claim that the Android preferred local fast path, Ask Nutri Android, Health
  Connect, reminders, or every diary/pantry/recipe action passed final release QA;
- no medical diagnosis, disease treatment, allergy-safety, or guaranteed weight
  outcome claim;
- no implication that OCR confidence equals correct structured interpretation;
- no traction, user-count, accuracy-rate or retention metric without measured
  production data;
- no “AI nutritionist” label. Ask Nutri must remain evidence-bounded;
- no use of a fabricated screenshot, result, testimonial, partner logo or store
  badge.

Replace `[PUBLIC_WEB_URL]`, `[DEMO_URL]`, `[SUPPORT_EMAIL]` and
`[PLAY_STORE_URL]` only with verified live values. Until Android is public, use
the web CTA and omit the Play CTA entirely.

## A. Primary launch tagline

**Understand what your food label actually means.**

## B. Alternative taglines

1. **Scan the label. See what matters.**
2. **From packaged-food label to useful nutrition evidence.**
3. **Read the serving, ingredients and allergen signals—not the fine print.**

## C. Landing-page hero copy

### Headline

Understand what your food label actually means.

### Supporting copy

Scan a packaged-food label to organize its nutrition, serving, ingredient and
allergen evidence into a clearer result. Save the result to your private account
and use it as a starting point for better-informed food decisions.

### Primary CTA

**Try NutriLens X on the web** → `[PUBLIC_WEB_URL]`

### Secondary CTA

**See how a scan works** → `[DEMO_URL]`

### Trust line

Results can contain uncertainty. Always verify the physical package—especially
for allergies. NutriLens X provides general wellness information, not medical
advice.

## D. Feature bullets

- **Turn label text into structure.** Review nutrition rows, serving basis,
  ingredients and explicit allergen statements in one result.
- **Keep the evidence visible.** Important findings remain tied to package text
  and provenance instead of becoming unsupported health claims.
- **Continue after a refresh.** Enhanced scans use durable, owner-scoped jobs so
  processing can continue in the background.
- **Keep records private to the account.** Saved scan results and related records
  are authenticated and owner scoped.
- **Build useful food records.** Organize scans alongside supported history,
  pantry and diary records; verify the exact surface on the release device before
  publishing screenshots.
- **Use honest uncertainty.** Missing or uncertain values remain unknown rather
  than silently becoming zero.

## E. 15-second demo script

**Visual:** Pick a packaged-food label, then show the structured result.
**Voiceover:** “Food labels are dense. NutriLens X turns a label into clear
nutrition, serving, ingredient and allergen evidence—so you can see what matters
without reading every line of fine print.”
**End card:** “Understand what your food label actually means.”

Production note: use a real completed result; do not promise that all scans finish
within 15 seconds.

## F. 30-second demo script

**0–5 s:** “What does this packaged-food label actually say?”
**5–12 s:** Select a clear photo and show the honest processing state.
**12–22 s:** Reveal the product header, serving basis, nutrition table,
ingredients and prominent allergen evidence.
**22–27 s:** Show a private saved result or a verified available action.
**27–30 s:** “NutriLens X. Scan the label. See what matters.”

On-screen footer: “Results may contain uncertainty. Verify the package,
especially for allergies. General wellness information only.”

## G. 60-second founder/demo script

“Packaged-food labels contain useful information, but serving columns, units,
ingredients and warnings can be hard to compare at a glance. I built NutriLens X
to make that evidence easier to work with.

Here is a real label scan. I choose the image, NutriLens reads the available
label evidence, and the result organizes the serving basis, nutrition rows,
ingredients and explicit allergen statements. The evidence stays separate from
the interpretation, and uncertain values remain uncertain.

The result is saved to the authenticated user’s private account. Enhanced scans
can continue as background jobs, so a refresh does not need to restart the
inference.

NutriLens X is a general nutrition and wellness tool—not a medical device, and
not a substitute for the physical package or professional advice. The goal is
simple: scan the label, see what matters, and make your next food decision with
better evidence.”

End card: “NutriLens X by Yash AI Technologies · `[PUBLIC_WEB_URL]`”

## H. Google Play short description

Scan food labels and review structured nutrition and ingredient evidence.

This is 74 characters and matches the existing Play listing draft.

## I. Google Play full description

NutriLens X helps you understand packaged-food labels and keep your own food
records in one place. Capture or choose a label image, review extracted
nutrition, ingredient and allergen evidence, and save results to your private
history.

Use NutriLens X to:

- read nutrition panels and serving information;
- review package ingredient and allergen statements;
- organize scans, pantry items and diary entries on supported surfaces;
- explore evidence-linked food information;
- keep supported records synchronized across NutriLens experiences.

On supported Android devices, label text may be read locally first. When the
image is unclear or enhanced processing is needed, the selected image and
bounded OCR evidence may be sent securely to NutriLens servers. Results can
contain uncertainty; always check the physical package, especially for
allergies.

NutriLens X provides general nutrition and wellness decision support. It does
not diagnose, treat, cure or prevent any medical condition and is not a medical
device.

Release note: use this only after the signed AAB, final SDK/permission audit,
physical-device pass and Play Console review material are complete.

## J. X / Twitter launch post

Food labels should not require a spreadsheet.

Today I’m introducing NutriLens X: scan a packaged-food label and review its
serving, nutrition, ingredient and allergen evidence in a clearer result.

Built by Yash AI Technologies. Try it: `[PUBLIC_WEB_URL]`

Results may contain uncertainty—always verify the package, especially for
allergies. #Nutrition #BuildInPublic

## K. LinkedIn launch post

Today I’m sharing NutriLens X, built around one question: **what does this food
label actually mean?**

The product turns a user-provided packaged-food label into a structured view of
serving context, nutrition rows, ingredients and explicit allergen evidence. A
completed result belongs to the authenticated user, and enhanced scans use
durable background jobs rather than tying the work to one page load.

The deliberate product choice is evidence before hype. Unknown values stay
unknown, provenance matters, and the experience is general wellness support—not
medical diagnosis or a guarantee that a food is safe for someone.

NutriLens X is a Yash AI Technologies product. Explore the public web experience:
`[PUBLIC_WEB_URL]`

I’d especially value feedback on clarity: after one scan, is the label easier to
understand and act on?

## L. Instagram caption

Small text. Multiple serving columns. Ingredients. Allergen warnings. 👀

NutriLens X helps turn a packaged-food label into a clearer view of what the
package reports—nutrition, serving context, ingredients and allergen evidence.

Scan the label. See what matters. `[PUBLIC_WEB_URL]`

Always verify the physical package, especially for allergies. General wellness
information only.

#NutriLensX #FoodLabels #NutritionAwareness #BuildInIndia

## M. WhatsApp / share message

I’ve been building NutriLens X, a tool that helps organize packaged-food label
information into clearer nutrition, serving, ingredient and allergen evidence.
If you try it, I’d love one piece of honest feedback: did the result make the
label easier to understand? `[PUBLIC_WEB_URL]`

Please verify the physical package for important decisions, especially
allergies.

## N. College-community launch message

Hi everyone—I'm inviting a small college community to try NutriLens X, a product
from Yash AI Technologies focused on food-label literacy.

The pilot is simple: scan a packaged-food label you already have, review the
structured serving/nutrition/ingredient evidence, and tell us what was clear or
confusing. Participation is optional, and this is a general wellness tool—not
medical advice. We will not ask a college or club for identifiable participant
nutrition data.

Demo: `[DEMO_URL]`
Try it: `[PUBLIC_WEB_URL]`
Feedback/contact: `[SUPPORT_EMAIL]`

## O. Reddit / community-style non-spam announcement

**Title:** I built a food-label reader that tries to show evidence before advice

I’m working on NutriLens X because nutrition panels are surprisingly difficult
to read at a glance—especially when a package mixes per-100-unit and per-serving
columns.

The current product accepts a label photo and organizes available serving,
nutrition, ingredient and explicit allergen evidence. I’m intentionally not
calling it a medical tool or claiming perfect extraction. Results can be wrong,
unknown values stay unknown, and the package remains the source of truth.

If the community rules permit product feedback, I’d appreciate testing on clear,
ordinary Indian packaged-food labels: `[PUBLIC_WEB_URL]`. I’m most interested in
whether the result is easier to understand, not sign-up counts. I’ll remove this
if launch posts are not allowed here.

## P. Product Hunt-style launch copy

### Name

NutriLens X

### Tagline

Understand what your packaged-food label actually means.

### Description

NutriLens X turns a user-provided food-label image into a structured view of
serving context, nutrition rows, ingredients and explicit allergen evidence.
Results are saved to the authenticated user’s private account, and enhanced
processing can continue as a durable background job. It is evidence-first
general wellness software, not a medical device.

### Maker comment

“I built NutriLens X after seeing how easily useful label evidence gets buried in
small print, mixed serving columns and long ingredient blocks. The hardest part
was not reading text—it was preserving structure, provenance and uncertainty.
For this first release, I’d love feedback on one question: after scanning a real
package, what part of the result helped most, and what still felt unclear?”

Use only when the community rules and release gate permit it. Do not claim the
Product Hunt launch itself until submitted.

## Q. Email announcement

**Subject:** Introducing NutriLens X: understand what your food label reports

Hi,

I’m introducing NutriLens X, a product from Yash AI Technologies that helps make
packaged-food labels easier to understand.

Choose a label image and NutriLens X organizes the available serving, nutrition,
ingredient and explicit allergen evidence into a clearer result. Completed
results stay in the authenticated user’s private account.

Try it here: `[PUBLIC_WEB_URL]`
See the short demo: `[DEMO_URL]`

I’d value one practical reply: what information did you expect to see first
after the scan?

NutriLens X provides general wellness information. Results may contain
uncertainty; always verify the physical package, especially for allergies.

— Yash
Yash AI Technologies

Send only to a permissioned list. Include the legally required sender identity
and unsubscribe mechanism for any campaign distribution.

## R. Press / founder one-pager

### NutriLens X makes packaged-food label evidence easier to understand

**[CITY, India] — draft, not for distribution.** Yash AI Technologies is
preparing the initial public release of NutriLens X, a consumer nutrition and
wellness product designed to turn packaged-food labels into clearer, structured
evidence.

Instead of presenting raw OCR text, NutriLens X is designed to organize serving
context, nutrition rows, ingredients and explicit allergen statements. The
product keeps extraction confidence and provenance separate from broader
interpretation, so an uncertain value is not silently presented as fact.

An authenticated production validation on a real Indian dairy package recovered
a per-100-ml table, serving information, major nutrient rows and an explicit milk
allergen statement. The scan was owner scoped, idempotent, persisted after
completion and could be resumed after the test process restarted. This is a
single validated fixture, not a population-wide accuracy claim.

NutriLens X uses a client-first Android direction to reduce unnecessary cloud
work when conservative evidence validation permits it, with a durable enhanced
server fallback for harder labels. The public message remains about the user
benefit—not the underlying OCR or model stack.

NutriLens X is intended for general nutrition and wellness decision support. It
does not diagnose, treat, cure or prevent medical conditions, and users should
verify the physical package for important decisions, especially allergies.

**Product:** `[PUBLIC_WEB_URL]`
**Demo:** `[DEMO_URL]`
**Media contact:** `[SUPPORT_EMAIL]`

### Founder boilerplate

Yash AI Technologies builds practical, evidence-conscious software. NutriLens X
is its consumer product for understanding packaged-food labels and organizing
personal food records.

## Screenshot and demo shot list

Capture only after each surface passes the release readiness matrix. Use real
accounts with synthetic, non-sensitive test data and remove tokens, email
addresses, IDs and diagnostics.

1. Today dashboard with real test records, not seeded marketing numbers.
2. Image selection/capture and honest processing state.
3. Insight-first scan result with allergen evidence prominent.
4. Clean nutrition table with serving basis and units.
5. Ask Nutri with a cited, supported answer—only after Android release QA.
6. Diary and nutrition totals based on explicit test consumption.
7. Pantry, recipe and comparison surfaces—only if their final actions pass.
8. Goals/hydration and Settings/Health Connect—only after permission testing.

The old raw-OCR-first result must not appear. Record whether each capture is web,
debug Android, signed Android, emulator or physical-device evidence.

## Organic launch sequence and measurement

1. Public web release gate and privacy/support links.
2. Founder LinkedIn, permissioned WhatsApp network and one college/community
   pilot invitation.
3. Short real demo video, then X/Instagram variants.
4. Community posts only where rules explicitly permit launches.
5. Play CTA only after a verified public listing.

Privacy-respecting funnel events:

`visit → signup → onboarding complete → first useful scan → first user action →
diary/goal use → return`

Initial activation is `account created + first useful completed scan` or
`account created + a real diary/goal action`. Do not report a metric until event
definitions, consent/legal basis, exclusion rules and production telemetry are
verified. Do not manufacture testimonials or traction.
