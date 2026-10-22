"""Synthetic fixture story. Everything here is fake and flagged is_fixture.

Traps built in (see plan §8):
 - DEMO-999 merge on the deploy day shares no key -> must not link.
 - A merge citing DEMO-102 and DEMO-201 matches two release rows -> suggested only.
 - Sheet note "team deployed 12 changes; Alex coordinated" -> never first-person.
 - "Target: 20% ..." -> never an achieved metric.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from ..ingest.envelope import Envelope
from ..ingest.importer import Approval

SELF_EMAIL = "demo.user@example.com"
OTHER_EMAIL = "alex@example.com"
SHEET = "demo-sheet"
GIT = "demo-git"
MANUAL = "manual"

CONNECTORS = {
    SHEET: ("release_sheet", "demo/release-schedule"),
    GIT: ("git", "demo/repo"),
    MANUAL: ("manual", "local"),
}
ALLOWED = {
    SHEET: {"release_id", "title", "status", "notes", "deployed_at", "owner_email", "url"},
    GIT: {"sha", "subject", "author_email", "committed_at", "branch", "is_merge", "url"},
    MANUAL: {"text", "created_at"},
}
T0 = datetime(2026, 10, 12, 9, 0)


def approvals(now: datetime | None = None) -> dict[str, Approval]:
    exp = (now or T0) + timedelta(days=365)
    return {cid: Approval(cid, frozenset(f), exp) for cid, f in ALLOWED.items()}


def _env(cid, export_id, records, *, before, after, mode="delta", complete=True,
         scope=None, tombs=(), hours=0) -> Envelope:
    return Envelope.model_validate({
        "schema_version": 1, "connector_instance_id": cid, "export_id": export_id,
        "export_mode": mode, "scope": scope or {"kind": "rows"},
        "collection_started_at": T0 + timedelta(hours=hours),
        "collection_completed_at": T0 + timedelta(hours=hours, minutes=1),
        "complete": complete, "cursor_before": before, "cursor_after": after,
        "records": [{"native_record_id": nid, "fields": f, "source_updated_at": T0 + timedelta(hours=hours)}
                    for nid, f in records],
        "explicit_tombstones": [{"native_record_id": x} for x in tombs],
    })


def _row(rid, status, notes, title, deployed=None):
    return (rid, {"release_id": rid, "title": title, "status": status, "notes": notes,
                  "deployed_at": deployed, "owner_email": OTHER_EMAIL,
                  "url": f"https://sheets.example.com/demo#{rid}"})


def _commit(sha, subject, branch, when, author=SELF_EMAIL, merge=True):
    return (sha, {"sha": sha, "subject": subject, "author_email": author, "committed_at": when,
                  "branch": branch, "is_merge": merge, "url": f"https://git.example.com/demo/commit/{sha}"})


NOTES_PLANNED_B = "Target: 20% fewer failed deployments. Stories DEMO-101, DEMO-102."
NOTES_DONE_B = NOTES_PLANNED_B + " Team deployed 12 changes; Alex coordinated."


def sheet_week1() -> Envelope:
    return _env(SHEET, "sheet-1", [
        _row("R-2026-10-B", "Planned", NOTES_PLANNED_B, "October B release"),
        _row("R-2026-10-C", "Planned", "Stories DEMO-201.", "October C release"),
    ], before=None, after="s1", mode="snapshot", scope={"kind": "all"})


def git_week1() -> Envelope:
    return _env(GIT, "git-1", [
        _commit("a1b2c3d", "Merge pull request #1 from feature/DEMO-101-fix-validation",
                "main", "2026-10-12T10:15:00-07:00"),
        _commit("b2c3d4e", "Merge pull request #2 from feature/DEMO-102-pipeline-gate",
                "main", "2026-10-13T14:00:00-07:00"),
        _commit("c3d4e5f", "Merge pull request #3 from feature/DEMO-999-readme",
                "main", "2026-10-14T15:00:00-07:00"),
        _commit("d4e5f6a", "Share deploy script for DEMO-102 and DEMO-201",
                "main", "2026-10-13T16:00:00-07:00", merge=False),
    ], before=None, after="g1", hours=1)


def sheet_deployed() -> Envelope:
    return _env(SHEET, "sheet-2", [
        _row("R-2026-10-B", "Deployed", NOTES_DONE_B, "October B release",
             deployed="2026-10-14T22:30:00-07:00"),
    ], before="s1", after="s2", hours=48)


def sheet_title_edit() -> Envelope:
    return _env(SHEET, "sheet-3", [
        _row("R-2026-10-B", "Deployed", NOTES_DONE_B, "October B release (renamed)",
             deployed="2026-10-14T22:30:00-07:00"),
    ], before="s2", after="s3", hours=72)


def sheet_tombstone_c() -> Envelope:
    return _env(SHEET, "sheet-4", [], before="s3", after="s4", hours=96, tombs=["R-2026-10-C"])


def initial_envelopes() -> list[Envelope]:
    return [sheet_week1(), git_week1(), sheet_deployed()]
