import json
from datetime import date

import pytest
from sqlalchemy import select

from careeros.github import connector as gh
from careeros.storage.models import JournalAttachment, JournalEntry, SyncRun
from careeros.storage.removal import add_skip_rule, remove_entry

ORG = "p-amers-us-irs-crm/ccirsgov-org"


def pr(n, title, repo=ORG, author="jtetzelSFDC", closed="2026-10-20T18:00:00Z"):
    return dict(number=n, title=title, url=f"https://github.com/{repo}/pull/{n}", author={"login": author},
                repository={"nameWithOwner": repo}, closedAt=closed, updatedAt="2026-10-21T12:00:00Z")


MINE = [pr(1, "Add sandbox refresh job"), pr(2, "Career OS thing", repo="jmysterio/career-os")]
REVIEWED = [pr(7, "Fix deploy gate", author="abirchfieldSFDC"), pr(1, "Add sandbox refresh job"),
            pr(8, "Still open", author="someone", closed=None),
            pr(9, "Last week", author="someone", closed="2026-10-14T15:00:00Z")]


@pytest.fixture
def fake_gh(monkeypatch):
    monkeypatch.setattr(gh, "PAUSE", 0)
    state = dict(calls=[], reviewed=list(REVIEWED))

    def run(*args):
        state["calls"].append(args)
        if args[:2] == ("api", "user"):
            return "jtetzelSFDC\n"
        return json.dumps(MINE if "--author=@me" in args else state["reviewed"])
    monkeypatch.setattr(gh, "_gh", run)
    return state


def pull(s, since=date(2026, 10, 1), today=date(2026, 10, 25)):
    return gh.merge(s, gh.fetch(since, today)[1])


def entries(s):
    return list(s.scalars(select(JournalEntry).where(JournalEntry.source == "github").order_by(JournalEntry.id)))


def listed(s, e):
    return s.scalar(select(JournalAttachment.body).where(JournalAttachment.entry_id == e.id))


def test_merged_prs_one_each_and_reviews_one_per_repo_per_week(session, fake_gh):
    assert pull(session) == dict(added=4, updated=0, skipped=0)
    assert pull(session) == dict(added=0, updated=0, skipped=0)
    by_id = {e.external_id: e for e in entries(session)}
    merged = by_id[f"gh:{ORG}#1:author"]
    assert merged.text == f"Merged PR: Add sandbox refresh job ({ORG}#1)" and merged.day == "2026-10-20"
    assert listed(session, merged).endswith("/pull/1")
    week = by_id[gh.week_key(ORG, date(2026, 10, 19))]
    assert week.text == f"Reviewed 2 pull requests in {ORG}, week of Oct 19"  # your own PR #1 isn't a review
    assert week.day == "2026-10-21" and "Fix deploy gate" in listed(session, week)  # open PR #8: last update
    assert by_id[gh.week_key(ORG, date(2026, 10, 12))].text.startswith("Reviewed 1 pull request in")
    assert all(e.kind == "task" and e.status == "done" for e in by_id.values())
    assert session.scalar(select(SyncRun).where(SyncRun.source == "github"))


def test_a_week_grows_as_more_reviews_arrive(session, fake_gh):
    pull(session)
    fake_gh["reviewed"].append(pr(10, "Thursday review", author="someone", closed="2026-10-22T15:00:00Z"))
    assert pull(session) == dict(added=0, updated=1, skipped=0)
    week = next(e for e in entries(session) if e.external_id == gh.week_key(ORG, date(2026, 10, 19)))
    assert week.text.startswith("Reviewed 3 pull requests") and week.day == "2026-10-22"
    assert listed(session, week).count("\n") == 2


def test_reviews_are_searched_a_month_at_a_time(session, fake_gh):
    gh.fetch(date(2025, 10, 29), date(2026, 10, 29))
    searches = [c for c in fake_gh["calls"] if "--reviewed-by=@me" in c]
    assert len(searches) == 12 and "--updated=2025-10-29..2025-11-28" in searches[0]
    assert searches[-1][-5].endswith("..2026-10-29")
    assert any("--merged-at=>=2025-10-29" in c for c in fake_gh["calls"])


def test_skip_rule_and_remove_keep_prs_out(session, fake_gh):
    add_skip_rule(session, "jmysterio/career-os", "github")
    assert pull(session)["skipped"] == 1
    week = next(e for e in entries(session) if "week of Oct 19" in e.text)
    remove_entry(session, week.id)
    fake_gh["reviewed"].append(pr(10, "Thursday review", author="someone", closed="2026-10-22T15:00:00Z"))
    assert pull(session)["added"] == 0
    assert not any("week of Oct 19" in e.text for e in entries(session))
    assert add_skip_rule(session, ORG, "github") == 2  # a new rule clears matching records already here
    assert entries(session) == []


def test_signed_out_gh_is_a_clear_error(monkeypatch):
    def run(*args):
        raise gh.GitHubError("not logged in")
    monkeypatch.setattr(gh, "_gh", run)
    with pytest.raises(gh.GitHubError, match="gh auth login"):
        gh.fetch(date(2026, 10, 1))


def test_first_pull_goes_back_a_year_then_from_the_last_one(session, fake_gh):
    assert gh.since(session) == date.today() - gh.FIRST_LOOKBACK
    gh.merge(session, [])
    assert (date.today() - gh.since(session)).days == 2


def test_sync_step_reports_counts(fake_gh, tmp_path):
    import threading
    from careeros.storage.db import init_db, make_engine, make_session_factory
    from careeros.web import syncs
    from careeros.web.jobs import Job
    engine = make_engine(tmp_path / "j.db")
    init_db(engine)
    job = Job(syncs.GITHUB_STEPS)
    syncs.run_github(job, make_session_factory(engine), threading.Lock())
    assert job.steps[0]["state"] == "done" and "for jtetzelSFDC" in job.steps[0]["detail"]
    assert job.steps[1]["state"] == "skipped"  # no leveling guide loaded
