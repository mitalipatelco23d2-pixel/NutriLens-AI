# Commit Conventions

Use `type(scope): imperative description`.

Supported types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `data`, `model`, `security`, and `ci`.

Examples:

- `feat(scanner): add image upload endpoint`
- `model(ocr): prepare PaddleOCR interface`
- `security(auth): strengthen input validation`
- `data(off): prepare Open Food Facts import directory`
- `test(api): add service health tests`
- `ci(web): add Next.js build verification`

Do not use a `feat` commit to introduce capabilities outside the frozen register.
