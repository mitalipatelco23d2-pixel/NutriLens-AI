"""Account-owned water logs, with durable retry identity and explicit local days."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta, timezone
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

router = APIRouter(prefix="/api/v1/hydration", tags=["Hydration"])
WaterAmount = Annotated[int, Field(strict=True, ge=1, le=5_000)]
WaterTarget = Annotated[int, Field(strict=True, ge=100, le=10_000)]


class HydrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    amount_ml: WaterAmount
    consumed_at: AwareDatetime

    @field_validator("consumed_at")
    @classmethod
    def validate_time(cls, value: datetime) -> datetime:
        value = value.astimezone(UTC)
        if value < datetime(2000, 1, 1, tzinfo=UTC):
            raise ValueError("Choose a date from 2000 onwards.")
        if value > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("Water can only be logged after it is consumed.")
        return value


class HydrationCreate(HydrationUpdate):
    id: UUID


class HydrationEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID
    amount_ml: WaterAmount
    consumed_at: AwareDatetime
    source: Literal["USER_ENTERED"] = "USER_ENTERED"


class HydrationTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_ml: WaterTarget | None


class HydrationDay(BaseModel):
    day: date
    timezone_offset_minutes: int
    target_ml: int | None
    total_ml: int
    remaining_ml: int | None
    entries: list[HydrationEntry]


class HydrationBucket(BaseModel):
    label: str
    start_time: AwareDatetime
    end_time: AwareDatetime
    total_ml: int
    target_ml: int | None = None
    target_attained: bool = False


class HydrationAnalytics(BaseModel):
    period: Literal["DAY", "WEEK", "MONTH", "YEAR", "CUSTOM"]
    start_date: date
    end_date: date
    total_ml: int
    daily_average_ml: int
    target_ml: int | None
    days_target_met: int
    total_days: int
    attainment_rate_pct: float
    buckets: list[HydrationBucket]


class HydrationConflict(ValueError):
    """The original addition has different content, or has since been deleted."""


def _fingerprint(payload: HydrationCreate) -> str:
    # Timestamp offsets normalize to UTC so equivalent client retries compare equal.
    content = f"{payload.amount_ml}:{payload.consumed_at.astimezone(UTC).isoformat()}"
    return sha256(content.encode()).hexdigest()


def _entry(row: dict[str, Any]) -> HydrationEntry:
    return HydrationEntry(id=row["id"], amount_ml=row["amount_ml"], consumed_at=row["consumed_at"])


class HydrationStore:
    def __init__(self, db: PostgresStore | None = None) -> None:
        self.db = db
        self.lock = RLock()
        self._targets: dict[str, int] = {}
        # Keep only identity/fingerprint after deletion to prevent delayed POST replay.
        self._records: dict[tuple[str, UUID], tuple[str, HydrationEntry | None]] = {}

    def target(self, user_id: str) -> int | None:
        if self.db is not None:
            with psycopg.connect(self.db.url) as connection:
                row = connection.execute(
                    "SELECT target_ml FROM hydration_targets WHERE user_id = %s", (user_id,)
                ).fetchone()
            return int(row[0]) if row else None
        with self.lock:
            return self._targets.get(user_id)

    def save_target(self, user_id: str, target: int | None) -> None:
        if self.db is not None:
            with psycopg.connect(self.db.url) as connection:
                if target is None:
                    connection.execute(
                        "DELETE FROM hydration_targets WHERE user_id = %s", (user_id,)
                    )
                else:
                    connection.execute(
                        "INSERT INTO hydration_targets (user_id, target_ml) VALUES (%s, %s) "
                        "ON CONFLICT (user_id) DO UPDATE "
                        "SET target_ml = EXCLUDED.target_ml, updated_at = now()",
                        (user_id, target),
                    )
            return
        with self.lock:
            if target is None:
                self._targets.pop(user_id, None)
            else:
                self._targets[user_id] = target

    def entries(
        self, user_id: str, start: datetime | None = None, end: datetime | None = None
    ) -> list[HydrationEntry]:
        if self.db is not None:
            with psycopg.connect(self.db.url, row_factory=dict_row) as connection:
                rows = connection.execute(
                    "SELECT id, amount_ml, consumed_at FROM hydration_entries "
                    "WHERE user_id = %s AND deleted_at IS NULL "
                    "AND (%s::timestamptz IS NULL OR consumed_at >= %s) "
                    "AND (%s::timestamptz IS NULL OR consumed_at < %s) "
                    "ORDER BY consumed_at DESC, id",
                    (user_id, start, start, end, end),
                ).fetchall()
            return [_entry(row) for row in rows]
        with self.lock:
            entries = [
                entry
                for (owner, _), (_, entry) in self._records.items()
                if owner == user_id
                and entry is not None
                and (start is None or entry.consumed_at >= start)
                and (end is None or entry.consumed_at < end)
            ]
        return sorted(entries, key=lambda item: (-item.consumed_at.timestamp(), item.id))

    def create(self, user_id: str, payload: HydrationCreate) -> tuple[HydrationEntry, bool]:
        fingerprint = _fingerprint(payload)
        if self.db is not None:
            with psycopg.connect(self.db.url, row_factory=dict_row) as connection:
                row = connection.execute(
                    "INSERT INTO hydration_entries "
                    "(user_id, id, amount_ml, consumed_at, request_sha256) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id, id) DO NOTHING "
                    "RETURNING id, amount_ml, consumed_at",
                    (user_id, payload.id, payload.amount_ml, payload.consumed_at, fingerprint),
                ).fetchone()
                if row is not None:
                    return _entry(row), True
                existing = connection.execute(
                    "SELECT id, amount_ml, consumed_at, request_sha256, deleted_at "
                    "FROM hydration_entries WHERE user_id = %s AND id = %s FOR UPDATE",
                    (user_id, payload.id),
                ).fetchone()
                if (
                    existing is None
                    or existing["deleted_at"] is not None
                    or existing["request_sha256"] != fingerprint
                ):
                    raise HydrationConflict("This addition was already changed or deleted.")
                return _entry(existing), False
        key = (user_id, payload.id)
        with self.lock:
            existing_memory = self._records.get(key)
            if existing_memory is not None:
                original_hash, current = existing_memory
                if current is None or original_hash != fingerprint:
                    raise HydrationConflict("This addition was already changed or deleted.")
                return current, False
            entry = HydrationEntry(**payload.model_dump())
            self._records[key] = (fingerprint, entry)
            return entry, True

    def replace(
        self, user_id: str, entry_id: UUID, payload: HydrationUpdate
    ) -> HydrationEntry | None:
        if self.db is not None:
            with psycopg.connect(self.db.url, row_factory=dict_row) as connection:
                row = connection.execute(
                    "UPDATE hydration_entries SET amount_ml = %s, consumed_at = %s, "
                    "updated_at = now() WHERE user_id = %s AND id = %s AND deleted_at IS NULL "
                    "RETURNING id, amount_ml, consumed_at",
                    (payload.amount_ml, payload.consumed_at, user_id, entry_id),
                ).fetchone()
            return _entry(row) if row is not None else None
        with self.lock:
            key = (user_id, entry_id)
            existing = self._records.get(key)
            if existing is None or existing[1] is None:
                return None
            updated = HydrationEntry(id=entry_id, **payload.model_dump())
            self._records[key] = (existing[0], updated)
            return updated

    def delete(self, user_id: str, entry_id: UUID) -> bool:
        if self.db is not None:
            with psycopg.connect(self.db.url) as connection:
                result = connection.execute(
                    "UPDATE hydration_entries SET amount_ml = NULL, consumed_at = NULL, "
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
        return {
            "target_ml": self.target(user_id),
            "entries": [entry.model_dump(mode="json") for entry in self.entries(user_id)],
        }

    def clear_user(self, user_id: str) -> None:
        # Durable records and retry identities cascade when the canonical user is deleted.
        if self.db is not None:
            return
        with self.lock:
            self._targets.pop(user_id, None)
            for key in [key for key in self._records if key[0] == user_id]:
                self._records.pop(key, None)


hydration_store = HydrationStore(postgres_store)


@router.get("", response_model=HydrationDay)
def get_day(
    user: Annotated[User, Depends(current_user)],
    day: date | None = None,
    timezone_offset_minutes: Annotated[int, Query(ge=-840, le=840)] = 0,
    next_day_timezone_offset_minutes: Annotated[int | None, Query(ge=-840, le=840)] = None,
) -> HydrationDay:
    local_zone = timezone(timedelta(minutes=timezone_offset_minutes))
    today = datetime.now(local_zone).date()
    selected = day or today
    if selected < date(2000, 1, 1) or selected > today:
        raise HTTPException(status_code=422, detail="Choose today or a past day from 2000 onwards.")
    start = datetime.combine(selected, time.min, tzinfo=local_zone).astimezone(UTC)
    next_zone = timezone(
        timedelta(
            minutes=timezone_offset_minutes
            if next_day_timezone_offset_minutes is None
            else next_day_timezone_offset_minutes
        )
    )
    end = datetime.combine(selected + timedelta(days=1), time.min, tzinfo=next_zone).astimezone(UTC)
    if not timedelta(hours=22) <= end - start <= timedelta(hours=26):
        raise HTTPException(status_code=422, detail="The local-day offsets are inconsistent.")
    entries = hydration_store.entries(user.id, start, end)
    total = sum(entry.amount_ml for entry in entries)
    target = hydration_store.target(user.id)
    return HydrationDay(
        day=selected,
        timezone_offset_minutes=timezone_offset_minutes,
        target_ml=target,
        total_ml=total,
        remaining_ml=max(0, target - total) if target is not None else None,
        entries=entries,
    )


@router.get("/analytics", response_model=HydrationAnalytics)
def get_analytics(
    user: Annotated[User, Depends(current_user)],
    period: Literal["DAY", "WEEK", "MONTH", "YEAR", "CUSTOM"] = "WEEK",
    day: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    timezone_offset_minutes: Annotated[int, Query(ge=-840, le=840)] = 0,
) -> HydrationAnalytics:
    local_zone = timezone(timedelta(minutes=timezone_offset_minutes))
    today = datetime.now(local_zone).date()
    ref_day = day or today
    if ref_day < date(2000, 1, 1) or ref_day > today:
        raise HTTPException(status_code=422, detail="Choose today or a past day from 2000 onwards.")

    target = hydration_store.target(user.id)

    if period == "DAY":
        eff_start_date = ref_day
        eff_end_date = ref_day
        total_days = 1
        day_start = datetime.combine(ref_day, time.min, tzinfo=local_zone).astimezone(UTC)
        day_end = datetime.combine(
            ref_day + timedelta(days=1), time.min, tzinfo=local_zone
        ).astimezone(UTC)
        entries = hydration_store.entries(user.id, day_start, day_end)

        buckets: list[HydrationBucket] = []
        for hour in range(0, 24, 2):
            b_start_local = datetime.combine(ref_day, time(hour, 0), tzinfo=local_zone)
            b_end_local = b_start_local + timedelta(hours=2)
            b_start_utc = b_start_local.astimezone(UTC)
            b_end_utc = b_end_local.astimezone(UTC)
            b_entries = [e for e in entries if b_start_utc <= e.consumed_at < b_end_utc]
            b_total = sum(e.amount_ml for e in b_entries)
            buckets.append(
                HydrationBucket(
                    label=f"{hour:02d}:00",
                    start_time=b_start_utc,
                    end_time=b_end_utc,
                    total_ml=b_total,
                    target_ml=None,
                    target_attained=False,
                )
            )
        total_ml = sum(b.total_ml for b in buckets)
        daily_average_ml = total_ml
        days_target_met = 1 if (target is not None and total_ml >= target) else 0

    elif period == "WEEK":
        eff_end_date = ref_day
        eff_start_date = ref_day - timedelta(days=6)
        total_days = 7
        period_start = datetime.combine(eff_start_date, time.min, tzinfo=local_zone).astimezone(UTC)
        period_end = datetime.combine(
            eff_end_date + timedelta(days=1), time.min, tzinfo=local_zone
        ).astimezone(UTC)
        entries = hydration_store.entries(user.id, period_start, period_end)

        buckets = []
        days_target_met = 0
        for i in range(7):
            d = eff_start_date + timedelta(days=i)
            d_start_local = datetime.combine(d, time.min, tzinfo=local_zone)
            d_end_local = d_start_local + timedelta(days=1)
            d_start_utc = d_start_local.astimezone(UTC)
            d_end_utc = d_end_local.astimezone(UTC)
            d_entries = [e for e in entries if d_start_utc <= e.consumed_at < d_end_utc]
            d_total = sum(e.amount_ml for e in d_entries)
            attained = target is not None and d_total >= target
            if attained:
                days_target_met += 1
            buckets.append(
                HydrationBucket(
                    label=d.strftime("%a %d"),
                    start_time=d_start_utc,
                    end_time=d_end_utc,
                    total_ml=d_total,
                    target_ml=target,
                    target_attained=attained,
                )
            )
        total_ml = sum(b.total_ml for b in buckets)
        daily_average_ml = round(total_ml / total_days)

    elif period == "MONTH":
        eff_end_date = ref_day
        eff_start_date = ref_day - timedelta(days=29)
        total_days = 30
        period_start = datetime.combine(eff_start_date, time.min, tzinfo=local_zone).astimezone(UTC)
        period_end = datetime.combine(
            eff_end_date + timedelta(days=1), time.min, tzinfo=local_zone
        ).astimezone(UTC)
        entries = hydration_store.entries(user.id, period_start, period_end)

        buckets = []
        days_target_met = 0
        for i in range(30):
            d = eff_start_date + timedelta(days=i)
            d_start_local = datetime.combine(d, time.min, tzinfo=local_zone)
            d_end_local = d_start_local + timedelta(days=1)
            d_start_utc = d_start_local.astimezone(UTC)
            d_end_utc = d_end_local.astimezone(UTC)
            d_entries = [e for e in entries if d_start_utc <= e.consumed_at < d_end_utc]
            d_total = sum(e.amount_ml for e in d_entries)
            attained = target is not None and d_total >= target
            if attained:
                days_target_met += 1
            buckets.append(
                HydrationBucket(
                    label=d.strftime("%b %d"),
                    start_time=d_start_utc,
                    end_time=d_end_utc,
                    total_ml=d_total,
                    target_ml=target,
                    target_attained=attained,
                )
            )
        total_ml = sum(b.total_ml for b in buckets)
        daily_average_ml = round(total_ml / total_days)

    elif period == "YEAR":
        eff_end_date = ref_day
        first_of_curr_month = date(ref_day.year, ref_day.month, 1)
        year_offset = (first_of_curr_month.month - 1 - 11) // 12
        month_offset = (first_of_curr_month.month - 1 - 11) % 12 + 1
        eff_start_date = date(first_of_curr_month.year + year_offset, month_offset, 1)
        period_start = datetime.combine(eff_start_date, time.min, tzinfo=local_zone).astimezone(UTC)
        period_end = datetime.combine(
            ref_day + timedelta(days=1), time.min, tzinfo=local_zone
        ).astimezone(UTC)
        entries = hydration_store.entries(user.id, period_start, period_end)

        buckets = []
        total_days = (ref_day - eff_start_date).days + 1
        curr_m_start = eff_start_date
        while curr_m_start <= ref_day:
            if curr_m_start.month == 12:
                next_m_start = date(curr_m_start.year + 1, 1, 1)
            else:
                next_m_start = date(curr_m_start.year, curr_m_start.month + 1, 1)
            m_end_date = min(ref_day + timedelta(days=1), next_m_start)
            m_start_utc = datetime.combine(curr_m_start, time.min, tzinfo=local_zone).astimezone(
                UTC
            )
            m_end_utc = datetime.combine(m_end_date, time.min, tzinfo=local_zone).astimezone(UTC)
            m_entries = [e for e in entries if m_start_utc <= e.consumed_at < m_end_utc]
            m_total = sum(e.amount_ml for e in m_entries)
            buckets.append(
                HydrationBucket(
                    label=curr_m_start.strftime("%b %Y"),
                    start_time=m_start_utc,
                    end_time=m_end_utc,
                    total_ml=m_total,
                    target_ml=None,
                    target_attained=False,
                )
            )
            curr_m_start = next_m_start
        total_ml = sum(b.total_ml for b in buckets)
        daily_average_ml = round(total_ml / total_days) if total_days > 0 else 0
        entries_by_day: dict[date, int] = {}
        for e in entries:
            ed = e.consumed_at.astimezone(local_zone).date()
            entries_by_day[ed] = entries_by_day.get(ed, 0) + e.amount_ml
        if target is not None:
            days_target_met = sum(1 for d, amt in entries_by_day.items() if amt >= target)
        else:
            days_target_met = 0

    elif period == "CUSTOM":
        if start_date is None or end_date is None:
            raise HTTPException(
                status_code=422, detail="start_date and end_date are required for CUSTOM period."
            )
        if start_date > end_date:
            raise HTTPException(
                status_code=422, detail="start_date must be less than or equal to end_date."
            )
        if end_date > today or start_date < date(2000, 1, 1):
            raise HTTPException(status_code=422, detail="Dates must be between 2000 and today.")
        eff_start_date = start_date
        eff_end_date = end_date
        total_days = (end_date - start_date).days + 1
        if total_days > 365:
            raise HTTPException(status_code=422, detail="Custom range cannot exceed 365 days.")
        period_start = datetime.combine(eff_start_date, time.min, tzinfo=local_zone).astimezone(UTC)
        period_end = datetime.combine(
            eff_end_date + timedelta(days=1), time.min, tzinfo=local_zone
        ).astimezone(UTC)
        entries = hydration_store.entries(user.id, period_start, period_end)

        buckets = []
        days_target_met = 0
        for i in range(total_days):
            d = eff_start_date + timedelta(days=i)
            d_start_local = datetime.combine(d, time.min, tzinfo=local_zone)
            d_end_local = d_start_local + timedelta(days=1)
            d_start_utc = d_start_local.astimezone(UTC)
            d_end_utc = d_end_local.astimezone(UTC)
            d_entries = [e for e in entries if d_start_utc <= e.consumed_at < d_end_utc]
            d_total = sum(e.amount_ml for e in d_entries)
            attained = target is not None and d_total >= target
            if attained:
                days_target_met += 1
            buckets.append(
                HydrationBucket(
                    label=d.strftime("%Y-%m-%d"),
                    start_time=d_start_utc,
                    end_time=d_end_utc,
                    total_ml=d_total,
                    target_ml=target,
                    target_attained=attained,
                )
            )
        total_ml = sum(b.total_ml for b in buckets)
        daily_average_ml = round(total_ml / total_days)

    attainment_rate_pct = (
        round((days_target_met / total_days) * 100, 1)
        if target is not None and total_days > 0
        else 0.0
    )

    return HydrationAnalytics(
        period=period,
        start_date=eff_start_date,
        end_date=eff_end_date,
        total_ml=total_ml,
        daily_average_ml=daily_average_ml,
        target_ml=target,
        days_target_met=days_target_met,
        total_days=total_days,
        attainment_rate_pct=attainment_rate_pct,
        buckets=buckets,
    )


@router.put("/target", response_model=HydrationTarget)
def set_target(
    payload: HydrationTarget, user: Annotated[User, Depends(current_user)]
) -> HydrationTarget:
    hydration_store.save_target(user.id, payload.target_ml)
    return payload


@router.post("/entries", response_model=HydrationEntry, status_code=201)
def add_entry(
    payload: HydrationCreate, response: Response, user: Annotated[User, Depends(current_user)]
) -> HydrationEntry:
    try:
        entry, created = hydration_store.create(user.id, payload)
    except HydrationConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    response.status_code = 201 if created else 200
    return entry


@router.put("/entries/{entry_id}", response_model=HydrationEntry)
def update_entry(
    entry_id: UUID, payload: HydrationUpdate, user: Annotated[User, Depends(current_user)]
) -> HydrationEntry:
    entry = hydration_store.replace(user.id, entry_id, payload)
    if entry is None:
        raise HTTPException(status_code=404, detail="Water entry not found.")
    return entry


@router.delete("/entries/{entry_id}", status_code=204, response_class=Response)
def delete_entry(entry_id: UUID, user: Annotated[User, Depends(current_user)]) -> Response:
    if not hydration_store.delete(user.id, entry_id):
        raise HTTPException(status_code=404, detail="Water entry not found.")
    return Response(status_code=204)
