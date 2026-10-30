import re
from datetime import date

from careeros.web.app import TABS, short_day

from test_guide import nb  # noqa: F401

PAGES = ["/", "/wins", "/promo", "/sheet", "/digest", "/search?q=refresh", "/promo/case", "/impact/deployment", *TABS]


def test_every_page_has_the_app_name_and_no_greeting(nb):
    _, c, *_ = nb
    for path in PAGES:
        html = c.get(path).text
        assert '<a class="brand" href="/">Career Tracker</a>' in html, path
        assert re.search(r"<title>Career Tracker( · [^<]+)?</title>", html), path
        assert not re.search(r"Good (morning|afternoon|evening)|Fresh cup, fresh page", html), path
    assert "<title>Career Tracker · Wins</title>" in c.get("/wins").text


def test_explanations_are_folded(nb):
    _, c, *_ = nb
    folded = {"/promo": "Each key experience from the leveling guide", "/wins": "starting with a verb works well",
              "/promo/case": "Claude writes each section", "/impact/deployment": "counts once per day it was done"}
    for path, text in folded.items():
        html = c.get(path).text
        before, sep, _ = html.partition(text)
        assert sep and before.rfind('<details class="howto">') > before.rfind("</details>"), path


def test_short_day():
    this_year = date.today().year
    assert short_day(f"{this_year}-10-29") == "Oct 29"
    assert short_day(date(this_year - 1, 3, 5)) == f"Mar 5, {this_year - 1}"
