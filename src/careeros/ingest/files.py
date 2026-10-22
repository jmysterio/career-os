"""File-drop transport: atomic handoff in, validated ingestion out (plan §3)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..storage.models import AuditEvent
from .envelope import Envelope
from .importer import Approval, ImportRejected, import_envelope

MAX_FILE_BYTES = 5_000_000
DIRS = ("incoming", "ready", "processed")


def inbox_dirs(inbox: Path) -> None:
    for d in DIRS:
        (inbox / d).mkdir(parents=True, exist_ok=True)


def handoff(env: Envelope, inbox: Path) -> Path:
    """Collector side: write .part, fsync, then rename into ready/."""
    inbox_dirs(inbox)
    part = inbox / "incoming" / f"{env.export_id}.json.part"
    with open(part, "w") as fh:
        fh.write(env.model_dump_json())
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(part, 0o600)
    final = inbox / "ready" / f"{env.export_id}.json"
    os.rename(part, final)
    return final


def ingest_ready_dir(session: Session, inbox: Path, approvals: dict[str, Approval],
                     now: datetime | None = None) -> dict[str, int]:
    inbox_dirs(inbox)
    counts = {"committed": 0, "duplicate": 0, "held_out_of_order": 0, "rejected": 0}
    for p in sorted((inbox / "ready").glob("*.json")):
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                raise ImportRejected("file too large")
            res = import_envelope(session, Envelope.model_validate_json(p.read_text()), approvals, now=now)
        except (ImportRejected, ValidationError, ValueError) as exc:
            # A rejected file may hold prohibited data: delete it, log only the error class.
            detail = type(exc).__name__ + (
                f" at {[e['loc'] for e in exc.errors()]}" if isinstance(exc, ValidationError) else "")
            p.unlink()
            session.add(AuditEvent(at=now or datetime.now(timezone.utc).replace(tzinfo=None),
                                   action="import_rejected", entity_ref=f"file:{p.name}", detail=detail))
            session.commit()
            counts["rejected"] += 1
            continue
        counts[res.status] += 1
        if res.status != "held_out_of_order":
            os.rename(p, inbox / "processed" / p.name)
    return counts
