"""Markdown export of the active accomplishment version (plan §8.7)."""
from __future__ import annotations

import os
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..claims import service as svc
from ..storage.models import (
    AccomplishmentVersion, Activity, Claim, ClaimSupport, ConnectorInstance, ExportRecord,
    SourceObservation, SourceRecord,
)


def esc(text: str) -> str:
    """Imported text is untrusted: neutralize markdown links, code, and HTML."""
    return re.sub(r"([\[\]()`<>*_|\\])", r"\\\1", text.replace("\n", " "))


def export_markdown(s: Session, anchor_id: int, export_dir: Path) -> Path:
    v = s.scalar(select(AccomplishmentVersion).where(
        AccomplishmentVersion.anchor_activity_id == anchor_id, AccomplishmentVersion.state == "active"))
    if v is None:
        raise ValueError("no active accomplishment version to export")
    anchor = s.get(Activity, anchor_id)
    stale = svc.stale_versions(s).get(v.id)
    fixture = any(c.is_fixture for c in s.scalars(select(ConnectorInstance)))
    lines = [f"# {esc(anchor.title)} (v{v.version})", ""]
    if fixture:
        lines += ["> SYNTHETIC DEMO DATA", ""]
    if stale:
        lines += ["> NEEDS REVIEW: cited evidence changed after approval.", ""]
    obs_ids: set[int] = set()
    for cid in v.claim_ids:
        c = s.get(Claim, cid)
        lines.append(f"- **[{c.layer} | {c.verification_status}]** {esc(svc.render_claim(c))}")
        for sup in s.scalars(select(ClaimSupport).where(ClaimSupport.claim_id == cid)):
            obs_ids.add(sup.observation_id)
            obs = s.get(SourceObservation, sup.observation_id)
            act = s.scalar(select(Activity).where(Activity.source_record_id == obs.source_record_id))
            link = f" ([source]({act.source_url}))" if act and act.source_url else ""
            lines.append(f"  - evidence `{svc.provenance_ref(sup)}` ({sup.polarity}){link}")
    lines.append("")
    export_dir.mkdir(parents=True, exist_ok=True)
    path = export_dir / f"accomplishment-{anchor_id}-v{v.version}.md"
    path.write_text("\n".join(lines))
    os.chmod(path, 0o600)
    s.add(ExportRecord(path=str(path), observation_ids=sorted(obs_ids)))
    s.commit()
    return path
