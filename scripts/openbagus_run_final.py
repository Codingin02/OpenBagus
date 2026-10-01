"""Compatibility wrapper for the canonical OpenBagus CLI."""

from openbagus.cli import _delivery_exit_code, main, parse_args

__all__ = ["_delivery_exit_code", "main", "parse_args"]


if __name__ == "__main__":
    raise SystemExit(main())
