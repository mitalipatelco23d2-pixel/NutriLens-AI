"""Explicit, owner-scoped recipe consumption and pantry/shopping actions."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from threading import RLock
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Response
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from backend import custom_recipes_api, product_api
from backend.auth import User, current_user
from backend.custom_recipes_api import Recipe
from backend.postgres_store import PostgresStore
from backend.product_api import DiaryEntry, NutrientSnapshot, PantryItem, ShoppingListItem
from backend.storage_runtime import postgres_store

router = APIRouter(prefix="/api/v1/recipes/custom", tags=["Custom recipe actions"])
LIMITATION = (
    "Matches use exact normalized ingredient names and the same unit; no unit, density or "
    "food substitutions are inferred. Leftovers and entries with a past saved expiry are excluded. "
    "Check package dates and actual stock. No pantry stock is deducted."
)
SHOPPING_LIMITATION = (
    "Only selected missing ingredients are added. An unchecked item with the same normalized "
    "name is not added again or increased: check its quantity and unit yourself. "
    "Checked items do not count as a pending purchase. No pantry stock is changed."
)


class RecipeSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    expected_version: int = Field(strict=True, ge=1)
    servings: float = Field(strict=True, ge=0.001, le=1000, allow_inf_nan=False)


class RecipeConsumption(RecipeSelection):
    id: UUID
    eaten_at: AwareDatetime

    @field_validator("eaten_at")
    @classmethod
    def actual_consumption(cls, value: datetime) -> datetime:
        value = value.astimezone(UTC)
        if value.year < 2000 or value > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("Choose an actual consumption time from 2000 onwards, not the future.")
        return value


class RecipeShopping(RecipeSelection):
    id: UUID
    check_token: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    ingredient_keys: list[Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{24}$")]] = Field(
        min_length=1, max_length=100
    )

    @field_validator("ingredient_keys")
    @classmethod
    def unique_keys(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Select each missing ingredient only once.")
        return sorted(value)


class PantryIngredientCheck(BaseModel):
    key: str
    name: str
    unit: str
    required_quantity: float
    available_quantity: float | None
    missing_quantity: float | None
    status: Literal["AVAILABLE", "MISSING", "UNIT_MISMATCH"]
    pantry_item_ids: list[str]


class RecipePantryCheck(BaseModel):
    recipe_id: UUID
    recipe_version: int
    servings: float
    check_token: str
    ingredients: list[PantryIngredientCheck]
    limitation: str = LIMITATION


class RecipeShoppingResult(BaseModel):
    recipe_id: UUID
    recipe_version: int
    generated_count: int
    items: list[ShoppingListItem]
    limitation: str = SHOPPING_LIMITATION


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def check_pantry(recipe: Recipe, servings: float, pantry: list[PantryItem]) -> RecipePantryCheck:
    # Combine duplicate ingredient rows before matching, so one stock entry cannot
    # satisfy each duplicate independently. Deliberately do not use substring matching.
    groups: dict[tuple[str, str], tuple[str, str, Decimal]] = {}
    scale = Decimal(str(servings)) / Decimal(str(recipe.servings))
    for ingredient in recipe.ingredients:
        identity = (_normalized(ingredient.name), _normalized(ingredient.unit))
        quantity = Decimal(str(ingredient.quantity)) * scale
        if identity in groups:
            name, unit, previous = groups[identity]
            groups[identity] = (name, unit, previous + quantity)
        else:
            groups[identity] = (ingredient.name, ingredient.unit, quantity)
    today = datetime.now(UTC).date()
    stock = [
        item
        for item in pantry
        if item.item_role == "INGREDIENT" and (item.expires_on is None or item.expires_on >= today)
    ]
    rows = []
    for (name_key, unit_key), (name, unit, required) in groups.items():
        named = [item for item in stock if _normalized(item.name) == name_key]
        matched = [item for item in named if _normalized(item.unit) == unit_key]
        available = sum((Decimal(str(item.quantity)) for item in matched), Decimal(0))
        incompatible = len(named) != len(matched) and available < required
        state: Literal["AVAILABLE", "MISSING", "UNIT_MISMATCH"] = (
            "UNIT_MISMATCH" if incompatible else "AVAILABLE" if available >= required else "MISSING"
        )
        rows.append(
            PantryIngredientCheck(
                key=sha256(json.dumps([name_key, unit_key]).encode()).hexdigest()[:24],
                name=name,
                unit=unit,
                required_quantity=float(required),
                available_quantity=None if incompatible else float(available),
                missing_quantity=None
                if incompatible
                else float(max(Decimal(0), required - available)),
                status=state,
                pantry_item_ids=sorted(item.id for item in named),
            )
        )
    snapshot = {
        "recipe_id": str(recipe.id),
        "recipe_version": recipe.version,
        "servings": float(servings),
        "ingredients": [row.model_dump() for row in rows],
    }
    check_token = sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return RecipePantryCheck(
        recipe_id=recipe.id,
        recipe_version=recipe.version,
        servings=servings,
        ingredients=rows,
        check_token=check_token,
    )


class _ActionContext:
    def __init__(self, owner: str, connection: psycopg.Connection[Any] | None = None) -> None:
        self.owner = owner
        self.connection = connection

    def recipe(self, recipe_id: UUID, version: int) -> Recipe:
        if self.connection is not None:
            row = self.connection.execute(
                "SELECT payload FROM custom_recipes WHERE user_id=%s AND id=%s "
                "AND payload IS NOT NULL FOR SHARE",
                (self.owner, recipe_id),
            ).fetchone()
            recipe = Recipe.model_validate(row["payload"]) if row else None
        else:
            recipe = custom_recipes_api.custom_recipe_store.get(self.owner, recipe_id)
        if recipe is None:
            raise HTTPException(404, "Recipe not found.")
        if recipe.version != version:
            raise HTTPException(409, "Recipe changed. Refresh it before starting a new action.")
        return recipe

    def pantry(self) -> list[PantryItem]:
        if self.connection is None:
            return product_api.product_store.list_pantry(self.owner)
        return [
            PantryItem.model_validate(row["payload"])
            for row in self.connection.execute(
                "SELECT payload FROM pantry_items WHERE user_id=%s FOR SHARE", (self.owner,)
            ).fetchall()
        ]

    def shopping(self) -> list[ShoppingListItem]:
        if self.connection is None:
            return product_api.product_store.list_shopping_list(self.owner)
        return [
            ShoppingListItem.model_validate(row["payload"])
            for row in self.connection.execute(
                "SELECT payload FROM shopping_list_items WHERE user_id=%s ORDER BY created_at,id "
                "FOR UPDATE",
                (self.owner,),
            ).fetchall()
        ]

    def diary(self, entry_id: str) -> DiaryEntry | None:
        if self.connection is None:
            return product_api.product_store.diary.get(self.owner, {}).get(entry_id)
        row = self.connection.execute(
            "SELECT payload FROM diary_entries WHERE user_id=%s AND id=%s FOR SHARE",
            (self.owner, entry_id),
        ).fetchone()
        return DiaryEntry.model_validate(row["payload"]) if row else None

    def add_diary(self, entry: DiaryEntry) -> None:
        if self.connection is None:
            product_api.product_store.add_diary(self.owner, entry)
            return
        self.connection.execute(
            "INSERT INTO diary_entries (id,user_id,eaten_at,payload) VALUES (%s,%s,%s,%s)",
            (entry.id, self.owner, entry.eaten_at, Jsonb(entry.model_dump(mode="json"))),
        )

    def add_shopping(self, item: ShoppingListItem) -> None:
        if self.connection is None:
            product_api.product_store.add_shopping_list_item(self.owner, item)
            return
        self.connection.execute(
            "INSERT INTO shopping_list_items (id,user_id,payload) VALUES (%s,%s,%s)",
            (item.id, self.owner, Jsonb(item.model_dump(mode="json"))),
        )

    def update_shopping(self, item: ShoppingListItem) -> None:
        if self.connection is None:
            product_api.product_store.update_shopping_list_item(self.owner, item)
            return
        self.connection.execute(
            "UPDATE shopping_list_items SET payload=%s WHERE user_id=%s AND id=%s",
            (Jsonb(item.model_dump(mode="json")), self.owner, item.id),
        )


class RecipeActionStore:
    def __init__(self, db: PostgresStore | None = None) -> None:
        self.db = db
        self.lock = RLock()
        self.receipts: dict[tuple[str, UUID], dict[str, Any]] = {}

    @contextmanager
    def context(self, owner: str) -> Iterator[_ActionContext]:
        if self.db is not None:
            with psycopg.connect(self.db.url, row_factory=dict_row) as connection:
                # Serialize this owner's action receipts and shopping deduplication,
                # while allowing other accounts to proceed independently.
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"recipe-actions:{owner}",)
                )
                yield _ActionContext(owner, connection)
        else:
            with (
                self.lock,
                custom_recipes_api.custom_recipe_store.lock,
                product_api.product_store.lock,
            ):
                yield _ActionContext(owner)

    def receipt(
        self, ctx: _ActionContext, action_id: UUID, fingerprint: str
    ) -> dict[str, Any] | None:
        if ctx.connection is not None:
            row = ctx.connection.execute(
                "SELECT * FROM custom_recipe_actions WHERE user_id=%s AND id=%s",
                (ctx.owner, action_id),
            ).fetchone()
        else:
            row = self.receipts.get((ctx.owner, action_id))
        if row is not None and row["request_sha256"] != fingerprint:
            raise HTTPException(409, "This action ID was already used with different details.")
        return dict(row) if row is not None else None

    def save_receipt(
        self,
        ctx: _ActionContext,
        action_id: UUID,
        kind: str,
        fingerprint: str,
        result_ids: list[str],
        generated: int,
    ) -> None:
        if ctx.connection is not None:
            ctx.connection.execute(
                "INSERT INTO custom_recipe_actions "
                "(user_id,id,kind,request_sha256,result_ids,generated_count) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (ctx.owner, action_id, kind, fingerprint, Jsonb(result_ids), generated),
            )
        else:
            self.receipts[(ctx.owner, action_id)] = {
                "kind": kind,
                "request_sha256": fingerprint,
                "result_ids": result_ids,
                "generated_count": generated,
            }

    def consume(
        self, owner: str, recipe_id: UUID, payload: RecipeConsumption
    ) -> tuple[DiaryEntry, bool]:
        fingerprint = _fingerprint("DIARY", recipe_id, payload)
        with self.context(owner) as ctx:
            receipt = self.receipt(ctx, payload.id, fingerprint)
            if receipt is not None:
                existing = ctx.diary(receipt["result_ids"][0])
                if existing is None:
                    raise HTTPException(
                        409, "This logged serving was deleted. It will not be recreated."
                    )
                return existing, False
            recipe = ctx.recipe(recipe_id, payload.expected_version)
            entry = DiaryEntry(
                id=str(uuid4()),
                name=recipe.name,
                eaten_at=payload.eaten_at,
                serving_grams=None,
                nutrients=NutrientSnapshot(
                    **{
                        nutrient: None
                        if value is None
                        else round(value / recipe.servings * payload.servings, 6)
                        for nutrient, value in recipe.total_nutrients.items()
                    }
                ),
                recipe_id=str(recipe.id),
                recipe_version=recipe.version,
                recipe_servings=payload.servings,
                source="CUSTOM_RECIPE",
            )
            ctx.add_diary(entry)
            self.save_receipt(ctx, payload.id, "DIARY", fingerprint, [entry.id], 1)
            return entry, True

    def shop(
        self, owner: str, recipe_id: UUID, payload: RecipeShopping
    ) -> tuple[RecipeShoppingResult, bool]:
        fingerprint = _fingerprint("SHOPPING", recipe_id, payload)
        with self.context(owner) as ctx:
            receipt = self.receipt(ctx, payload.id, fingerprint)
            if receipt is not None:
                current = {item.id: item for item in ctx.shopping()}
                if any(item_id not in current for item_id in receipt["result_ids"]):
                    raise HTTPException(
                        409, "An item from this action was deleted. It will not be recreated."
                    )
                return RecipeShoppingResult(
                    recipe_id=recipe_id,
                    recipe_version=payload.expected_version,
                    generated_count=receipt["generated_count"],
                    items=[current[item_id] for item_id in receipt["result_ids"]],
                ), False
            recipe = ctx.recipe(recipe_id, payload.expected_version)
            check = check_pantry(recipe, payload.servings, ctx.pantry())
            if payload.check_token != check.check_token:
                raise HTTPException(409, "Pantry stock changed. Check again before adding items.")
            missing = {row.key: row for row in check.ingredients if row.status == "MISSING"}
            if any(key not in missing for key in payload.ingredient_keys):
                raise HTTPException(
                    409, "Pantry availability changed or a selection is unresolved. Check again."
                )
            current_items = ctx.shopping()
            existing = {_normalized(item.name): item for item in current_items if not item.checked}
            selected = [missing[key] for key in payload.ingredient_keys]
            additions: list[ShoppingListItem] = []
            results: list[ShoppingListItem] = []
            for ingredient in selected:
                name_key = _normalized(ingredient.name)
                item = existing.get(name_key)
                if item is None:
                    item = ShoppingListItem(
                        id=str(uuid4()),
                        name=ingredient.name,
                        source="RECIPE_PLAN",
                        quantity=ingredient.missing_quantity,
                        unit=ingredient.unit,
                        recipe_id=str(recipe.id),
                    )
                    additions.append(item)
                    existing[name_key] = item
                elif (
                    item.source == "RECIPE_PLAN"
                    and item.recipe_id == str(recipe.id)
                    and item.unit == ingredient.unit
                    and ingredient.missing_quantity is not None
                    and item.quantity != ingredient.missing_quantity
                ):
                    item = ShoppingListItem.model_validate(
                        {
                            **item.model_dump(),
                            "quantity": ingredient.missing_quantity,
                            "source": "RECIPE_PLAN",
                        }
                    )
                    ctx.update_shopping(item)
                    existing[name_key] = item
                if not any(result.id == item.id for result in results):
                    results.append(item)
            if len(current_items) + len(additions) > 200:
                raise HTTPException(409, "Shopping list limit reached. No items were added.")
            for item in additions:
                ctx.add_shopping(item)
            self.save_receipt(
                ctx,
                payload.id,
                "SHOPPING",
                fingerprint,
                [item.id for item in results],
                len(additions),
            )
            return RecipeShoppingResult(
                recipe_id=recipe.id,
                recipe_version=recipe.version,
                generated_count=len(additions),
                items=results,
            ), True

    def clear_user(self, owner: str) -> None:
        if self.db is None:
            with self.lock:
                for key in [key for key in self.receipts if key[0] == owner]:
                    del self.receipts[key]


def _fingerprint(kind: str, recipe_id: UUID, payload: BaseModel) -> str:
    request = {
        "kind": kind,
        "recipe_id": str(recipe_id),
        "payload": payload.model_dump(mode="json"),
    }
    return sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


recipe_action_store = RecipeActionStore(postgres_store)


@router.post("/{recipe_id}/diary", response_model=DiaryEntry, status_code=201)
def consume_recipe(
    recipe_id: UUID,
    payload: RecipeConsumption,
    response: Response,
    user: Annotated[User, Depends(current_user)],
) -> DiaryEntry:
    entry, created = recipe_action_store.consume(user.id, recipe_id, payload)
    response.status_code = 201 if created else 200
    return entry


@router.post("/{recipe_id}/pantry-check", response_model=RecipePantryCheck)
def check_recipe_pantry(
    recipe_id: UUID, payload: RecipeSelection, user: Annotated[User, Depends(current_user)]
) -> RecipePantryCheck:
    with recipe_action_store.context(user.id) as ctx:
        recipe = ctx.recipe(recipe_id, payload.expected_version)
        return check_pantry(recipe, payload.servings, ctx.pantry())


@router.post("/{recipe_id}/shopping-list", response_model=RecipeShoppingResult, status_code=201)
def recipe_shopping(
    recipe_id: UUID,
    payload: RecipeShopping,
    response: Response,
    user: Annotated[User, Depends(current_user)],
) -> RecipeShoppingResult:
    result, created = recipe_action_store.shop(user.id, recipe_id, payload)
    response.status_code = 201 if created else 200
    return result
