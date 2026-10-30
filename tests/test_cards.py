import re

from sqlalchemy import select

from careeros.storage.models import JournalEntry

from test_guide import nb, session  # noqa: F401
from test_web import form

URL = "https://docs.google.com/spreadsheets/d/abc123/edit?usp=drivesdk"


def test_cards_are_one_line_with_labelled_icon_actions_and_named_links(nb):
    dd, c, tok, _ = nb
    form(c, "/journal/add", tok, kind="meeting", text="Release go/no-go", a_kind="link", a_title="Release tracker", a_body=URL)
    form(c, "/journal/add", tok, kind="meeting", text="Bare link meeting", a_kind="link", a_body="https://example.com/x/y")
    with session(dd) as s:
        eid = s.scalar(select(JournalEntry.id).where(JournalEntry.text == "Release go/no-go"))
    html = c.get("/meetings").text
    card = html[html.index("Release go/no-go"):]
    card = card[:card.index('<div class="entry">')] if '<div class="entry">' in card else card
    for action in (f'action="/journal/{eid}/attach"', 'action="/wins/add"', f'action="/journal/{eid}/delete"',
                   f'href="/guide/link?entry={eid}'):
        assert action in card, action
    for label in ("Add notes or a link to this", "Count this as a win", "Link to the leveling guide", "Remove this record"):
        assert f'aria-label="{label}"' in card, label
    assert f'title="{URL}"' in card and "Release tracker</a>" in card
    assert f">{URL}<" not in html  # the address is in the link and its tooltip, never shown as text
    assert "example.com</a>" in html  # a link without a name shows its site
    assert "No meeting notes or transcript attached" not in html


def test_card_actions_still_work(nb):
    dd, c, tok, _ = nb
    form(c, "/journal/add", tok, kind="task", text="Wrote the runbook")
    with session(dd) as s:
        eid = s.scalar(select(JournalEntry.id))
    form(c, f"/journal/{eid}/attach", tok, a_kind="notes", a_title="My notes", a_body="Step one, step two")
    html = c.get("/tasks").text
    assert re.search(r'<summary class="chip att">.*My notes</summary>', html) and "Step one, step two" in html
    form(c, "/wins/add", tok, title="Wrote the runbook", size="medium", entry_id=eid, next="/tasks")
    assert "Wrote the runbook" in c.get("/wins").text
    form(c, f"/journal/{eid}/delete", tok)
    assert "Wrote the runbook" not in c.get("/tasks").text
