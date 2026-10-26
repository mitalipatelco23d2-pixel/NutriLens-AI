# Git Workflow

`main` represents the most stable reviewed academic baseline. `develop` is the integration branch for the next release. Work branches start from `develop` and use `feature/`, `fix/`, `docs/`, `security/`, or `chore/` prefixes.

Keep branches focused, reference capability IDs and releases in pull requests, require passing CI, and use squash merging for a readable student-project history. Emergency fixes may branch from `main` and must be merged back into `develop`. Direct pushes to `main` should be avoided.
