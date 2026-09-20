from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.db.models import User
from backend.app.db.session import get_db
from backend.app.main import create_app


@pytest.fixture()
def auth_context(tmp_path):
    database_path = tmp_path / "auth-test.db"

    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )

    TestSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    Base.metadata.create_all(bind=engine)

    application = create_app()

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = override_get_db

    with TestClient(application) as client:
        yield client, TestSessionLocal

    application.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_register_user(auth_context):
    client, _ = auth_context

    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Test User",
            "email": "test@example.com",
            "password": "TestPassword123!",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["name"] == "Test User"
    assert data["email"] == "test@example.com"
    assert "password" not in data
    assert "password_hash" not in data


def test_password_is_hashed_in_database(auth_context):
    client, TestSessionLocal = auth_context

    password = "TestPassword123!"

    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Hash Test",
            "email": "hash@example.com",
            "password": password,
        },
    )

    assert response.status_code == 201

    with TestSessionLocal() as db:
        user = db.scalar(
            select(User).where(User.email == "hash@example.com")
        )

        assert user is not None
        assert user.password_hash != password
        assert password not in user.password_hash


def test_duplicate_email_is_rejected(auth_context):
    client, _ = auth_context

    payload = {
        "name": "Duplicate Test",
        "email": "duplicate@example.com",
        "password": "TestPassword123!",
    }

    first = client.post("/api/v1/auth/register", json=payload)
    second = client.post("/api/v1/auth/register", json=payload)

    assert first.status_code == 201
    assert second.status_code == 409


def test_login_returns_access_token(auth_context):
    client, _ = auth_context

    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Login Test",
            "email": "login@example.com",
            "password": "TestPassword123!",
        },
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "login@example.com",
            "password": "TestPassword123!",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["token_type"] == "bearer"
    assert data["access_token"]
    assert data["user"]["email"] == "login@example.com"


def test_wrong_password_is_rejected(auth_context):
    client, _ = auth_context

    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Wrong Password Test",
            "email": "wrong@example.com",
            "password": "CorrectPassword123!",
        },
    )

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "wrong@example.com",
            "password": "WrongPassword123!",
        },
    )

    assert response.status_code == 401


def test_authenticated_user_can_get_profile(auth_context):
    client, _ = auth_context

    client.post(
        "/api/v1/auth/register",
        json={
            "name": "Profile Test",
            "email": "profile@example.com",
            "password": "TestPassword123!",
        },
    )

    login = client.post(
        "/api/v1/auth/login",
        json={
            "email": "profile@example.com",
            "password": "TestPassword123!",
        },
    )

    token = login.json()["access_token"]

    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "profile@example.com"
    assert response.json()["name"] == "Profile Test"


def test_profile_requires_authentication(auth_context):
    client, _ = auth_context

    response = client.get("/api/v1/users/me")

    assert response.status_code == 401
