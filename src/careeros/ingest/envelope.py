"""Import envelope schema (see plan §3)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

MAX_RECORDS = 10_000


class EnvelopeRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    native_record_id: str
    source_updated_at: datetime | None = None
    fields: dict[str, Any]


class Tombstone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    native_record_id: str


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int
    connector_instance_id: str
    export_id: str
    export_mode: Literal["snapshot", "delta"]
    # {"kind": "all"} marks a whole-connector scope; only that scope can
    # justify inferring deletion from absence in a complete snapshot.
    scope: dict[str, Any]
    coverage_start: datetime | None = None
    coverage_end: datetime | None = None
    collection_started_at: datetime
    collection_completed_at: datetime
    complete: bool
    cursor_before: str | None = None
    cursor_after: str | None = None
    records: list[EnvelopeRecord]
    explicit_tombstones: list[Tombstone] = []
