import json
from pathlib import Path

import pytest
from sqlalchemy import select

from careeros.claims import service as svc
from careeros.correlate.engine import rebuild_episodes
from careeros.export.markdown import export_markdown
from careeros.fixtures import demo
from careeros.ingest.files import handoff, ingest_ready_dir
from careeros.lifecycle.purge import purge_source
from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import Activity, ConnectorInstance, PurgeMarker, SourceObservation
from careeros.correlate.project import ensure_self, project_activities

CANARIES = [b"Alex coordinated", b"October B release", b"on-call burden canary"]


def scan(root: Path, needles) -> list[str]:
    hits = []
    for p in root.rglob("*"):
        if p.is_file():
            data = p.read_bytes()
            hits += [f"{p.name}:{n.decode()}" for n in needles if n in data]
    return hits


@pytest.fixture
def world(tmp_path):
    engine = make_engine(tmp_path / "data" / "t.db") if (tmp_path / "data").mkdir() is None else None
    init_db(engine)
    inbox, exports = tmp_path / "data" / "inbox", tmp_path / "data" / "exports"
    with make_session_factory(engine)() as s:
        for cid, (stype, ns) in demo.CONNECTORS.items():
            s.add(ConnectorInstance(id=cid, source_type=stype, namespace=ns))
        s.commit()
        ensure_self(s, demo.SELF_EMAIL)
        s.commit()
        for env in demo.initial_envelopes():
            handoff(env, inbox)
        counts = ingest_ready_dir(s, inbox, demo.approvals(), now=demo.T0)
        assert counts["committed"] == 3, counts
        project_activities(s)
        rebuild_episodes(s)
        anchor = s.scalar(select(Activity).where(Activity.title.contains("R-2026-10-B")))
        svc.draft_episode(s, anchor.id)
        from careeros.storage.models import Claim
        cs = list(s.scalars(select(Claim).where(Claim.anchor_activity_id == anchor.id)))
        for c in cs:
            if c.layer == "observation":
                svc.approve(s, c.id, batch=True)
        impact = svc.add_impact_claim(s, anchor.id, "Cut on-call burden canary")
        svc.approve(s, impact)
        ids = [c.id for c in cs if c.layer == "observation"] + [impact]
        svc.publish(s, anchor.id, ids)
        export_markdown(s, anchor.id, exports)
        yield tmp_path / "data", s, inbox, exports, anchor


def test_file_ingest_is_idempotent_and_moves_files(world):
    data, s, inbox, exports, _ = world
    assert list((inbox / "ready").glob("*")) == [] and len(list((inbox / "processed").glob("*"))) == 3
    handoff(demo.sheet_week1(), inbox)  # re-delivery of an already committed export
    assert ingest_ready_dir(s, inbox, demo.approvals(), now=demo.T0)["duplicate"] == 1


def test_rejected_file_with_prohibited_field_is_deleted(world):
    data, s, inbox, *_ = world
    bad = demo.sheet_deployed().model_copy(deep=True)
    bad.export_id = "bad-1"
    bad.cursor_before = "s2"
    bad.records[0].fields["body"] = "PROHIBITED-BODY"
    handoff(bad, inbox)
    assert ingest_ready_dir(s, inbox, demo.approvals(), now=demo.T0)["rejected"] == 1
    assert scan(data, [b"PROHIBITED-BODY"]) == []


def test_exported_markdown_has_layers_and_provenance(world):
    data, s, inbox, exports, anchor = world
    md = next(exports.glob("*.md")).read_text()
    assert "SYNTHETIC DEMO DATA" in md
    assert "[observation | human_approved]" in md and "[interpretation | human_approved]" in md
    assert "cos://obs/" in md and "([source](https://" in md


def test_purge_removes_canaries_everywhere_but_leaves_other_sources(world):
    data, s, inbox, exports, anchor = world
    assert scan(data, CANARIES), "canaries should exist before purge"
    rep = purge_source(s, demo.SHEET, inbox=inbox, export_dir=exports, reason="test")
    assert scan(data, CANARIES) == []  # db, -wal, -shm, inbox, exports
    assert rep.versions_withdrawn >= 1 and rep.observations > 0
    assert not list(exports.glob("*.md"))
    # git source untouched; purge left only a content-free marker
    assert scan(data, [b"DEMO-101"])
    assert s.scalar(select(PurgeMarker)).entity_ref == "connector:demo-sheet"
    assert s.scalar(select(SourceObservation).limit(1)) is not None
