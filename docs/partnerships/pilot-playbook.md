# NutriLens X pilot playbook

Status: owner-review planning document. It creates no commercial, legal or
clinical commitment.

## Shared pilot guardrails

Every pilot must be opt-in, general-wellness only, limited to verified product
capabilities, and preceded by a go/no-go check covering product readiness,
privacy notice, contact ownership, operational capacity and support. Partners do
not receive identifiable user data. Health Connect is excluded from partner
reporting. No result ranking or interpretation can be sponsored.

Minimum launch gates:

1. the selected web/Android flow is `READY_PUBLIC` or explicitly
   `READY_WITH_FALLBACK` for the proposed participants;
2. authentication, account deletion and owner isolation are production tested;
3. support and incident contacts are staffed for the pilot window;
4. the invitation, consent/notice and feedback survey are approved;
5. capacity matches the participant schedule without buying infrastructure;
6. no partner logo or endorsement is published without written permission.

## A. College nutrition-awareness pilot

**Audience:** an adult student club, campus wellness program or innovation cell.
**Format:** one label-literacy session, a two-week opt-in scan challenge and an
anonymous clarity survey.
**Primary metric:** share of invited users who complete one useful scan.
**Secondary metrics:** structured-result completion, participant-rated clarity,
user-initiated next action, support tickets and fallback rate.
**Not measured:** weight loss, clinical outcomes or individual eating behavior.
**Partner role:** invitation, room/link, one coordinator and participant-safety
escalation route.
**NutriLens role:** demo, product access, support and aggregate operational
summary if legally approved.

## B. Gym member nutrition-tracking pilot

**Audience:** adult members in a voluntary education cohort.
**Format:** trainer-led orientation on serving evidence, followed by two weeks of
optional label scans and verified diary actions.
**Primary metric:** first useful scan plus a deliberate user action.
**Guardrail:** trainers do not receive member-level records through the pilot;
NutriLens does not prescribe diets or promise performance/weight outcomes.

## C. Dietitian companion-tool pilot

**Audience:** registered/qualified dietetic professionals who evaluate the tool,
not patients receiving automated treatment.
**Format:** a bounded set of de-identified or commercially obtained test labels,
structured-result review and expert error taxonomy.
**Primary metric:** percentage of labels for which reviewers say the structured
view reduces manual navigation time, reported with sample size.
**Guardrail:** no patient data, no clinical record integration and no replacement
for professional judgment.

## D. Cafeteria or canteen nutrition-awareness pilot

**Audience:** adult diners and cafeteria operations staff.
**Format:** scan only packaged products with readable manufacturer labels; place
a neutral QR/link near the shelf after permission.
**Primary metric:** completed scans per displayed product and reported clarity.
**Guardrail:** do not infer unlabelled recipe nutrition, do not create health
scores for vendors, and do not present a cafeteria as endorsed.

## E. Consumer food-label transparency pilot

**Audience:** a packaged-food brand willing to provide authorized package images
or current label data for independent testing.
**Format:** compare NutriLens extraction with the package's declared table across
an agreed set of SKUs and layouts.
**Primary metric:** field-level structured recovery and provenance completeness,
with corrections disclosed.
**Guardrail:** the brand cannot approve or purchase a favorable interpretation;
public use of results or trademarks requires separate written permission.

## F. Aggregated research-insights concept

Status: `BLOCKED_LEGAL` until privacy/legal/research review. This is not an
initial public-release offer.

Permissible future questions may concern sufficiently aggregated food-category,
nutrient-distribution or ingredient-frequency trends. Direct identifiers,
user-level dossiers, private scan images and Health Connect data are prohibited.
The project requires purpose limitation, data minimization, minimum-cell
suppression, retention rules, participant notice/consent analysis, security
review and publication governance before any data work begins.

## Standard 2–4 week pilot plan

### Week 0 — qualification

- confirm partner authority, participant age boundary and release surface;
- choose one learning objective and one primary metric;
- approve invitation, participant notice, survey and support plan;
- run a small internal rehearsal with synthetic test accounts;
- record exact product version and known limitations.

### Week 1 — orientation and soft launch

- 20–30 minute product and label-literacy introduction;
- demonstrate one real package with uncertainty and disclaimer visible;
- invite a capped first cohort;
- monitor failures, not private label contents.

### Week 2 — bounded use

- invite the remaining approved cohort only if capacity is healthy;
- send at most one permissioned reminder through the partner;
- collect voluntary feedback;
- pause on security, privacy, safety or severe correctness incidents.

### Week 3/4 — closeout

- stop the pilot-specific invitation;
- aggregate only the approved metrics;
- suppress small cells and remove direct identifiers;
- review failures and participant feedback;
- decide stop, iterate or propose a separately approved next phase.

## Success metric dictionary

| Metric                    | Definition                                                                    | Guardrail                                                  |
| ------------------------- | ----------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Invite-to-signup          | Unique pilot invitees who create an account / valid invitees                  | Requires a lawful, privacy-respecting attribution method   |
| First useful scan         | Account receives one completed structured result with useful evidence         | OCR success alone does not qualify                         |
| Time to useful insight    | Image selection/capture to first useful interpretation rendered               | Report client and fallback paths separately                |
| Next action               | Explicit save/diary/pantry/Ask action on a release-verified surface           | A scan does not imply consumption                          |
| Completion rate           | Completed eligible jobs / accepted eligible jobs                              | Report failures and timeouts, not only successes           |
| Fallback rate             | Enhanced server fallback jobs / eligible scan attempts                        | Separate client evidence acceptance from server completion |
| Clarity score             | Voluntary post-task response to a predeclared question                        | Report question, scale, N and missing responses            |
| Safety defect             | Missed or materially wrong explicit allergen evidence in reviewed test labels | Escalate; do not average away critical defects             |
| Privacy/security incident | Unauthorized access, leakage or misuse event                                  | Immediate pause and incident process                       |

Never use “users improved their health” or “reduced disease risk” as a pilot
success metric without a separate validated clinical/research design.

## Stop conditions

Pause the pilot for a critical owner-isolation failure, material privacy issue,
unresolved allergen-safety defect, misleading public claim, unsupported partner
data request, capacity instability that harms ordinary users, or a requested
financial/legal commitment outside the approved scope.

## Closeout deliverable

One page containing cohort size, exact product version, eligibility/exclusions,
accepted/completed/failed counts, client/fallback split, latency distribution,
support incidents, structured correctness review, feedback response rate,
privacy notes, limitations and a recommendation of `STOP`, `ITERATE` or
`PROPOSE_NEXT_PHASE`.
