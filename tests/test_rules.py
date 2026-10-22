"""Labeled failure-class matrix (plan §5). Each class has a bad claim that must
be flagged and, where it matters, a good twin that must pass."""
import pytest

from careeros.claims.rules import ClaimView, SupportView, check

REL = "R-2026-10-B"


def sup(text, record=REL, **kw):
    return SupportView(observation_id=1, excerpt=text, record_id=record, **kw)


def claim(supports, **kw):
    base = dict(layer="observation", subject="release", status="completed")
    base.update(kw)
    return ClaimView(supports=supports, **base)


def codes(c):
    return {v.split(":")[0] for v in check(c)}


def test_good_observation_passes():
    c = claim([sup("Team deployed 12 changes")], subject="team", metric_value=12,
              metric_unit="changes", metric_scope=REL)
    assert check(c) == []


def test_uncited():
    assert "uncited" in codes(claim([]))


def test_role_inflation():
    # evidence shows 'author'; claim says 'lead'
    c = claim([sup("Merge pull request #1", self_roles={"author"})], layer="attribution",
              subject="I", contribution_role="lead")
    assert "role_not_supported" in codes(c)


def test_team_to_self_attribution():
    c = claim([sup("Team deployed 12 changes", self_roles={"author"})], layer="attribution",
              subject="team", contribution_role="author")
    assert "team_result_claimed_as_self" in codes(c)


def test_first_person_without_role():
    assert "first_person_without_role" in codes(claim([sup("Team deployed 12 changes")], subject="I"))


def test_planned_to_completed():
    c = claim([sup("Planned")], status="completed")
    assert "no_completion_evidence" in codes(c)


def test_target_to_actual():
    c = claim([sup("Deployed. Target: 20% fewer failed deployments")], metric_value=20,
              metric_unit="%", metric_scope=REL)
    assert "metric_is_target" in codes(c)


def test_target_stated_as_planned_is_fine():
    c = claim([sup("Target: 20% fewer failed deployments")], status="planned", metric_value=20,
              metric_unit="%", metric_scope=REL)
    assert check(c) == []


def test_cross_scope_metric_reuse():
    c = claim([sup("Team deployed 12 changes", record="R-2026-09-A")], subject="team",
              metric_value=12, metric_unit="changes", metric_scope=REL)
    assert "metric_scope_mismatch" in codes(c)


def test_invented_number():
    c = claim([sup("Team deployed 12 changes")], subject="team", metric_value=15,
              metric_unit="changes", metric_scope=REL)
    assert "metric_not_in_evidence" in codes(c)


def test_number_substring_is_not_a_match():
    c = claim([sup("Team deployed 120 changes")], subject="team", metric_value=12,
              metric_unit="changes", metric_scope=REL)
    assert "metric_not_in_evidence" in codes(c)


def test_ignoring_contradiction():
    c = claim([sup("Deployed"), sup("Rolled back", polarity="contradicts")])
    assert "contradicted" in codes(c)


def test_ignoring_later_evidence():
    assert "stale_evidence" in codes(claim([sup("Deployed", is_current=False)]))


def test_deployment_to_impact():
    c = claim([sup("Deployed")], layer="interpretation", subject="release")
    assert "interpretation_not_user_authored" in codes(c)


def test_user_authored_impact_passes():
    c = claim([sup("Fewer failed deploys saved on-call time")], layer="interpretation",
              authored_by="user", status="completed")
    assert check(c) == []


def test_evidence_from_unlinked_activity_is_stale():
    c = claim([sup("Merge pull request #1", in_episode=False)])
    assert "stale_link" in codes(c)
