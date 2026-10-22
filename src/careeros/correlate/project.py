"""Project current observations into activities, identities, and participation."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..storage.models import (
    Activity, ConnectorInstance, ContentBlob, Identity, Participation,
    SourceObservation, SourceRecord,
)

KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{3,}\b")


def extract_keys(*texts: str | None) -> list[str]:
    found: list[str] = []
    for t in texts:
        for k in KEY_RE.findall(t or ""):
            if k not in found:
                found.append(k)
    return found


def _parse(ts: str | None) -> tuple[datetime | None, str | None]:
    if not ts:
        return None, None
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        return dt, None
    tz = dt.strftime("%z")
    return dt.astimezone(timezone.utc).replace(tzinfo=None), f"{tz[:3]}:{tz[3:]}"


def ensure_self(session: Session, email: str) -> Identity:
    ident = session.scalar(select(Identity).where(Identity.kind == "email", Identity.value == email))
    if ident is None:
        ident = Identity(kind="email", value=email, is_self=True)
        session.add(ident)
        session.flush()
    return ident


def project_activities(session: Session) -> int:
    """Upsert one Activity per source record from its current observation."""
    self_ids = {i.value: i for i in session.scalars(select(Identity).where(Identity.is_self))}
    n = 0
    for sr in session.scalars(select(SourceRecord)):
        if sr.current_observation_id is None:
            continue
        obs = session.get(SourceObservation, sr.current_observation_id)
        ci = session.get(ConnectorInstance, sr.connector_instance_id)
        act = session.scalar(select(Activity).where(Activity.source_record_id == sr.id))
        if obs.state == "deleted":
            if act is not None:
                act.state = "deleted"
                act.derived_from_observation_id = obs.id
            continue
        f = session.get(ContentBlob, obs.content_blob_id).minimized_payload
        if ci.source_type == "release_sheet":
            at, tz = _parse(f.get("deployed_at"))
            vals = dict(type="release_row", title=f"{f['release_id']}: {f.get('title', '')}",
                        source_url=f.get("url"), occurred_at_utc=at, source_tz=tz,
                        keys=extract_keys(f.get("notes"), f.get("title")))
        elif ci.source_type == "git":
            at, tz = _parse(f.get("committed_at"))
            vals = dict(type="merge_commit" if f.get("is_merge") else "commit",
                        title=f["subject"], source_url=f.get("url"), occurred_at_utc=at,
                        source_tz=tz, keys=extract_keys(f["subject"], f.get("branch")))
        else:
            at, tz = _parse(f.get("created_at"))
            vals = dict(type="manual_note", title=f["text"][:80], source_url=None,
                        occurred_at_utc=at, source_tz=tz, keys=extract_keys(f["text"]))
        if act is None:
            act = Activity(source_record_id=sr.id, derived_from_observation_id=obs.id, **vals)
            session.add(act)
            session.flush()
        else:
            for k, v in vals.items():
                setattr(act, k, v)
            act.state = "present"
            act.derived_from_observation_id = obs.id
        session.execute(delete(Participation).where(Participation.activity_id == act.id))
        if ci.source_type == "git" and f.get("author_email") in self_ids:
            session.add(Participation(activity_id=act.id, identity_id=self_ids[f["author_email"]].id,
                                      role="author", assertion_source="git_author"))
        n += 1
    session.commit()
    return n
