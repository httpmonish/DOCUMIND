#!/usr/bin/env python3
"""scripts/fetch_squad.py -- Download SQuAD 2.0 dev dataset and verify MD5 checksum."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

SQUAD_DEV_URL = "https://rajpurkar.github.io/SQuAD-explorer/dataset/dev-v2.0.json"
EXPECTED_MD5 = "246adae8b7002f8679c027697b0b7cf8"
DEST_PATH = Path(__file__).parent.parent / "evals" / "data" / "dev-v2.0.json"


def main() -> None:
    DEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    if DEST_PATH.exists():
        print(f"File already exists at {DEST_PATH}, verifying MD5...")
        data = DEST_PATH.read_bytes()
    else:
        print(f"Downloading SQuAD 2.0 dev from {SQUAD_DEV_URL}...")
        with urllib.request.urlopen(SQUAD_DEV_URL) as response:  # noqa: S310
            data = response.read()
        DEST_PATH.write_bytes(data)
        print(f"Saved {len(data)} bytes to {DEST_PATH}")

    actual_md5 = hashlib.md5(data, usedforsecurity=False).hexdigest()  # noqa: S324
    print(f"Actual MD5:   {actual_md5}")
    print(f"Expected MD5: {EXPECTED_MD5}")

    if actual_md5 == EXPECTED_MD5:
        print("Checksum verification: PASSED")
    else:
        print("WARNING: Checksum mismatch! Verify source at rajpurkar.github.io/SQuAD-explorer/")


if __name__ == "__main__":
    main()
