from sqlalchemy import select

from careeros.correlate.engine import link, rebuild_episodes, unlink
from careeros.storage.models import Activity, EpisodeMember


def act(s, title_part):
    return s.scalar(select(Activity).where(Activity.title.contains(title_part)))


def members(s, anchor):
    return {(act_.title, m.status, m.origin) for m in s.scalars(
        select(EpisodeMember).where(EpisodeMember.anchor_activity_id == anchor.id))
        for act_ in [s.get(Activity, m.activity_id)]}


def test_explicit_key_links_and_same_day_does_not(demo_session):
    s = demo_session
    rebuild_episodes(s)
    b = act(s, "R-2026-10-B")
    titles = {t for t, st, o in members(s, b) if st == "linked"}
    assert any("DEMO-101" in t for t in titles) and any("DEMO-102-pipeline" in t for t in titles)
    # DEMO-999 merge landed on the deploy day but shares no key.
    all_member_ids = {m.activity_id for m in s.scalars(select(EpisodeMember))}
    assert act(s, "DEMO-999").id not in all_member_ids


def test_key_shared_by_two_rows_is_only_suggested(demo_session):
    s = demo_session
    rebuild_episodes(s)
    shared = act(s, "Share deploy script")
    rows = s.scalars(select(EpisodeMember).where(EpisodeMember.activity_id == shared.id)).all()
    assert len(rows) == 2 and all(r.status == "suggested" and r.origin == "ambiguous" for r in rows)


def test_cannot_link_survives_rebuild(demo_session):
    s = demo_session
    rebuild_episodes(s)
    b, m1 = act(s, "R-2026-10-B"), act(s, "DEMO-101")
    unlink(s, m1.id, b.id)
    rebuild_episodes(s)
    rebuild_episodes(s)
    assert m1.id not in {m.activity_id for m in s.scalars(select(EpisodeMember))}


def test_must_link_survives_rebuild_and_overrides_key_absence(demo_session):
    s = demo_session
    rebuild_episodes(s)
    b, unrelated = act(s, "R-2026-10-B"), act(s, "DEMO-999")
    link(s, unrelated.id, b.id)
    rebuild_episodes(s)
    m = s.scalar(select(EpisodeMember).where(EpisodeMember.activity_id == unrelated.id))
    assert m.origin == "manual" and m.status == "linked"
    unlink(s, unrelated.id, b.id)
    assert s.scalar(select(EpisodeMember).where(EpisodeMember.activity_id == unrelated.id)) is None


def test_deleted_row_drops_out_of_episodes(demo_session):
    s = demo_session
    from careeros.fixtures import demo
    from careeros.ingest.importer import import_envelope
    from careeros.correlate.project import project_activities
    import_envelope(s, demo.sheet_tombstone_c(), demo.approvals(), now=demo.T0)  # stale cursor -> held
    # chain is s2 now, so build a valid tombstone for current checkpoint
    env = demo.sheet_tombstone_c().model_copy(update={"cursor_before": "s2"})
    import_envelope(s, env, demo.approvals(), now=demo.T0)
    project_activities(s)
    rebuild_episodes(s)
    c = act(s, "R-2026-10-C")
    assert c.state == "deleted"
    assert s.scalar(select(EpisodeMember).where(EpisodeMember.anchor_activity_id == c.id)) is None
