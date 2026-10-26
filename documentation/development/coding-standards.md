# Coding Standards

## Shared rules

- Never commit secrets, real health profiles, or private food histories.
- Clearly label demonstrations and scaffolds; never present hardcoded AI output as trained inference.
- Preserve the wellness boundary and provide actionable errors without leaking internals.
- Prefer small, typed, testable units and comments that explain decisions rather than syntax.

## Python and FastAPI

Use `snake_case`, type every public function, separate routes from service/database logic, catch failures at service boundaries, log structured operational facts without sensitive payloads, and test healthy and degraded behavior. Ruff is the formatter and linter; mypy is the type checker; pytest is the test runner.

## TypeScript and Next.js

Use strict types, `PascalCase` components, `camelCase` functions, semantic HTML, accessible labels and keyboard interactions. Keep API calls behind typed abstractions, handle loading/error/empty states, and avoid unsafe assertions. Use ESLint, TypeScript and Prettier.

## Dart and Flutter

Follow Effective Dart naming, keep widgets focused, separate API clients and configuration from presentation, expose errors in user-friendly language, provide semantics for interactive controls, and cover the navigation shell and service state with widget/unit tests. Use `dart format`, `flutter analyze`, and `flutter test`.
