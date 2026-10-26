"""Owner-owned recipes with explicit unknown nutrition and versioned writes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from threading import RLock
from typing import Annotated, Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.auth import User, current_user
from backend.postgres_store import PostgresStore
from backend.storage_runtime import postgres_store

router = APIRouter(prefix="/api/v1/recipes/custom", tags=["Custom recipes"])
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Amount = Annotated[float, Field(strict=True, ge=0.001, le=100_000, allow_inf_nan=False)]
NutrientAmount = Annotated[float, Field(strict=True, ge=0, le=1_000_000, allow_inf_nan=False)]


class RecipeNutrients(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    calories: NutrientAmount | None = None
    protein_g: NutrientAmount | None = None
    carbs_g: NutrientAmount | None = None
    fat_g: NutrientAmount | None = None
    sugar_g: NutrientAmount | None = None
    sodium_mg: NutrientAmount | None = None
    fiber_g: NutrientAmount | None = None


class RecipeIngredient(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Name
    quantity: Amount
    unit: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]
    # These values are for the entire listed quantity, NOT for 100 g or one unit.
    nutrients: RecipeNutrients = Field(default_factory=RecipeNutrients)
    source_label: Name = "User-entered ingredient values"


class RecipeFields(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: Name
    servings: Annotated[float, Field(strict=True, ge=0.001, le=1000, allow_inf_nan=False)]
    ingredients: list[RecipeIngredient] = Field(min_length=1, max_length=100)
    notes: str = Field(default="", max_length=4000)


class RecipeCreate(RecipeFields):
    id: UUID


class RecipeUpdate(RecipeFields):
    expected_version: Annotated[int, Field(strict=True, ge=1)]


class Recipe(RecipeCreate):
    version: int
    created_at: datetime
    updated_at: datetime
    # Aggregates can exceed an individual ingredient's input bounds.
    total_nutrients: dict[str, float | None]
    per_serving: dict[str, float | None]
    source: Literal["USER_ENTERED"] = "USER_ENTERED"


class RecipeConflict(Exception):
    pass


def _recipe(recipe_id: UUID, fields: RecipeFields, version: int, created_at: datetime) -> Recipe:
    totals: dict[str, float | None] = {}
    for key in RecipeNutrients.model_fields:
        values = [getattr(ingredient.nutrients, key) for ingredient in fields.ingredients]
        totals[key] = None if any(value is None for value in values) else round(sum(values), 6)
    return Recipe(
        **fields.model_dump(include=set(RecipeFields.model_fields)),
        id=recipe_id,
        version=version,
        created_at=created_at,
        updated_at=datetime.now(UTC),
        total_nutrients=totals,
        per_serving={
            key: None if value is None else round(value / fields.servings, 6)
            for key, value in totals.items()
        },
    )


class CustomRecipeStore:
    def __init__(self, db: PostgresStore | None = None) -> None:
        self.db = db
        self.lock = RLock()
        self.records: dict[tuple[str, UUID], tuple[str, Recipe | None]] = {}

    def list_recipes(self, owner: str, limit: int | None = 200, offset: int = 0) -> list[Recipe]:
        if self.db is not None:
            with psycopg.connect(self.db.url) as connection:
                rows = connection.execute(
                    "SELECT payload FROM custom_recipes WHERE user_id = %s "
                    "AND payload IS NOT NULL ORDER BY updated_at DESC, id LIMIT %s OFFSET %s",
                    (owner, limit, offset),
                ).fetchall()
            return [Recipe.model_validate(row[0]) for row in rows]
        with self.lock:
            recipes = sorted(
                [r for (user, _), (_, r) in self.records.items() if user == owner and r],
                key=lambda r: (-r.updated_at.timestamp(), r.id),
            )
            return recipes[offset : None if limit is None else offset + limit]

    def get(self, owner: str, recipe_id: UUID) -> Recipe | None:
        if self.db is not None:
            with psycopg.connect(self.db.url) as connection:
                row = connection.execute(
                    "SELECT payload FROM custom_recipes WHERE user_id = %s AND id = %s",
                    (owner, recipe_id),
                ).fetchone()
            return Recipe.model_validate(row[0]) if row and row[0] else None
        with self.lock:
            return self.records.get((owner, recipe_id), ("", None))[1]

    def create(self, owner: str, payload: RecipeCreate) -> tuple[Recipe, bool]:
        fingerprint = sha256(
            json.dumps(payload.model_dump(mode="json"), sort_keys=True).encode()
        ).hexdigest()
        recipe = _recipe(payload.id, payload, 1, datetime.now(UTC))
        if self.db is not None:
            with psycopg.connect(self.db.url, row_factory=dict_row) as connection:
                inserted = connection.execute(
                    "INSERT INTO custom_recipes (user_id, id, payload, request_sha256, version) "
                    "VALUES (%s, %s, %s, %s, 1) ON CONFLICT (user_id, id) DO NOTHING RETURNING id",
                    (owner, payload.id, Jsonb(recipe.model_dump(mode="json")), fingerprint),
                ).fetchone()
                if inserted:
                    return recipe, True
                existing = connection.execute(
                    "SELECT payload, request_sha256 FROM custom_recipes "
                    "WHERE user_id = %s AND id = %s FOR UPDATE",
                    (owner, payload.id),
                ).fetchone()
                if (
                    not existing
                    or not existing["payload"]
                    or existing["request_sha256"] != fingerprint
                ):
                    raise RecipeConflict("This creation was already changed or deleted.")
                return Recipe.model_validate(existing["payload"]), False
        with self.lock:
            key = (owner, payload.id)
            if key in self.records:
                original_hash, existing_memory = self.records[key]
                if original_hash != fingerprint or existing_memory is None:
                    raise RecipeConflict("This creation was already changed or deleted.")
                return existing_memory, False
            self.records[key] = (fingerprint, recipe)
            return recipe, True

    def replace(self, owner: str, recipe_id: UUID, payload: RecipeUpdate) -> Recipe | None:
        if self.db is not None:
            with psycopg.connect(self.db.url, row_factory=dict_row) as connection:
                row = connection.execute(
                    "SELECT payload, version FROM custom_recipes WHERE user_id = %s AND id = %s "
                    "AND payload IS NOT NULL FOR UPDATE",
                    (owner, recipe_id),
                ).fetchone()
                if not row:
                    return None
                if row["version"] != payload.expected_version:
                    raise RecipeConflict("This recipe changed. Refresh before editing again.")
                current = Recipe.model_validate(row["payload"])
                recipe = _recipe(recipe_id, payload, current.version + 1, current.created_at)
                connection.execute(
                    "UPDATE custom_recipes SET payload = %s, version = %s, updated_at = now() "
                    "WHERE user_id = %s AND id = %s",
                    (Jsonb(recipe.model_dump(mode="json")), recipe.version, owner, recipe_id),
                )
                return recipe
        with self.lock:
            key = (owner, recipe_id)
            fingerprint, current_memory = self.records.get(key, ("", None))
            if current_memory is None:
                return None
            if current_memory.version != payload.expected_version:
                raise RecipeConflict("This recipe changed. Refresh before editing again.")
            recipe = _recipe(
                recipe_id, payload, current_memory.version + 1, current_memory.created_at
            )
            self.records[key] = (fingerprint, recipe)
            return recipe

    def delete(self, owner: str, recipe_id: UUID, expected_version: int) -> bool:
        if self.db is not None:
            with psycopg.connect(self.db.url) as connection:
                row = connection.execute(
                    "SELECT version FROM custom_recipes WHERE user_id = %s AND id = %s "
                    "AND payload IS NOT NULL FOR UPDATE",
                    (owner, recipe_id),
                ).fetchone()
                if not row:
                    return False
                if row[0] != expected_version:
                    raise RecipeConflict("This recipe changed. Refresh before deleting it.")
                connection.execute(
                    "UPDATE custom_recipes SET payload = NULL, updated_at = now() "
                    "WHERE user_id = %s AND id = %s",
                    (owner, recipe_id),
                )
                return True
        with self.lock:
            key = (owner, recipe_id)
            fingerprint, current = self.records.get(key, ("", None))
            if current is None:
                return False
            if current.version != expected_version:
                raise RecipeConflict("This recipe changed. Refresh before deleting it.")
            self.records[key] = (fingerprint, None)
            return True

    def export_user(self, owner: str) -> list[dict[str, Any]]:
        return [recipe.model_dump(mode="json") for recipe in self.list_recipes(owner, limit=None)]

    def clear_user(self, owner: str) -> None:
        # Durable recipes and retry tombstones cascade with canonical account deletion.
        if self.db is None:
            with self.lock:
                for key in [key for key in self.records if key[0] == owner]:
                    del self.records[key]


custom_recipe_store = CustomRecipeStore(postgres_store)


@router.get("", response_model=list[Recipe])
def list_recipes(
    user: Annotated[User, Depends(current_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Recipe]:
    return custom_recipe_store.list_recipes(user.id, limit, offset)


@router.get("/{recipe_id}", response_model=Recipe)
def get_recipe(recipe_id: UUID, user: Annotated[User, Depends(current_user)]) -> Recipe:
    recipe = custom_recipe_store.get(user.id, recipe_id)
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found.")
    return recipe


@router.post("", response_model=Recipe, status_code=201)
def create_recipe(
    payload: RecipeCreate, response: Response, user: Annotated[User, Depends(current_user)]
) -> Recipe:
    try:
        recipe, created = custom_recipe_store.create(user.id, payload)
    except RecipeConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    response.status_code = 201 if created else 200
    return recipe


@router.put("/{recipe_id}", response_model=Recipe)
def update_recipe(
    recipe_id: UUID, payload: RecipeUpdate, user: Annotated[User, Depends(current_user)]
) -> Recipe:
    try:
        recipe = custom_recipe_store.replace(user.id, recipe_id, payload)
    except RecipeConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if recipe is None:
        raise HTTPException(status_code=404, detail="Recipe not found.")
    return recipe


@router.delete("/{recipe_id}", status_code=204, response_class=Response)
def delete_recipe(
    recipe_id: UUID,
    user: Annotated[User, Depends(current_user)],
    expected_version: Annotated[int, Query(ge=1)],
) -> Response:
    try:
        deleted = custom_recipe_store.delete(user.id, recipe_id, expected_version)
    except RecipeConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not deleted:
        raise HTTPException(status_code=404, detail="Recipe not found.")
    return Response(status_code=204)
