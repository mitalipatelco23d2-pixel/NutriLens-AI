from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.security import hash_password, verify_password
from backend.app.db.models import User
from backend.app.schemas.auth import UserRegisterRequest


def get_user_by_email(db: Session, email: str) -> User | None:
    normalized_email = email.strip().lower()

    return db.scalar(
        select(User).where(User.email == normalized_email)
    )


def create_user(
    db: Session,
    payload: UserRegisterRequest,
) -> User:
    user = User(
        name=payload.name.strip(),
        email=payload.email.strip().lower(),
        password_hash=hash_password(payload.password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


def authenticate_user(
    db: Session,
    email: str,
    password: str,
) -> User | None:
    user = get_user_by_email(db, email)

    if user is None:
        return None

    if not verify_password(password, user.password_hash):
        return None

    return user
