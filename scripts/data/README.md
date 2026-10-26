# R1 acquisition commands

Run commands from the repository root with Python 3.12 or newer.

```powershell
python scripts/data/download_dataset.py --list
python scripts/data/download_dataset.py --all-small
python scripts/data/download_dataset.py --dataset FOODON
python scripts/data/verify_downloads.py
python scripts/validate_r1.py
```

The registry contains only bounded official downloads with byte limits. Existing final files are
reused and checksummed, not overwritten; use `--force` only when intentionally replacing a
mutable upstream snapshot. Interrupted downloads retain a `.part` file and resume when the
server supports byte ranges.

Open Food Facts full exports are excluded from the default registry because they are large and
mutable. `download_open_food_facts.py` prints instructions by default and requires both
`--mode full` and `--allow-large`. Manual or restricted sources are covered by
`documentation/datasets/manual-acquisition.md`; no script bypasses registration or terms.
