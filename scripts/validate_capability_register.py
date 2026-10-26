from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

REGISTER = Path("documentation/project-management/capability-register.csv")
STATUSES = {"NOT_STARTED", "SCAFFOLDED", "IN_PROGRESS", "IMPLEMENTED", "TESTED", "COMPLETE"}
PRIORITIES = {"LOW", "MEDIUM", "HIGH"}
MODULES = {
    1: "Food Understanding Engine",
    2: "Ingredient Intelligence Engine",
    3: "Food Knowledge Intelligence",
    4: "Personalized Health Intelligence",
    5: "Explainable AI Engine",
    6: "Recommendation Intelligence Engine",
    7: "Personal Nutrition Intelligence",
    8: "Smart Cooking & Pantry Intelligence",
    9: "Nutrition Analytics & Visualization",
    10: "Population & Research Intelligence",
    11: "AI Nutrition Assistant",
    12: "Data & AI Infrastructure",
    13: "Backend Services",
    14: "Cross-Platform User Experience",
    15: "Security, Privacy & Cloud Infrastructure",
}
STATUS_COLUMNS = {
    "Implementation status",
    "Backend status",
    "Web status",
    "Mobile status",
    "AI/model status",
    "Database status",
    "Security status",
    "Multilingual status",
    "Test status",
}


def main() -> None:
    with REGISTER.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))

    assert len(rows) >= 90, "Register must contain at least 90 capabilities"
    ids = [row["Capability ID"] for row in rows]
    assert len(ids) == len(set(ids)), "Capability IDs must be unique"

    for row in rows:
        module_number = int(row["Module number"])
        assert MODULES[module_number] == row["Module name"], row["Capability ID"]
        assert row["Target release"].startswith("R") and 0 <= int(row["Target release"][1:]) <= 21
        assert row["Priority"] in PRIORITIES
        for column in STATUS_COLUMNS:
            assert row[column] in STATUSES, f"{row['Capability ID']}: invalid {column}"

    module_counts = Counter(row["Module name"] for row in rows)
    status_counts = Counter(row["Implementation status"] for row in rows)
    print(f"Validated {len(rows)} capabilities across {len(module_counts)} modules")
    for name, count in sorted(module_counts.items()):
        print(f"{name}: {count}")
    print("Statuses:", dict(sorted(status_counts.items())))


if __name__ == "__main__":
    main()
