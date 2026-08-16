from __future__ import annotations

from backend.app.db.base import Base
from backend.app.db.models import User  # noqa: F401
from backend.app.db.session import engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
