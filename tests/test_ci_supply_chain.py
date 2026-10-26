import re
from pathlib import Path


def test_ci_actions_are_commit_pinned_and_both_dependency_sets_are_audited() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    action_references = re.findall(r"uses:\s*([^\s#]+)", workflow)
    assert action_references
    assert all(re.search(r"@[0-9a-f]{40}$", reference) for reference in action_references)
    assert "pip-audit -r backend/requirements.txt" in workflow
    assert "pip-audit -r backend/requirements-dev.txt" in workflow
    assert "infrastructure/docker/api.Dockerfile" in workflow
    assert "infrastructure/docker/web.Dockerfile" in workflow


def test_api_runtime_requirements_exclude_development_tooling() -> None:
    production = Path("backend/requirements.txt").read_text(encoding="utf-8").casefold()
    development = Path("backend/requirements-dev.txt").read_text(encoding="utf-8").casefold()
    for package in ("pytest", "ruff", "mypy", "pip-audit", "httpx2"):
        assert package not in production
        assert package in development
    assert "google-auth[requests]" in production


def test_web_container_uses_traced_runtime_and_compose_internal_api_host() -> None:
    dockerfile = Path("infrastructure/docker/web.Dockerfile").read_text(encoding="utf-8")
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "/app/.next/standalone" in dockerfile
    assert "/app/node_modules" not in dockerfile
    assert 'CMD ["node", "server.js"]' in dockerfile
    assert "BACKEND_INTERNAL_URL: http://api:8000" in compose
    assert 'REDISCLI_AUTH=\\"$${REDIS_PASSWORD}\\" redis-cli ping' in compose


def test_docker_context_excludes_local_models_environments_and_generated_outputs() -> None:
    ignored = Path(".dockerignore").read_text(encoding="utf-8").splitlines()
    for pattern in (".venv*", ".model-cache", ".open-next", "runs", "*.pt"):
        assert pattern in ignored
