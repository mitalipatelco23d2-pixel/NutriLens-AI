"""Governed, descriptive population indicator comparison APIs."""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth import User, current_user

router = APIRouter(prefix="/api/v1/population", tags=["Population Intelligence"])
RUNTIME_PATH = Path("data/runtime/faostat-country-indicators-v0.1.0.json.gz")


class CountrySummary(BaseModel):
    m49_code: str
    country: str


class CountryCatalogResponse(BaseModel):
    countries: list[CountrySummary]
    first_year: int
    latest_year: int
    source: dict[str, str]


class CountryComparisonRequest(BaseModel):
    m49_codes: list[str] = Field(min_length=2, max_length=5)
    year: int | None = Field(default=None, ge=2010, le=2023)


class CountryIndicatorValues(BaseModel):
    food_supply_kcal_per_capita_day: float | None
    protein_supply_g_per_capita_day: float | None
    fat_supply_g_per_capita_day: float | None


class CountryIndicatorRecord(BaseModel):
    m49_code: str
    country: str
    year: int
    values: CountryIndicatorValues
    quality_flags: dict[str, str]


class CountryComparisonResponse(BaseModel):
    state: Literal["AVAILABLE"] = "AVAILABLE"
    year: int
    records: list[CountryIndicatorRecord]
    indicators: list[dict[str, str]]
    source: dict[str, str]
    method: str
    limitations: list[str]


IndicatorId = Literal[
    "food_supply_kcal_per_capita_day",
    "protein_supply_g_per_capita_day",
    "fat_supply_g_per_capita_day",
]


class CountryTrendRequest(BaseModel):
    m49_codes: list[str] = Field(min_length=1, max_length=3)
    indicator: IndicatorId
    first_year: int = Field(default=2010, ge=2010, le=2023)
    latest_year: int = Field(default=2023, ge=2010, le=2023)


class CountryTrendPoint(BaseModel):
    year: int
    value: float | None
    quality_flag: str | None


class CountryTrendSeries(BaseModel):
    m49_code: str
    country: str
    points: list[CountryTrendPoint]


class CountryTrendResponse(BaseModel):
    state: Literal["AVAILABLE"] = "AVAILABLE"
    indicator: IndicatorId
    unit: str
    first_year: int
    latest_year: int
    series: list[CountryTrendSeries]
    source: dict[str, str]
    method: str = "DIRECT_FAOSTAT_FBS_DESCRIPTIVE_TIME_SERIES_V1"
    limitations: list[str]


@lru_cache(maxsize=1)
def load_country_bundle() -> dict[str, Any]:
    try:
        with gzip.open(RUNTIME_PATH, "rt", encoding="utf-8") as stream:
            payload: dict[str, Any] = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Governed FAOSTAT runtime bundle is unavailable.") from error
    if payload.get("schema_version") != "0.1.0":
        raise RuntimeError("Unsupported FAOSTAT runtime schema.")
    return payload


@router.get("/countries", response_model=CountryCatalogResponse)
def country_catalog(
    _user: Annotated[User, Depends(current_user)],
) -> CountryCatalogResponse:
    bundle = load_country_bundle()
    records = bundle["records"]
    countries = sorted(
        {(record["m49_code"], record["country"]) for record in records},
        key=lambda item: item[1],
    )
    years = [record["year"] for record in records]
    return CountryCatalogResponse(
        countries=[CountrySummary(m49_code=code, country=name) for code, name in countries],
        first_year=min(years),
        latest_year=max(years),
        source=bundle["source"],
    )


@router.post("/compare", response_model=CountryComparisonResponse)
def compare_countries(
    request: CountryComparisonRequest,
    _user: Annotated[User, Depends(current_user)],
) -> CountryComparisonResponse:
    codes = [code.strip().zfill(3) for code in request.m49_codes]
    if any(not code.isdigit() or len(code) != 3 for code in codes):
        raise HTTPException(status_code=422, detail="Countries must use three-digit M49 codes.")
    if len(set(codes)) != len(codes):
        raise HTTPException(status_code=422, detail="Select distinct countries.")

    bundle = load_country_bundle()
    year = request.year or max(record["year"] for record in bundle["records"])
    by_identity = {(record["m49_code"], record["year"]): record for record in bundle["records"]}
    missing = [code for code in codes if (code, year) not in by_identity]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=(
                "No governed record exists for the selected country and year: "
                f"{', '.join(missing)}."
            ),
        )
    records = [CountryIndicatorRecord.model_validate(by_identity[(code, year)]) for code in codes]
    return CountryComparisonResponse(
        year=year,
        records=records,
        indicators=bundle["indicators"],
        source=bundle["source"],
        method=bundle["method"],
        limitations=bundle["limitations"],
    )


@router.post("/trends", response_model=CountryTrendResponse)
def country_trends(
    request: CountryTrendRequest,
    _user: Annotated[User, Depends(current_user)],
) -> CountryTrendResponse:
    codes = [code.strip().zfill(3) for code in request.m49_codes]
    if any(not code.isdigit() or len(code) != 3 for code in codes):
        raise HTTPException(status_code=422, detail="Countries must use three-digit M49 codes.")
    if len(set(codes)) != len(codes):
        raise HTTPException(status_code=422, detail="Select distinct countries.")
    if request.first_year > request.latest_year:
        raise HTTPException(status_code=422, detail="The first year cannot follow the latest year.")

    bundle = load_country_bundle()
    country_names = {record["m49_code"]: record["country"] for record in bundle["records"]}
    unknown = [code for code in codes if code not in country_names]
    if unknown:
        raise HTTPException(status_code=404, detail="No governed country record exists.")
    records = {(record["m49_code"], record["year"]): record for record in bundle["records"]}
    series = []
    for code in codes:
        points = []
        for year in range(request.first_year, request.latest_year + 1):
            record = records.get((code, year))
            points.append(
                CountryTrendPoint(
                    year=year,
                    value=record["values"].get(request.indicator) if record else None,
                    quality_flag=(
                        record["quality_flags"].get(request.indicator) if record else None
                    ),
                )
            )
        series.append(
            CountryTrendSeries(
                m49_code=code,
                country=country_names[code],
                points=points,
            )
        )
    unit = next(
        indicator["unit"]
        for indicator in bundle["indicators"]
        if indicator["id"] == request.indicator
    )
    return CountryTrendResponse(
        indicator=request.indicator,
        unit=unit,
        first_year=request.first_year,
        latest_year=request.latest_year,
        series=series,
        source=bundle["source"],
        limitations=[
            *bundle["limitations"],
            "The series is descriptive and does not estimate a trend, cause or future value.",
        ],
    )
