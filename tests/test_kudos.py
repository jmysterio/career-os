import json
import re
from datetime import date, datetime

import pytest
from sqlalchemy import select

from careeros.claude_cli import ClaudeError
from careeros.config import DataDir
from careeros.slack import kudos
from careeros.storage.models import JournalAttachment, JournalEntry

ME = "U01ME"


def result(n, who, uid, text, ts="1792789025.320009", day="2026-10-23", bot=False, thread=""):
    frm = f"{who} <{who.split()[0].lower()}@salesforce.com> (ID: {uid}) " if not bot else " (ID: U00)  [BOT]"
    return (f"### Result {n} of 4\nChannel: #release-team (ID: C1)\nFrom: {frm}\nTime: {day} 16:57:05 EDT\n"
            f"Message_ts: {ts}\nPermalink: [link](https://salesforce.enterprise.slack.com/archives/C1/p{ts.replace('.', '')}"
            f"{thread})\nText: \n{text}\n\n---\n\n")


KUDOS = f"Huge shout-out to <@{ME}|Jordan Tetzel> for getting the 3.4 release out the door on a Friday night. Saved us!"
INVITE = f"Thanks for the invite <@{ME}|Jordan Tetzel>, see you there."
SEARCH = json.dumps({"results": "# Search Results for: \n\n## Messages (4 results)\n"
                     + result(1, "Pat Lee", "U02PAT", KUDOS)
                     + result(2, "Sam Roe", "U03SAM", INVITE, ts="1792789999.000001", thread="?thread_ts=1&cid=C1")
                     + result(3, "Jordan Tetzel", ME, "I'll take this one", ts="1792780000.000002")
                     + result(4, "", "U00", f"Thank you, <@{ME}> for your request.", ts="1792770000.000003", bot=True),
                     "pagination_info": "End of results - No more pages available.\\n"})
PAGED = json.loads(SEARCH) | {"pagination_info": "For the next page of results use cursor `Q1VSUkVOVF9QQUdFOjI=`\n"}
PAGED = json.dumps(PAGED)


def fake_filter(prompt, data, timeout=0):
    msgs = json.loads(data)["messages"]
    return json.dumps({"results": [dict(id=m["id"], keep="shout-out" in m["text"],
                                        quote="Huge shout-out to <@U01ME|Jordan Tetzel> for getting the 3.4 release out the door")
                                   for m in msgs]})


@pytest.fixture
def slack(monkeypatch):
    calls = []

    def search(prompt, tools, timeout, max_turns):
        lines = [dict(re.findall(r"(\w+)='([^']*)'", line)) for line in prompt.splitlines() if line[:1].isdigit()]
        calls.append(lines)
        return [("t", args, SEARCH if not calls[1:] or "cursor" in args else PAGED) for args in lines]
    monkeypatch.setattr("careeros.claude_cli.call_tools", search)
    monkeypatch.setattr("careeros.claude_cli.ask", fake_filter)
    return calls


def test_parse_reads_the_real_format():
    msgs, nxt = kudos.parse(SEARCH)
    assert nxt == "" and kudos.parse(PAGED)[1] == "Q1VSUkVOVF9QQUdFOjI=" and [m.who for m in msgs] == ["Pat Lee", "Sam Roe", "Jordan Tetzel", ""]
    assert msgs[0].who_id == "U02PAT" and msgs[0].day == date(2026, 10, 23) and msgs[0].channel == "#release-team"
    assert msgs[1].key == "kudos:https://salesforce.enterprise.slack.com/archives/C1/p1792789999000001"
    assert msgs[3].bot


def test_only_real_kudos_kept_with_an_exact_quote_and_reruns_add_nothing(session, slack):
    msgs, full = kudos.fetch(ME, date(2026, 10, 1), date(2026, 10, 29))
    assert [m.who for m in msgs] == ["Pat Lee", "Sam Roe"] and full == 0  # you and bots dropped
    kept = kudos.choose(kudos.new(session, msgs), ME, "Jordan Tetzel")
    assert kudos.merge(session, kept) == 1
    e = session.scalar(select(JournalEntry).where(JournalEntry.source == "kudos"))
    assert e.kind == "recognition" and e.day == "2026-10-23"
    assert e.text == 'Pat Lee: "Huge shout-out to @Jordan Tetzel for getting the 3.4 release out the door"'
    link = session.scalar(select(JournalAttachment).where(JournalAttachment.entry_id == e.id))
    assert link.title == "Slack message in #release-team" and "/p1792789025320009" in link.body
    again, _ = kudos.fetch(ME, date(2026, 10, 1), date(2026, 10, 29))
    assert [m.who for m in kudos.new(session, again)] == ["Sam Roe"]  # only the one Claude dropped is read again


