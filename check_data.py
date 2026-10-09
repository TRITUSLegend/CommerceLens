"""Verify that all 9 Olist CSVs are present in DATA_DIR.

Usage:
    python check_data.py

Exits with code 1 (and prints the Kaggle URL + missing files) if any are absent.
"""

import sys

from src.config import DATA_DIR, KAGGLE_URL, REQUIRED_FILES


def main() -> int:
    """Check each required file and report status."""
    print(f"DATA_DIR: {DATA_DIR}\n")
    missing = []
    for name in REQUIRED_FILES:
        path = DATA_DIR / name
        if path.is_file():
            print(f"  [OK]      {name:<42} {path.stat().st_size / 1e6:8.2f} MB")
        else:
            print(f"  [MISSING] {name}")
            missing.append(name)

    if missing:
        print(f"\n{len(missing)} file(s) missing. Download the dataset from:\n  {KAGGLE_URL}")
        print("Unzip the CSVs into DATA_DIR (or set COMMERCELENS_DATA_DIR). Missing:")
        for name in missing:
            print(f"  - {name}")
        return 1

    print(f"\nAll {len(REQUIRED_FILES)} files present.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
