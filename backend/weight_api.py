"""Optional owner-scoped weight records with explicit enablement and no clinical inference."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import RLock
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg.rows import dict_row
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from backend.auth import User, current_user
from backend.postgres_store import PostgresStore
from backend.storage_runtime import postgres_store

router = APIRouter(prefix="/api/v1/weight", tags=["Weight"])
WeightKg = Annotated[float, Field(strict=True, ge=20, le=500, allow_inf_nan=False)]


class WeightSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target_weight_kg: WeightKg | None = None


class WeightSettings(BaseModel):
    model_config = ConfigDict(frozen=True)
    state: Literal["DISABLED", "ACTIVE"]
    target_weight_kg: float | None


class WeightUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    weight_kg: WeightKg
    recorded_at: AwareDatetime

    @field_validator("recorded_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        value = value.astimezone(UTC)
        if value < datetime(2000, 1, 1, tzinfo=UTC):
            raise ValueError("Choose a date from 2000 onwards.")
        if value > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("Weight can only be recorded for the present or past.")
        return value


class WeightCreate(WeightUpdate):
    id: UUID


class WeightEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    weight_kg: float
    recorded_at: AwareDatetime
    source: Literal["USER_ENTERED"] = "USER_ENTERED"


class WeightSummary(BaseModel):
    state: Literal["DISABLED", "ACTIVE"]
    target_weight_kg: float | None
    latest_weight_kg: float | None
    change_from_first_kg: float | None
    difference_from_target_kg: float | None
    entries: list[WeightEntry]
    method: str = "SELF_REPORTED_WEIGHT_DIFFERENCE_V1"
    limitation: str = (
        "Descriptive self-reported records only. NutriLens does not assign an ideal weight, "
        "safe pace, calorie prescription, diagnosis or treatment."
    )


class WeightConflict(ValueError):
    """The original addition has different content, or has since been deleted."""


def _fingerprint(payload: WeightCreate) -> str:
    content = f"{payload.weight_kg:.4f}:{payload.recorded_at.astimezone(UTC).isoformat()}"
    return sha256(content.encode()).hexdigest()


def _entry(row: dict[str, Any]) -> WeightEntry:
    return WeightEntry(
        id=row["id"],
        weight_kg=float(row["weight_kg"]),
        recorded_at=row["recorded_at"],
    )


class WeightStore:
    def __init__(self, db: PostgresStore | None = None) -> None:
        self.db = db
        self.lock = RLock()
        self._targets: dict[str, float | None] = {}
        self._records: dict[tuple[str, UUID], tuple[str, WeightEntry | None]] = {}

    def settings(self, user_id: str) -> WeightSettings:
        if self.db is not None:
            with psycopg.connect(self.db.url) as connection:
                row = connection.execute(
                    "SELECT target_weight_kg FROM weight_settings WHERE user_id = %s",
                    (user_id,),
                ).fetchone()
            return WeightSettings(
                state="ACTIVE" if row else "DISABLED",
                target_weight_kg=float(row[0]) if row and row[0] is not None else None,
            )
        with self.lock:
            enabled = user_id in self._targets
            return WeightSettings(
                state="ACTIVE" if enabled else "DISABLED",
                target_weight_kg=self._targets.get(user_id),
            )

    def enable(self, user_id: str, target_weight_kg: float | None) -> WeightSettings:
        if self.db is not None:
            with psycopg.connect(self.db.url) as connection:
                connection.execute(
                    "INSERT INTO weight_settings (user_id, target_weight_kg) VALUES (%s, %s) "
                    "ON CONFLICT (user_id) DO UPDATE "
                    "SET target_weight_kg = EXCLUDED.target_weight_kg, updated_at = now()",
                    (user_id, target_weight_kg),
                )
        else:
            with self.lock:
                self._targets[user_id] = target_weight_kg
        return WeightSettings(state="ACTIVE", target_weight_kg=target_weight_kg)

    def disable_and_clear(self, user_id: str) -> None:
        if self.db is not None:
            with psycopg.connect(self.db.url) as connection:
                connection.execute("DELETE FROM weight_entries WHERE user_id = %s", (user_id,))
                connection.execute("DELETE FROM weight_settings WHERE user_id = %s", (user_id,))
            return
        with self.lock:
            self._targets.pop(user_id, None)
            for key in [key for key in self._records if key[0] == user_id]:
                self._records.pop(key, None)

    def entries(self, user_id: str, limit: int = 180) -> list[WeightEntry]:
        if self.db is not None:
            with psycopg.connect(self.db.url, row_factory=dict_row) as connection:
                rows = connection.execute(
                    "SELECT id, weight_kg, recorded_at FROM weight_entries "
                    "WHERE user_id = %s AND deleted_at IS NULL "
                    "ORDER BY recorded_at DESC, id LIMIT %s",
                    (user_id, limit),
                ).fetchall()
            return [_entry(row) for row in rows]
        with self.lock:
            entries = [
                entry
                for (owner, _), (_, entry) in self._records.items()
                if owner == user_id and entry is not None
            ]
        return sorted(
            entries,
            key=lambda item: (-item.recorded_at.timestamp(), str(item.id)),
        )[:limit]

    def create(self, user_id: str, payload: WeightCreate) -> tuple[WeightEntry, bool]:
        fingerprint = _fingerprint(payload)
        if self.db is not None:
            with psycopg.connect(self.db.url, row_factory=dict_row) as connection:
                enabled = connection.execute(
                    "SELECT user_id FROM weight_settings WHERE user_id = %s FOR SHARE",
                    (user_id,),
                ).fetchone()
                if enabled is None:
                    raise WeightConflict("Enable optional weight tracking before adding a record.")
                row = connection.execute(
                    "INSERT INTO weight_entries "
                    "(user_id, id, weight_kg, recorded_at, request_sha256) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id, id) DO NOTHING "
                    "RETURNING id, weight_kg, recorded_at",
                    (user_id, payload.id, payload.weight_kg, payload.recorded_at, fingerprint),
                ).fetchone()
                if row is not None:
                    return _entry(row), True
                existing = connection.execute(
                    "SELECT id, weight_kg, recorded_at, request_sha256, deleted_at "
                    "FROM weight_entries WHERE user_id = %s AND id = %s FOR UPDATE",
                    (user_id, payload.id),
                ).fetchone()
                if (
                    existing is None
                    or existing["deleted_at"] is not None
                    or existing["request_sha256"] != fingerprint
                ):
                    raise WeightConflict("This weight record was already changed or deleted.")
                return _entry(existing), False
        if self.settings(user_id).state != "ACTIVE":
            raise WeightConflict("Enable optional weight tracking before adding a record.")
        key = (user_id, payload.id)
        with self.lock:
            existing_memory = self._records.get(key)
            if existing_memory is not None:
                original_hash, current = existing_memory
                if current is None or original_hash != fingerprint:
                    raise WeightConflict("This weight record was already changed or deleted.")
                return current, False
            entry = WeightEntry(**payload.model_dump())
            self._records[key] = (fingerprint, entry)
            return entry, True

    def replace(self, user_id: str, entry_id: UUID, payload: WeightUpdate) -> WeightEntry | None:
        if self.settings(user_id).state != "ACTIVE":
            return None
        if self.db is not None:
            with psycopg.connect(self.db.url, row_factory=dict_row) as connection:
                row = connection.execute(
                    "UPDATE weight_entries SET weight_kg = %s, recorded_at = %s, "
                    "updated_at = now() WHERE user_id = %s AND id = %s AND deleted_at IS NULL "
                    "RETURNING id, weight_kg, recorded_at",
                    (payload.weight_kg, payload.recorded_at, user_id, entry_id),
                ).fetchone()
            return _entry(row) if row is not None else None
        with self.lock:
            key = (user_id, entry_id)
            existing = self._records.get(key)
            if existing is None or existing[1] is None:
                return None
            updated = WeightEntry(id=entry_id, **payload.model_dump())
            self._records[key] = (existing[0], updated)
            return updated

    def delete(self, user_id: str, entry_id: UUID) -> bool:
        if self.db is not None:
            with psycopg.connect(self.db.url) as connection:
                result = connection.execute(
                    "UPDATE weight_entries SET weight_kg = NULL, recorded_at = NULL, "
                    "deleted_at = now(), updated_at = now() "
                    "WHERE user_id = %s AND id = %s AND deleted_at IS NULL",
                    (user_id, entry_id),
                )
            return result.rowcount == 1
        with self.lock:
            key = (user_id, entry_id)
            existing = self._records.get(key)
            if existing is None or existing[1] is None:
                return False
            self._records[key] = (existing[0], None)
            return True

    def export_user(self, user_id: str) -> dict[str, Any]:
        settings = self.settings(user_id)
        return {
            "state": settings.state,
            "target_weight_kg": settings.target_weight_kg,
            "entries": [entry.model_dump(mode="json") for entry in self.entries(user_id)],
        }

    def clear_user(self, user_id: str) -> None:
        if self.db is not None:
            return
        self.disable_and_clear(user_id)


weight_store = WeightStore(postgres_store)


def _summary(user_id: str, limit: int) -> WeightSummary:
    settings = weight_store.settings(user_id)
    entries = weight_store.entries(user_id, limit) if settings.state == "ACTIVE" else []
    latest = entries[0].weight_kg if entries else None
    first = entries[-1].weight_kg if len(entries) > 1 else None
    return WeightSummary(
        state=settings.state,
        target_weight_kg=settings.target_weight_kg,
        latest_weight_kg=latest,
        change_from_first_kg=(
            round(latest - first, 2) if latest is not None and first is not None else None
        ),
        difference_from_target_kg=(
            round(latest - settings.target_weight_kg, 2)
            if latest is not None and settings.target_weight_kg is not None
            else None
        ),
        entries=entries,
    )


@router.get("", response_model=WeightSummary)
def get_weight_summary(
    user: Annotated[User, Depends(current_user)],
    limit: Annotated[int, Query(ge=1, le=365)] = 180,
) -> WeightSummary:
    return _summary(user.id, limit)


@router.put("/settings", response_model=WeightSettings)
def enable_weight_tracking(
    payload: WeightSettingsUpdate,
    user: Annotated[User, Depends(current_user)],
) -> WeightSettings:
    return weight_store.enable(user.id, payload.target_weight_kg)


@router.delete("/settings", status_code=204, response_class=Response)
def disable_weight_tracking(user: Annotated[User, Depends(current_user)]) -> Response:
    weight_store.disable_and_clear(user.id)
    return Response(status_code=204)


@router.post("/entries", response_model=WeightEntry, status_code=201)
def add_weight_entry(
    payload: WeightCreate,
    response: Response,
    user: Annotated[User, Depends(current_user)],
) -> WeightEntry:
    try:
        entry, created = weight_store.create(user.id, payload)
    except WeightConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    response.status_code = 201 if created else 200
    return entry


@router.put("/entries/{entry_id}", response_model=WeightEntry)
def update_weight_entry(
    entry_id: UUID,
    payload: WeightUpdate,
    user: Annotated[User, Depends(current_user)],
) -> WeightEntry:
    entry = weight_store.replace(user.id, entry_id, payload)
    if entry is None:
        raise HTTPException(status_code=404, detail="Weight record not found.")
    return entry


@router.delete("/entries/{entry_id}", status_code=204, response_class=Response)
def delete_weight_entry(
    entry_id: UUID,
    user: Annotated[User, Depends(current_user)],
) -> Response:
    if not weight_store.delete(user.id, entry_id):
        raise HTTPException(status_code=404, detail="Weight record not found.")
    return Response(status_code=204)
