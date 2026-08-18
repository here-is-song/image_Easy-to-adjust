"""Backward-compatible launcher for image_easy-to-adjust (IEA)."""

from iea.cli import main, run

__all__ = ["main", "run"]


if __name__ == "__main__":
    raise SystemExit(main())
