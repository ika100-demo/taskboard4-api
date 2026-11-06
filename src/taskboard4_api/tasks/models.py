"""Request and response models for tasks."""

import re
from datetime import date
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StrictStr, StringConstraints, field_validator

Title = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TaskCreate(BaseModel):
    """Body of ``POST /tasks``."""

    model_config = ConfigDict(extra="ignore")

    title: Title
    due_date: date | None = None

    @field_validator("due_date", mode="before")
    @classmethod
    def _parse_due_date(cls, value: Any) -> date | None:
        """Accept ``None`` or a strict ``YYYY-MM-DD`` calendar date string."""
        if value is None:
            return None
        if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
            raise ValueError("due_date must be a date in the form YYYY-MM-DD")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("due_date must be a real calendar date") from exc


class Task(BaseModel):
    """A stored task as returned by the API."""

    id: str
    title: str
    due_date: date | None
