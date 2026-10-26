"""Leakage-safe deterministic split assignment and validation."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from scripts.data_engineering import SPLIT_SEED


@dataclass(frozen=True)
class SplitRecord:
    record_id: str
    group_id: str
    split: str
    seed: int


def assign_group(group_id: str, *, seed: int = SPLIT_SEED) -> str:
    digest = hashlib.sha256(f"{seed}:{group_id}".encode()).digest()
    fraction = int.from_bytes(digest[:8], "big") / 2**64
    if fraction < 0.70:
        return "TRAIN"
    if fraction < 0.85:
        return "VALIDATION"
    return "TEST"


def generate_splits(
    record_groups: Iterable[tuple[str, str]], *, seed: int = SPLIT_SEED
) -> list[SplitRecord]:
    return [
        SplitRecord(record_id, group_id, assign_group(group_id, seed=seed), seed)
        for record_id, group_id in sorted(record_groups)
    ]


def validate_no_group_leakage(records: Iterable[SplitRecord]) -> list[str]:
    group_splits: dict[str, set[str]] = defaultdict(set)
    for record in records:
        group_splits[record.group_id].add(record.split)
    return [group for group, splits in group_splits.items() if len(splits) > 1]
