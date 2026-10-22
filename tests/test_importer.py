from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from careeros.ingest.envelope import Envelope
from careeros.ingest.importer import Approval, ImportRejected, import_envelope
from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import (
    ConnectorInstance, ImportBatch, SourceObservation, SourceRecord,
)

T0 = datetime(2026, 10, 1, 12, 0)
CI = "sheet-1"


@pytest.fixture
def s(tmp_path):
    engine = make_engine(tmp_path / "t.db")
    init_db(engine)
    with make_session_factory(engine)() as session:
        session.add(ConnectorInstance(id=CI, source_type="release_sheet", namespace="demo"))
        session.commit()
        yield session


APPROVALS = {CI: Approval(CI, frozenset({"title", "status"}), T0 + timedelta(days=365))}


def env(export_id, records, *, before=None, after=None, mode="delta", complete=True,
        scope=None, tombs=(), t=0):
    return Envelope.model_validate({
        "schema_version": 1, "connector_instance_id": CI, "export_id": export_id,
        "export_mode": mode, "scope": scope or {"kind": "rows"},
        "collection_started_at": T0 + timedelta(hours=t),
        "collection_completed_at": T0 + timedelta(hours=t, minutes=1),
        "complete": complete, "cursor_before": before, "cursor_after": after,
        "records": [{"native_record_id": r[0], "fields": r[1],
                     "source_updated_at": T0 + timedelta(hours=r[2] if len(r) > 2 else t)}
                    for r in records],
        "explicit_tombstones": [{"native_record_id": x} for x in tombs],
    })


def count(s, model):
    return s.scalar(select(func.count()).select_from(model))


def test_reimport_same_export_is_noop(s):
    e = env("e1", [("R1", {"title": "A"})], after="c1")
    assert import_envelope(s, e, APPROVALS, now=T0).status == "committed"
    assert import_envelope(s, e, APPROVALS, now=T0).status == "duplicate"
    assert count(s, SourceObservation) == 1


def test_unchanged_content_makes_no_new_observation(s):
    import_envelope(s, env("e1", [("R1", {"title": "A"})], after="c1"), APPROVALS, now=T0)
    r = import_envelope(s, env("e2", [("R1", {"title": "A"})], before="c1", after="c2", t=1), APPROVALS, now=T0)
    assert r.new_observations == 0 and count(s, SourceObservation) == 1


def test_a_b_a_keeps_three_observations(s):
    for i, title in enumerate(["A", "B", "A"]):
        import_envelope(s, env(f"e{i}", [("R1", {"title": title})],
                               before=f"c{i-1}" if i else None, after=f"c{i}", t=i), APPROVALS, now=T0)
    assert count(s, SourceObservation) == 3


def test_stale_record_does_not_override_newer(s):
    import_envelope(s, env("e1", [("R1", {"title": "new"}, 5)], after="c1"), APPROVALS, now=T0)
    r = import_envelope(s, env("e2", [("R1", {"title": "old"}, 1)], before="c1", after="c2"), APPROVALS, now=T0)
    assert r.skipped_stale == 1 and count(s, SourceObservation) == 1


def test_partial_export_never_deletes(s):
    import_envelope(s, env("e1", [("R1", {"title": "A"}), ("R2", {"title": "B"})], after="c1"), APPROVALS, now=T0)
    r = import_envelope(s, env("e2", [("R1", {"title": "A"})], before="c1", after="c2",
                               mode="snapshot", complete=False, scope={"kind": "all"}), APPROVALS, now=T0)
    assert r.deleted == 0


def test_complete_snapshot_of_scoped_subset_never_deletes(s):
    import_envelope(s, env("e1", [("R1", {"title": "A"}), ("R2", {"title": "B"})], after="c1"), APPROVALS, now=T0)
    r = import_envelope(s, env("e2", [("R1", {"title": "A"})], before="c1", after="c2",
                               mode="snapshot", complete=True, scope={"kind": "rows", "ids": ["R1"]}), APPROVALS, now=T0)
    assert r.deleted == 0


def test_complete_whole_snapshot_deletes_absent(s):
    import_envelope(s, env("e1", [("R1", {"title": "A"}), ("R2", {"title": "B"})], after="c1"), APPROVALS, now=T0)
    r = import_envelope(s, env("e2", [("R1", {"title": "A"})], before="c1", after="c2",
                               mode="snapshot", complete=True, scope={"kind": "all"}), APPROVALS, now=T0)
    assert r.deleted == 1
    sr = s.scalar(select(SourceRecord).where(SourceRecord.native_record_id == "R2"))
    assert s.get(SourceObservation, sr.current_observation_id).state == "deleted"


def test_explicit_tombstone_deletes(s):
    import_envelope(s, env("e1", [("R1", {"title": "A"})], after="c1"), APPROVALS, now=T0)
    r = import_envelope(s, env("e2", [], before="c1", after="c2", tombs=["R1"]), APPROVALS, now=T0)
    assert r.deleted == 1


def test_out_of_order_envelope_is_held(s):
    import_envelope(s, env("e1", [("R1", {"title": "A"})], after="c1"), APPROVALS, now=T0)
    r = import_envelope(s, env("late", [("R1", {"title": "Z"})], before="c0", after="cX"), APPROVALS, now=T0)
    assert r.status == "held_out_of_order" and count(s, SourceObservation) == 1
    assert s.get(ConnectorInstance, CI).checkpoint == "c1"


def test_non_allowlisted_field_rejects_whole_envelope(s):
    e = env("e1", [("R1", {"title": "A"}), ("R2", {"title": "B", "body": "secret"})], after="c1")
    with pytest.raises(ImportRejected):
        import_envelope(s, e, APPROVALS, now=T0)
    assert count(s, SourceObservation) == 0 and count(s, ImportBatch) == 0


def test_unapproved_or_expired_connector_rejected(s):
    e = env("e1", [("R1", {"title": "A"})], after="c1")
    with pytest.raises(ImportRejected):
        import_envelope(s, e, {}, now=T0)
    with pytest.raises(ImportRejected):
        import_envelope(s, e, APPROVALS, now=T0 + timedelta(days=400))


def test_failure_mid_import_rolls_back_and_keeps_checkpoint(s, monkeypatch):
    import careeros.ingest.importer as imp
    calls = {"n": 0}
    real = imp._observe

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("crash")
        return real(*a, **k)

    monkeypatch.setattr(imp, "_observe", boom)
    with pytest.raises(RuntimeError):
        import_envelope(s, env("e1", [("R1", {"title": "A"}), ("R2", {"title": "B"})], after="c1"), APPROVALS, now=T0)
    assert count(s, SourceObservation) == 0 and count(s, ImportBatch) == 0
    assert s.get(ConnectorInstance, CI).checkpoint is None
