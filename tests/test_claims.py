import pytest
from sqlalchemy import select

from careeros.claims import service as svc
from careeros.correlate.engine import rebuild_episodes
from careeros.correlate.project import project_activities
from careeros.fixtures import demo
from careeros.ingest.importer import import_envelope
from careeros.storage.models import AccomplishmentVersion, Activity, Claim


@pytest.fixture
def ep(demo_session):
    s = demo_session
    rebuild_episodes(s)
    anchor = s.scalar(select(Activity).where(Activity.title.contains("R-2026-10-B")))
    unknowns = svc.draft_episode(s, anchor.id)
    return s, anchor, unknowns


def claims(s, anchor):
    return list(s.scalars(select(Claim).where(Claim.anchor_activity_id == anchor.id)))


def test_traps_do_not_become_first_person_or_achieved(ep):
    s, anchor, _ = ep
    cs = claims(s, anchor)
    team = next(c for c in cs if c.subject == "team")
    assert team.contribution_role is None and team.metric_scope == "R-2026-10-B"
    target = next(c for c in cs if c.action == "targeted")
    assert target.status == "planned"
    # nothing claims 12 changes in first person
    assert not any(c.subject == "I" and "12" in c.object for c in cs)
    # no machine-generated interpretation, and the unknowns ask for impact
    assert not any(c.layer == "interpretation" for c in cs)


def test_unknowns_ask_for_impact_and_flag_ambiguous_link(ep):
    _, _, unknowns = ep
    assert any("Why did this matter" in u for u in unknowns)
    assert any("part of this release" in u for u in unknowns)


def test_attribution_only_for_self_authored_linked_merges(ep):
    s, anchor, _ = ep
    attrib = [c for c in claims(s, anchor) if c.layer == "attribution"]
    assert {c.object.split()[1] for c in attrib} == {"a1b2c3d", "b2c3d4e"}
    assert all(c.verification_status == "rule_checked" and c.contribution_role == "author" for c in attrib)


def test_batch_approval_only_observation(ep):
    s, anchor, _ = ep
    attrib = next(c for c in claims(s, anchor) if c.layer == "attribution")
    with pytest.raises(svc.ClaimBlocked):
        svc.approve(s, attrib.id, batch=True)
    svc.approve(s, attrib.id)
    assert s.get(Claim, attrib.id).verification_status == "human_approved"


def test_publish_requires_approval_and_impact_is_user_authored(ep):
    s, anchor, _ = ep
    obs_claim = next(c for c in claims(s, anchor) if c.layer == "observation")
    with pytest.raises(svc.ClaimBlocked):
        svc.publish(s, anchor.id, [obs_claim.id])
    svc.approve(s, obs_claim.id, batch=True)
    impact = svc.add_impact_claim(s, anchor.id, "Fewer failed deployments reduced on-call load")
    svc.approve(s, impact)
    v = svc.publish(s, anchor.id, [obs_claim.id, impact])
    assert v.state == "active" and "on-call" in v.rendered_text
    v2 = svc.publish(s, anchor.id, [obs_claim.id])
    s.refresh(v)
    assert v.state == "superseded" and v2.version == 2


def test_source_edit_after_approval_flags_version_and_blocks_reapproval(ep):
    s, anchor, _ = ep
    status_claim = next(c for c in claims(s, anchor) if c.action == "has status")
    svc.approve(s, status_claim.id, batch=True)
    v = svc.publish(s, anchor.id, [status_claim.id])
    assert svc.stale_versions(s) == {}
    import_envelope(s, demo.sheet_title_edit(), demo.approvals(), now=demo.T0)
    project_activities(s)
    assert v.id in svc.stale_versions(s)
    with pytest.raises(svc.ClaimBlocked):
        svc.approve(s, status_claim.id)


def test_redraft_after_edit_creates_fresh_claim_and_keeps_published_one(ep):
    s, anchor, _ = ep
    status_claim = next(c for c in claims(s, anchor) if c.action == "has status")
    svc.approve(s, status_claim.id, batch=True)
    svc.publish(s, anchor.id, [status_claim.id])
    import_envelope(s, demo.sheet_title_edit(), demo.approvals(), now=demo.T0)
    project_activities(s)
    svc.draft_episode(s, anchor.id)
    same = [c for c in claims(s, anchor) if c.action == "has status"]
    assert len(same) == 2 and {c.verification_status for c in same} == {"human_approved", "rule_checked"}


def test_edit_resets_verification(ep):
    s, anchor, _ = ep
    c = next(c for c in claims(s, anchor) if c.action == "has status")
    svc.approve(s, c.id, batch=True)
    svc.edit_claim(s, c.id, object="Deployed")
    assert s.get(Claim, c.id).verification_status in ("rule_checked", "unverified")


def test_withdraw(ep):
    s, anchor, _ = ep
    c = next(c for c in claims(s, anchor) if c.action == "has status")
    svc.approve(s, c.id, batch=True)
    v = svc.publish(s, anchor.id, [c.id])
    svc.withdraw(s, v.id, "confidentiality")
    assert s.get(AccomplishmentVersion, v.id).state == "withdrawn"


def test_unlinking_blocks_approved_claim_and_flags_published_version(ep):
    from careeros.correlate.engine import unlink
    s, anchor, _ = ep
    m1 = s.scalar(select(Activity).where(Activity.title.contains("DEMO-101")))
    attrib = next(c for c in claims(s, anchor) if c.layer == "attribution" and "a1b2c3d" in c.object)
    svc.approve(s, attrib.id)
    v = svc.publish(s, anchor.id, [attrib.id])
    unlink(s, m1.id, anchor.id)
    assert any(x.startswith("stale_link") for x in svc.violations(s, attrib))
    assert v.id in svc.stale_versions(s)
    with pytest.raises(svc.ClaimBlocked):
        svc.approve(s, attrib.id)
