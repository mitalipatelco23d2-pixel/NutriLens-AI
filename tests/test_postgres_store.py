"""Focused regression tests for PostgreSQL persistence helpers."""

from types import SimpleNamespace, TracebackType

import psycopg
from pytest import MonkeyPatch

from backend.postgres_store import PostgresStore


def test_delete_shopping_list_item_uses_the_governed_table_allowlist(
    monkeypatch: MonkeyPatch,
) -> None:
    executed: dict[str, object] = {}

    class Connection:
        def __enter__(self) -> "Connection":
            return self

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: TracebackType | None,
        ) -> None:
            return None

        def execute(self, sql: str, values: tuple[str, str]) -> SimpleNamespace:
            executed["sql"] = sql
            executed["values"] = values
            return SimpleNamespace(rowcount=1)

    monkeypatch.setattr(
        psycopg,
        "connect",
        lambda _url: Connection(),
    )

    store = PostgresStore("postgresql://test")

    assert store.delete_shopping_list_item("owner-1", "shopping-1") is True
    assert "DELETE FROM shopping_list_items" in str(executed["sql"])
    assert executed["values"] == ("shopping-1", "owner-1")
