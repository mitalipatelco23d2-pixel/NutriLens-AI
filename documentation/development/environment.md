# Environment Variables

Copy `.env.example` to `.env`. The example contains development-only values and variable names, not production secrets. `.env` and all local overrides are ignored by Git.

`NEXT_PUBLIC_API_URL` is public and embedded into the web bundle. Database URLs, JWT configuration and credentials must never use a `NEXT_PUBLIC_` prefix. Mobile configuration uses `--dart-define=API_BASE_URL=...` and defaults to the Android emulator loopback alias.

Before any non-local use, rotate every development credential and generate a high-entropy JWT secret. Logs must not include connection strings, tokens, health profiles, images, OCR text, or ingredient histories.
