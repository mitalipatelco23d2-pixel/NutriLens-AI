# Main-branch prototypes preserved for review

This directory preserves untested prototype source from the team repository's
main-only commits so it remains easy to inspect without being part of the
tested NutriLens demo runtime.

- `backend/` comes from commit `1a404d66188f8709a53cb08d4c8ad5c5979922ff`
  (`Add NutriLens AI ML and analysis services`).
- `frontend/` comes from commit `4a714428e36919c418bf31cdd63d11f3bbe3fcbc`
  (`Add M3 NutriLens frontend`).

The active application uses the reviewed integration implementations under
`backend/app/` and `frontend/web/`. These archived files are not imported,
built, tested, or supported by the demo. Their logic is preserved unchanged
for team review; activating any portion requires a separate design and test
decision.

The two Git LFS model copies from the main-only ML commit are intentionally not
duplicated here. The demo privately provisions its verified model, vectorizer,
and knowledge-base artifacts at the paths documented in the root README.