def test_a_made_up_quote_falls_back_to_the_message_itself(session, monkeypatch):
    msg = kudos.parse(SEARCH)[0][0]
    monkeypatch.setattr("careeros.claude_cli.ask", lambda p, d, timeout=0: json.dumps(
        {"results": [dict(id="m0", keep=True, quote="Jordan is the best release manager ever")]}))
    [(_, quote)] = kudos.choose([msg], ME, "Jordan")
    assert quote == "Huge shout-out to @Jordan Tetzel for getting the 3.4 release out the door on a Friday night. Saved us!"


def test_unreadable_filter_answer_is_an_error(monkeypatch):
    monkeypatch.setattr("careeros.claude_cli.ask", lambda p, d, timeout=0: "sorry")
    with pytest.raises(ClaudeError):
        kudos.choose(kudos.parse(SEARCH)[0][:1], ME, "Jordan")


def test_a_year_is_searched_a_month_at_a_time(slack):
    kudos.fetch(ME, date(2025, 10, 29), date(2026, 10, 29))
    assert len(slack[0]) == 12 and slack[0][0] == {"filters": "after:2025-10-28 before:2025-11-29"}


def test_extra_pages_are_followed(monkeypatch):
    rounds = []

    def search(prompt, tools, timeout, max_turns):
        lines = [dict(re.findall(r"(\w+)='([^']*)'", line)) for line in prompt.splitlines() if line[:1].isdigit()]
        rounds.append(lines)
        return [("t", args, SEARCH if "cursor" in args else PAGED) for args in lines]
    monkeypatch.setattr("careeros.claude_cli.call_tools", search)
    msgs, short = kudos.fetch(ME, date(2026, 10, 1), date(2026, 10, 29))
    assert short == 0 and len(rounds) == 2 and rounds[1] == [dict(filters="after:2026-09-30 before:2026-10-30",
                                                                    cursor="Q1VSUkVOVF9QQUdFOjI=")]


def test_a_search_that_never_comes_back_is_counted(monkeypatch):
    monkeypatch.setattr("careeros.claude_cli.call_tools", lambda *a, **k: [("t", {"filters": "other"}, SEARCH)])
    assert kudos.fetch(ME, date(2026, 10, 1), date(2026, 10, 29)) == ([], 1)


def test_user_id_is_asked_once_and_kept(tmp_path, monkeypatch):
    dd = DataDir(tmp_path)
    asked = []
    monkeypatch.setattr("careeros.claude_cli.call_tool", lambda prompt, tool: asked.append(tool) or
                        "User ID: U01ME\nUsername: jtetzel\nDisplay Name: Jordan Tetzel\n")
    assert kudos.user(dd) == ("U01ME", "Jordan Tetzel")
    assert kudos.user(dd) == ("U01ME", "Jordan Tetzel") and len(asked) == 1
    assert oct((tmp_path / kudos.USER_FILE).stat().st_mode & 0o777) == "0o600"


def test_recognition_counts_like_a_medium_win(session):
    from careeros.guide.service import POINTS, evidence
    from careeros.storage.models import GuideItem, GuideLink
    g = GuideItem(key="E1", kind="experience", grade=6, name="Leads releases", position=1, active=True)
    session.add(g)
    session.flush()
    for kind in ("recognition", "task"):
        e = JournalEntry(day="2026-10-20", kind=kind, text=f"{kind} record", source="", created_at=datetime.now(),
                         status="done")
        session.add(e)
        session.flush()
        session.add(GuideLink(item_id=g.id, entry_id=e.id, created_at=datetime.now()))
    session.commit()
    assert evidence(session)[g.id]["points"] == POINTS["medium"] + POINTS["entry"]


def test_recognition_goes_to_the_promo_writer_as_its_own_quoted_piece(session):
    from careeros.promo.evidence import build
    session.add(JournalEntry(day="2026-10-20", kind="recognition", text='Pat Lee: "Saved us!"', source="kudos",
                             created_at=datetime.now(), external_id="kudos:x"))
    session.commit()
    pieces, slices = build(session, "2026-01-01", "2026-12-31")
    rec = next(p for p in pieces if p["kind"] == "recognition")
    assert rec["text"] == 'Recognition (2026-10-20), quoted exactly: Pat Lee: "Saved us!"'
    assert rec["n"] in slices["behaviors"] and rec["n"] in slices["impact"]
