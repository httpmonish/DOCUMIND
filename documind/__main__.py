"""Package execution entry point: python -m documind."""

from __future__ import annotations

from documind.interfaces.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
