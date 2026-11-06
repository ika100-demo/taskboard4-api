"""Environment-based settings."""

from __future__ import annotations

import os


class MissingSetting(RuntimeError):  # noqa: N818 - name fixed by the contract
    """A required environment variable is unset or blank."""


def load_database_url() -> str:
    """Return the stripped `DATABASE_URL`; raise `MissingSetting` when unset or blank."""
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise MissingSetting("DATABASE_URL is not set")
    return value
