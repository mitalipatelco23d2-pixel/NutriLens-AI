"""Select the configured durable persistence adapter once per API process."""

from backend.postgres_store import PostgresStore
from backend.settings import settings

postgres_store = (
    PostgresStore(settings.postgres_url) if settings.persistence_backend == "postgres" else None
)


def migrate_if_configured() -> None:
    if postgres_store is not None and settings.auto_migrate:
        postgres_store.migrate()
