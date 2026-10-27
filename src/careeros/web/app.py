"""Local review UI. Loopback-only, CSRF + Host/Origin checks, autoescaped rendering."""
from __future__ import annotations

import hashlib
import os
import hmac
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import delete, false, func, select
from sqlalchemy.orm import Session

from ..claims import service as svc
from ..config import DataDir
from ..correlate.engine import link, rebuild_episodes, unlink
from ..export.csv_all import notebook_zip
from ..export.promo import promo_markdown
from ..export.wins import wins_markdown
from ..google import summaries
from ..guide import service as gsvc
from ..guide.topics import suggest, topic_of
from ..slack import importer as slack_imp
from ..storage.removal import remove_entry, restore_entry
from ..storage.db import init_db, make_engine, make_session_factory
from ..storage.models import (
    AccomplishmentVersion, Activity, Claim, ClaimSupport, EpisodeMember, GuideItem, GuideLink, JournalAttachment,
    JournalEntry, RemovedEntry, SourceObservation, Win,
)

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'self'; connect-src 'self'; form-action 'self'; "
       "base-uri 'none'; frame-ancestors 'none'")
SHEET_JS = (Path(__file__).parent / "static" / "sheet.js").read_text()
_write_lock = threading.Lock()

# Plain-language versions of the rule codes in claims/rules.py.
FRIENDLY = {
    "uncited": "I can't find where this came from.",
    "contradicted": "Another record disagrees with this.",
    "stale_evidence": "The record behind this has changed since it was written.",
    "stale_link": "This relied on something you've since un-linked.",
    "interpretation_not_user_authored": "Why it mattered should come from you, not from me.",
    "no_completion_evidence": "The records don't say this was finished yet.",
    "metric_not_in_evidence": "That number doesn't appear in the records.",
    "metric_unit_not_in_evidence": "The records don't use that unit with that number.",
    "metric_scope_mismatch": "That number comes from a different release.",
    "metric_is_target": "The records call this a goal, not a result.",
    "team_result_claimed_as_self": "That was a team result, not something recorded as yours.",
    "role_not_supported": "The records don't show you in that role.",
    "first_person_without_role": "The records don't show what your part was.",
    "attribution_without_role": "The records don't show what your part was.",
    "nothing_confirmed": "Nothing is confirmed yet. Mark at least one item as 'Looks right' first.",
}
STATE_LABEL = {"unverified": "needs a look", "rule_checked": "ready for you",
               "human_approved": "confirmed", "rejected": "set aside"}
SECTIONS = [
    dict(layer="observation", title="What happened", hint="what the records show", css="happened"),
    dict(layer="attribution", title="What I did", hint="your part in it", css="did"),
    dict(layer="interpretation", title="Why it mattered", hint="in your words", css="why"),
]


KINDS = [("meeting", "Had a meeting"), ("conversation", "Had a conversation"),
         ("document", "Worked on a document"), ("task", "Finished a task"), ("note", "Something else")]
KIND_LABEL = dict(KINDS)
KIND_PLURAL = {"meeting": ("meeting", "meetings"), "conversation": ("conversation", "conversations"),
               "document": ("document", "documents"), "task": ("task", "tasks"), "note": ("other note", "other notes")}
ATTACH_KINDS = [("notes", "Meeting notes"), ("transcript", "Transcript"), ("link", "Link"),
                ("canvas", "Slack canvas"), ("prompt", "A prompt I wrote"), ("other", "Other text")]
ATTACH_LABEL = dict(ATTACH_KINDS)
MAX_BODY = 200_000
TAGLINES = ["Fresh cup, fresh page.", "Pull up a chair. Nothing here is a test.",
            "Take your time. Jot down what you did."]
TABS = {  # path -> (kind, tab name, heading, what's on it)
    "/meetings": ("meeting", "Meetings", "Meetings", "Every meeting you've logged or pulled from your calendar, newest first. Notes and documents linked to a meeting show underneath it."),
    "/conversations": ("conversation", "Conversations", "Conversations", "Chats and calls you've noted, newest first."),
    "/documents": ("document", "Documents", "Documents", "Documents you've worked on, newest first."),
    "/tasks": ("task", "Tasks", "Tasks", "Your Google Tasks and any you've noted yourself. What's still open is at the top, finished ones are grouped by the day you completed them."),
    "/other": ("note", "Other", "Something else", "Anything that didn't fit the other tabs."),
}
PAGES = {"/", "/releases", "/search", "/wins", "/promo", "/sheet", *TABS}
SOURCE_LABEL = {"calendar": "Calendar", "tasks": "Google Tasks", "slack": "Slack", "": "Typed"}
SHEET_KIND = [("meeting", "Meeting"), ("conversation", "Convo"), ("document", "Doc"), ("task", "Task"), ("note", "Other")]
SHEET_SHOW = {"all": "Everything", "todo": "Not checked yet", "ai": "Changed by Claude", "linked": "Linked to the guide",
              "unlinked": "Not linked", "wins": "Wins", "checked": "Checked", "removed": "Removed"}
SHEET_PAGE = 100
LIST_LIMIT = 300
SIZES = [("small", "Small"), ("medium", "Medium"), ("large", "Large")]
SIZE_LABEL = dict(SIZES)
THEMES = ["Delivery", "Quality & reliability", "Leadership", "Collaboration", "Customer impact",
          "Process improvement", "Mentoring", "Learning & growth"]


def day_label(d: date, today: date) -> str:
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%A, %B ") + str(d.day)


def friendly(violation: str) -> str:
    return FRIENDLY.get(violation.split(":")[0].strip(), violation)


def greeting(now: datetime | None = None) -> str:
    h = (now or datetime.now()).hour
    return "Good morning" if h < 12 else "Good afternoon" if h < 18 else "Good evening"


def claim_text(c: Claim) -> str:
    text = f"{c.subject[:1].upper() + c.subject[1:]} {c.action} {c.object}"
    return text if c.status == "completed" else f"{text} ({c.status.replace('_', ' ')})"


def _hostname(value: str) -> str:
    return urlparse(f"//{value}").hostname or ""


def guide_label(g: GuideItem) -> str:
    return f"{topic_of(g.name).name} (Grade {g.grade})" if g.kind == "experience" else g.name


def guide_chips(s: Session, *, win_ids=(), entry_ids=()) -> dict[tuple[str, int], list[str]]:
    """("win"|"entry", id) -> short labels of the guide items it's linked to."""
    out: dict[tuple[str, int], list[str]] = {}
    q = select(GuideLink, GuideItem).join(GuideItem, GuideItem.id == GuideLink.item_id).where(
        (GuideLink.win_id.in_(list(win_ids))) | (GuideLink.entry_id.in_(list(entry_ids))))
    for l, g in s.execute(q.order_by(GuideItem.position)):
        label = guide_label(g)
        k = ("win", l.win_id) if l.win_id else ("entry", l.entry_id)
        if label not in out.setdefault(k, []):
            out[k].append(label)
    return out


def create_app(dd: DataDir) -> FastAPI:
    dd.require_known()
    personal = dd.is_personal
    os.umask(0o077)
    engine = make_engine(dd.db)
    init_db(engine)
    Session_ = make_session_factory(engine)
    csrf_token = hmac.new(dd.secret(), b"csrf", hashlib.sha256).hexdigest()
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True)
    env.globals.update(tabs=TABS, sizes=SIZES, themes=THEMES)
    app = FastAPI(debug=False, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if _hostname(request.headers.get("host", "")) not in ALLOWED_HOSTS:
            return JSONResponse({"error": "bad host"}, status_code=400)
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin and _hostname(urlparse(origin).netloc) not in ALLOWED_HOSTS:
                return JSONResponse({"error": "bad origin"}, status_code=403)
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "same-origin"
        return resp

    def db():
        with Session_() as s:
            yield s

    def check_csrf(csrf: str = Form("")) -> None:
        if not hmac.compare_digest(csrf, csrf_token):
            raise _Forbidden()

    class _Forbidden(Exception):
        pass

    @app.exception_handler(_Forbidden)
    async def _forbidden(_r, _e):
        return JSONResponse({"error": "bad csrf token"}, status_code=403)

    def back(msg: str | None = None, to: str = "/releases") -> RedirectResponse:
        return RedirectResponse(to + (f"?msg={quote(msg[:300])}" if msg else ""), status_code=303)

    def guarded(fn):
        try:
            with _write_lock:
                fn()
        except svc.ClaimBlocked as exc:
            return back("Not saved yet: " + " ".join(friendly(v) for v in exc.violations))
        return back()

    def theme_of(request: Request) -> str:
        return "light" if request.cookies.get("theme") == "light" else "dark"

    def entry_dicts(s: Session, rows: list) -> list[dict]:
        atts: dict[int, list] = {}
        for a in s.scalars(select(JournalAttachment).where(
                JournalAttachment.entry_id.in_([e.id for e in rows])).order_by(JournalAttachment.id)):
            link = a.kind == "link" and urlparse(a.body.strip()).scheme in ("http", "https")
            atts.setdefault(a.entry_id, []).append(dict(
                id=a.id, label=ATTACH_LABEL.get(a.kind, "Text"), title=a.title, body=a.body,
                url=a.body.strip() if link else None,
                ai=a.kind == "notes" and a.title == summaries.AI_TITLE,
                slack_ai=a.kind == "notes" and a.title.startswith(slack_imp.NOTES_TITLE)))
        guided = gsvc.has_guide(s)
        chips = guide_chips(s, entry_ids=[e.id for e in rows]) if guided else {}
        has_win = set(s.scalars(select(Win.entry_id).where(Win.entry_id.in_([e.id for e in rows]))))
        out = []
        for e in rows:
            linked = chips.get(("entry", e.id), [])
            hint = [t.name for t in suggest(e.text)[0]] if guided and not linked and not e.ai_read else []
            mine = atts.get(e.id, [])
            impact = next((slack_imp.impact_of(a["body"]) for a in mine if a["slack_ai"]), "")
            has_notes = any(summaries.doc_ids([a["url"]]) for a in mine if a["url"])
            from_cal = e.source == "calendar"
            out.append(dict(id=e.id, day=e.day, text=e.text, kind_label=KIND_LABEL.get(e.kind, "Note"),
                            from_calendar=from_cal, status=e.status, attachments=mine, guided=guided,
                            guide=linked, hint=hint, from_slack=e.source == slack_imp.SOURCE, win_impact=impact,
                            suggested_win=bool(impact) and e.id not in has_win,
                            notes_state=("" if not from_cal else "summarized" if any(a["ai"] for a in mine)
                                         else "pending" if has_notes else "none")))
        return out

    @app.get("/", response_class=HTMLResponse)
    def today_page(request: Request, msg: str | None = None, s: Session = Depends(db)):
        today = date.today()
        week = [today - timedelta(days=i) for i in range(7)]
        rows = list(s.scalars(select(JournalEntry).where(
            JournalEntry.day.in_([d.isoformat() for d in week]), JournalEntry.status != "open")
            .order_by(JournalEntry.id.desc())))
        ents = entry_dicts(s, rows)
        days = []
        for d in week:
            es = [e for e in ents if e["day"] == d.isoformat()]
            if es or d == today:
                days.append(dict(label=day_label(d, today), entries=es, is_today=d == today))
        parts = []
        for k, (one, many) in KIND_PLURAL.items():
            n = sum(1 for e in rows if e.kind == k)
            if n:
                parts.append(f"{n} {one if n == 1 else many}")
        tally = ("In the last 7 days you noted " + ", ".join(parts) + ".") if parts else ""
        html = env.get_template("today.html").render(
            days=days, tally=tally, kinds=KINDS, attach_kinds=ATTACH_KINDS, today=today.isoformat(),
            tagline=TAGLINES[today.toordinal() % len(TAGLINES)], csrf=csrf_token, msg=msg,
            sync_warning=dd.sync_warning(), theme=theme_of(request), greeting=greeting(), page="/", personal=personal, q="",
            slack_canvas=slack_imp.load_canvas_id(dd) if personal else None)
        return HTMLResponse(html)

    def tab_page(path: str):
        kind, _name, title, intro = TABS[path]

        def view(request: Request, msg: str | None = None, s: Session = Depends(db)):
            q = select(JournalEntry).where(JournalEntry.kind == kind)
            count = s.scalar(select(func.count()).select_from(q.subquery()))
            open_rows = list(s.scalars(q.where(JournalEntry.status == "open").order_by(JournalEntry.day.desc(), JournalEntry.id)))
            rows = list(s.scalars(q.where(JournalEntry.status != "open")
                                  .order_by(JournalEntry.day.desc(), JournalEntry.id.desc()).limit(LIST_LIMIT)))
            today = date.today()
            ents = entry_dicts(s, open_rows + rows)
            days: list[dict] = []
            for e in ents[len(open_rows):]:
                if not days or days[-1]["day"] != e["day"]:
                    days.append(dict(day=e["day"], label=day_label(date.fromisoformat(e["day"]), today), entries=[]))
                days[-1]["entries"].append(e)
            html = env.get_template("list.html").render(
                title=title, intro=intro, count=count, shown=len(rows), days=days, open_entries=ents[:len(open_rows)],
                kinds=KINDS, attach_kinds=ATTACH_KINDS, csrf=csrf_token, msg=msg, sync_warning=dd.sync_warning(),
                theme=theme_of(request), greeting=greeting(), tagline=TAGLINES[0], page=path, personal=personal, q="")
            return HTMLResponse(html)
        return view

    for _path in TABS:
        app.add_api_route(_path, tab_page(_path), methods=["GET"], response_class=HTMLResponse)

    @app.get("/search", response_class=HTMLResponse)
    def search(request: Request, q: str = "", s: Session = Depends(db)):
        q = q.strip()[:200]
        hits = []
        if q:
            terms = [w for w in q.split() if w][:6]
            by_entry: dict[int, dict] = {}
            for e in s.scalars(select(JournalEntry).order_by(JournalEntry.day.desc(), JournalEntry.id.desc())):
                by_entry[e.id] = dict(e=e, atts=[])
            for a in s.scalars(select(JournalAttachment)):
                if a.entry_id in by_entry:
                    by_entry[a.entry_id]["atts"].append(a)
            for v in by_entry.values():
                e = v["e"]
                texts = [("", e.text)] + [(f"{ATTACH_LABEL.get(a.kind, 'Text')}: {a.title}".strip(": "), a.body)
                                          for a in v["atts"]] + [("", a.title) for a in v["atts"] if a.title]
                blob = "\n".join(x for _, x in texts).lower()
                if not all(w.lower() in blob for w in terms):
                    continue
                snippets = []
                for label, body in texts[1:] if len(texts) > 1 else []:
                    low = body.lower()
                    i = low.find(terms[0].lower())
                    if i < 0:
                        continue
                    lo, hi = max(0, i - 80), min(len(body), i + len(terms[0]) + 120)
                    snippets.append(dict(label=label, before=("…" if lo else "") + body[lo:i].replace("\n", " "),
                                         hit=body[i:i + len(terms[0])],
                                         after=body[i + len(terms[0]):hi].replace("\n", " ") + ("…" if hi < len(body) else "")))
                hits.append(dict(day=e.day, kind_label=KIND_LABEL.get(e.kind, "Note"), text=e.text,
                                 snippets=snippets[:2]))
                if len(hits) >= 50:
                    break
            for w in s.scalars(select(Win).order_by(Win.day.desc(), Win.id.desc())):
                if all(t.lower() in f"{w.title}\n{w.impact}\n{w.theme}".lower() for t in terms):
                    hits.append(dict(day=w.day, kind_label="Win", text=w.title, snippets=[]))
            hits.sort(key=lambda h: h["day"], reverse=True)
        html = env.get_template("search.html").render(
            q=q, hits=hits, csrf=csrf_token, msg=None, sync_warning=dd.sync_warning(), theme=theme_of(request),
            greeting=greeting(), tagline=TAGLINES[0], page="/search", personal=personal)
        return HTMLResponse(html)

    @app.post("/journal/add", dependencies=[Depends(check_csrf)])
    def journal_add(kind: str = Form(...), text: str = Form(..., max_length=500),
                    day: str = Form(""), a_kind: str = Form("notes"), a_title: str = Form("", max_length=200),
                    a_body: str = Form("", max_length=MAX_BODY), s: Session = Depends(db)):
        text = text.strip()
        try:
            d = date.fromisoformat(day) if day else date.today()
        except ValueError:
            d = date.today()
        d = min(d, date.today())
        if not text:
            return back("Write a few words first.", "/")
        with _write_lock:
            entry = JournalEntry(day=d.isoformat(), kind=kind if kind in KIND_LABEL else "note",
                                 text=text, created_at=datetime.now())
            s.add(entry)
            s.flush()
            if a_body.strip():
                s.add(JournalAttachment(entry_id=entry.id, kind=a_kind if a_kind in ATTACH_LABEL else "other",
                                        title=a_title.strip(), body=a_body.strip(), created_at=datetime.now()))
            s.commit()
        return back(to="/")

    @app.post("/calendar/sync", dependencies=[Depends(check_csrf)])
    def calendar_sync(s: Session = Depends(db)):
        """Ask Claude Code to fetch yesterday's and today's meetings through the Google Workspace connector."""
        if not personal:
            return back("Calendar sync only works with your personal notebook.", "/")
        from ..google import calendar as gcal, connector
        last = date.today()
        first = last - timedelta(days=1)
        try:
            items = connector.fetch(first, last)
            with _write_lock:
                r = gcal.import_events(s, items, first, last)
                n = summaries.summarize_pending(s, first, last)
        except gcal.CalendarError as exc:
            return back(str(exc), "/")
        msg = (f"Calendar synced: {r['added']} new, {r['updated']} changed, {r['removed']} removed. "
               f"{n['summarized']} meeting summaries written.")
        if n["failed"]:
            msg += f" {n['failed']} couldn't be summarized; press Sync calendar to try again."
        return back(msg, "/")

    @app.post("/slack/sync", dependencies=[Depends(check_csrf)])
    def slack_sync(s: Session = Depends(db)):
        """Ask Claude Code to read the connected Slack tracker canvas, then sort and import its new items."""
        if not personal:
            return back("Slack sync only works with your personal notebook.", "/")
        from ..claude_cli import ClaudeError
        from ..slack.classify import classify
        from ..slack.connector import fetch_canvas
        from ..slack.parse import CanvasFormatError, parse_canvas
        cid = slack_imp.load_canvas_id(dd)
        if not cid:
            return back("No Slack canvas connected yet. In Terminal run: uv run careeros slack connect <canvas link>", "/")
        try:
            items = parse_canvas(fetch_canvas(cid))
            with _write_lock:
                r = slack_imp.import_items(s, items, classify)
        except (ClaudeError, CanvasFormatError) as exc:
            return back(f"Slack sync didn't finish: {exc}", "/")
        return back(f"Slack synced: {r['added']} new ({r['meeting']} meetings, {r['conversation']} conversations, "
                    f"{r['document']} documents, {r['task']} tasks, {r['note']} other), {r['skipped']} already here.", "/")

    @app.post("/journal/{eid}/attach", dependencies=[Depends(check_csrf)])
    def journal_attach(eid: int, a_kind: str = Form("notes"), a_title: str = Form("", max_length=200),
                       a_body: str = Form(..., max_length=MAX_BODY), s: Session = Depends(db)):
        with _write_lock:
            if s.get(JournalEntry, eid) and a_body.strip():
                s.add(JournalAttachment(entry_id=eid, kind=a_kind if a_kind in ATTACH_LABEL else "other",
                                        title=a_title.strip(), body=a_body.strip(), created_at=datetime.now()))
                s.commit()
        return back(to="/")

    @app.post("/journal/attachment/{aid}/delete", dependencies=[Depends(check_csrf)])
    def journal_attachment_delete(aid: int, s: Session = Depends(db)):
        with _write_lock:
            a = s.get(JournalAttachment, aid)
            if a:
                s.delete(a)
                s.commit()
        return back(to="/")

    @app.post("/journal/{eid}/delete", dependencies=[Depends(check_csrf)])
    def journal_delete(eid: int, s: Session = Depends(db)):
        with _write_lock:
            remove_entry(s, eid)
        return back(to="/")

    def win_years(s: Session) -> list[int]:
        return sorted({int(d[:4]) for d in s.scalars(select(Win.day))} | {date.today().year}, reverse=True)

    def year_wins(s: Session, year: int) -> list[Win]:
        return list(s.scalars(select(Win).where(Win.day >= f"{year}-01-01", Win.day <= f"{year}-12-31")
                              .order_by(Win.day.desc(), Win.id.desc())))

    @app.get("/wins", response_class=HTMLResponse)
    def wins_page(request: Request, year: int | None = None, size: str = "", msg: str | None = None,
                  s: Session = Depends(db)):
        year = year or date.today().year
        rows = year_wins(s, year)
        counts = {k: sum(1 for w in rows if w.size == k) for k in SIZE_LABEL}
        shown = [w for w in rows if not size or w.size == size]
        entries = {e.id: e.text for e in s.scalars(select(JournalEntry).where(
            JournalEntry.id.in_([w.entry_id for w in shown if w.entry_id])))}
        chips = guide_chips(s, win_ids=[w.id for w in shown])
        months: list[dict] = []
        for w in shown:
            label = date.fromisoformat(w.day).strftime("%B")
            if not months or months[-1]["label"] != label:
                months.append(dict(label=label, wins=[]))
            months[-1]["wins"].append(dict(w=w, size_label=SIZE_LABEL.get(w.size, w.size),
                                           from_entry=entries.get(w.entry_id), guide=chips.get(("win", w.id), [])))
        html = env.get_template("wins.html").render(
            year=year, years=win_years(s), size=size, months=months, total=len(rows), counts=counts,
            missing=sum(1 for w in rows if not w.impact), today=date.today().isoformat(), guided=gsvc.has_guide(s),
            csrf=csrf_token, msg=msg, sync_warning=dd.sync_warning(), theme=theme_of(request), greeting=greeting(),
            tagline=TAGLINES[0], page="/wins", personal=personal, q="")
        return HTMLResponse(html)

    def win_fields(title: str, impact: str, size: str, theme: str, day: str) -> dict:
        try:
            d = min(date.fromisoformat(day), date.today()) if day else date.today()
        except ValueError:
            d = date.today()
        return dict(title=title.strip(), impact=impact.strip(), size=size if size in SIZE_LABEL else "small",
                    theme=theme if theme in THEMES else "", day=d.isoformat())

    @app.post("/wins/add", dependencies=[Depends(check_csrf)])
    def win_add(title: str = Form(..., max_length=500), impact: str = Form("", max_length=2000),
                size: str = Form("small"), theme: str = Form(""), day: str = Form(""),
                entry_id: int | None = Form(None), next: str = Form("/wins"), s: Session = Depends(db)):
        to = next if next in PAGES else "/wins"
        f = win_fields(title, impact, size, theme, day)
        if not f["title"]:
            return back("Write what you did first.", to)
        with _write_lock:
            entry = s.get(JournalEntry, entry_id) if entry_id else None
            w = Win(**f, entry_id=entry.id if entry else None, created_at=datetime.now())
            s.add(w)
            s.commit()
        if gsvc.has_guide(s):
            return RedirectResponse(f"/guide/link?win={w.id}&next={quote(to)}", status_code=303)
        return back(f"Saved to your wins: {f['title']}", to)

    @app.post("/wins/{wid}/edit", dependencies=[Depends(check_csrf)])
    def win_edit(wid: int, title: str = Form(..., max_length=500), impact: str = Form("", max_length=2000),
                 size: str = Form("small"), theme: str = Form(""), day: str = Form(""), s: Session = Depends(db)):
        f = win_fields(title, impact, size, theme, day)
        with _write_lock:
            w = s.get(Win, wid)
            if w and f["title"]:
                for k, v in f.items():
                    setattr(w, k, v)
                w.by_ai = False
                s.commit()
        return back(to=f"/wins?year={f['day'][:4]}")

    @app.post("/wins/{wid}/delete", dependencies=[Depends(check_csrf)])
    def win_delete(wid: int, s: Session = Depends(db)):
        with _write_lock:
            w = s.get(Win, wid)
            if w:
                gsvc.drop_links(s, win_id=wid)
                s.delete(w)
                s.commit()
        return back(to="/wins")

    def link_target(s: Session, win: int | None, entry: int | None):
        if win is not None:
            w = s.get(Win, win)
            return (w, dict(win_id=w.id), w.title + "\n" + w.impact) if w else None
        e = s.get(JournalEntry, entry) if entry is not None else None
        return (e, dict(entry_id=e.id), e.text) if e else None

    @app.get("/guide/link", response_class=HTMLResponse)
    def guide_link_page(request: Request, win: int | None = None, entry: int | None = None, next: str = "/wins",
                        s: Session = Depends(db)):
        t = link_target(s, win, entry)
        if t is None or not gsvc.has_guide(s):
            return back("That item is gone, or the leveling guide isn't loaded yet.", "/promo")
        obj, ref, text = t
        linked = gsvc.linked_ids(s, **ref)
        if not linked and isinstance(obj, Win) and obj.entry_id:
            linked = gsvc.linked_ids(s, entry_id=obj.entry_id)
        suggested = set() if linked else gsvc.suggested_ids(s, text)
        pm = gsvc.promo_map(s)
        html = env.get_template("guide_link.html").render(
            obj=obj, is_win=isinstance(obj, Win), ref=ref, checked=linked or suggested, suggested=bool(suggested),
            pm=pm, next=next if next in PAGES else "/wins", csrf=csrf_token, msg=None, sync_warning=dd.sync_warning(),
            theme=theme_of(request), greeting=greeting(), tagline=TAGLINES[0], page="/promo", personal=personal, q="")
        return HTMLResponse(html)

    @app.post("/guide/link", dependencies=[Depends(check_csrf)])
    def guide_link_save(win: int | None = Form(None), entry: int | None = Form(None), item: list[int] = Form([]),
                        next: str = Form("/wins"), s: Session = Depends(db)):
        to = next if next in PAGES else "/wins"
        with _write_lock:
            t = link_target(s, win, entry)
            if t is None:
                return back("That item is gone.", to)
            gsvc.set_links(s, set(item), **t[1])
        n = len(item)
        return back(f"Linked to {n} leveling guide item{'' if n == 1 else 's'}." if n else "Saved, with no guide items.", to)

    def sheet_filters(show: str = "todo", source: str = "any", kind: str = "any", page: int = 1) -> dict:
        return dict(show=show if show in SHEET_SHOW else "todo",
                    source=source if source in SOURCE_LABEL or source == "any" else "any",
                    kind=kind if kind in KIND_LABEL or kind == "any" else "any", page=max(1, min(page, 1000)))

    def parse_ret(ret: str) -> dict:
        q = {k: v[0] for k, v in parse_qs(ret).items() if k in ("show", "source", "kind", "page")}
        try:
            return sheet_filters(**{**q, "page": int(q.get("page", 1))})
        except ValueError:
            return sheet_filters()

    def sheet_query(f: dict):
        linked = select(GuideLink.entry_id).where(GuideLink.entry_id.is_not(None))
        q = select(JournalEntry)
        if f["source"] != "any":
            q = q.where(JournalEntry.source == f["source"])
        if f["kind"] != "any":
            q = q.where(JournalEntry.kind == f["kind"])
        return {"todo": q.where(JournalEntry.reviewed.is_(False)), "checked": q.where(JournalEntry.reviewed.is_(True)),
                "ai": q.where(JournalEntry.reviewed.is_(False), (JournalEntry.kind_was != "") | JournalEntry.id.in_(
                    select(GuideLink.entry_id).where(GuideLink.by_ai)) | JournalEntry.id.in_(
                    select(Win.entry_id).where(Win.by_ai))),
                "linked": q.where(JournalEntry.id.in_(linked)), "unlinked": q.where(JournalEntry.id.not_in(linked)),
                "wins": q.where(JournalEntry.id.in_(select(Win.entry_id).where(Win.entry_id.is_not(None)))),
                "removed": q.where(false()), "all": q}[f["show"]]

    def sheet_ctx(s: Session, f: dict) -> dict:
        return dict(ret=urlencode(f), csrf=csrf_token, kind_opts=SHEET_KIND, size_label=SIZE_LABEL,
                    guided=gsvc.has_guide(s))

    def sheet_back(request: Request, s: Session, ret: str, eid: int | None = None, msg: str | None = None,
                   after: int | None = None) -> Response:
        """A full redirect for plain form posts; for the Sheet's script, just the redrawn row, or "gone"."""
        f = parse_ret(ret)
        if request.headers.get("x-sheet") == "1" and eid:
            s.expire_all()
            e = s.scalar(sheet_query(f).where(JournalEntry.id == eid))
            if e is None:
                return Response("", headers={"X-Row": "gone"})
            html = env.get_template("_sheet_row.html").render(r=sheet_rows(s, [e])[0], nxt="", **sheet_ctx(s, f))
            return HTMLResponse(html)
        if msg:
            f["msg"] = msg[:300]
        anchor = after or eid
        return RedirectResponse(f"/sheet?{urlencode(f)}" + (f"#r{anchor}" if anchor else ""), status_code=303)

    @app.get("/static/sheet.js")
    def sheet_js():
        return Response(SHEET_JS, media_type="text/javascript; charset=utf-8")

    @app.get("/sheet", response_class=HTMLResponse)
    def sheet_page(request: Request, show: str = "todo", source: str = "any", kind: str = "any", page: int = 1,
                   msg: str | None = None, s: Session = Depends(db)):
        f = sheet_filters(show, source, kind, page)
        if f["show"] == "removed":
            q = select(RemovedEntry)
            if f["source"] != "any":
                q = q.where(RemovedEntry.source == f["source"])
            if f["kind"] != "any":
                q = q.where(RemovedEntry.kind == f["kind"])
            order = (RemovedEntry.removed_at.desc(), RemovedEntry.id.desc())
        else:
            q, order = sheet_query(f), (JournalEntry.day.desc(), JournalEntry.id.desc())
        total = s.scalar(select(func.count()).select_from(q.subquery())) or 0
        pages = max(1, -(-total // SHEET_PAGE))
        f["page"] = min(f["page"], pages)
        rows = list(s.scalars(q.order_by(*order).offset((f["page"] - 1) * SHEET_PAGE).limit(SHEET_PAGE)))
        out = ([dict(id=r.id, day=r.day, source=SOURCE_LABEL.get(r.source, r.source), text=r.text,
                     kind=dict(SHEET_KIND).get(r.kind, "Other")) for r in rows]
               if f["show"] == "removed" else sheet_rows(s, rows))
        counts = dict(
            total=s.scalar(select(func.count()).select_from(JournalEntry)) or 0,
            read=s.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.ai_read)) or 0,
            checked=s.scalar(select(func.count()).select_from(JournalEntry).where(JournalEntry.reviewed)) or 0,
            unread=s.scalar(select(func.count()).select_from(JournalEntry).where(
                JournalEntry.ai_read.is_(False), JournalEntry.reviewed.is_(False))) or 0,
            **gsvc.ai_counts(s))
        html = env.get_template("sheet.html").render(
            rows=out, f=f, total=total, pages=pages, counts=counts, show_opts=SHEET_SHOW, source_opts=SOURCE_LABEL,
            msg=msg, sync_warning=dd.sync_warning(), theme=theme_of(request), greeting=greeting(),
            tagline=TAGLINES[0], page="/sheet", personal=personal, q="", wide=True, **sheet_ctx(s, f))
        return HTMLResponse(html)

    def sheet_rows(s: Session, rows: list) -> list[dict]:
        ids = [e.id for e in rows]
        links: dict[int, list] = {}
        for l, g in s.execute(select(GuideLink, GuideItem).join(GuideItem, GuideItem.id == GuideLink.item_id)
                              .where(GuideLink.entry_id.in_(ids)).order_by(GuideItem.position)):
            links.setdefault(l.entry_id, []).append(dict(id=l.id, label=guide_label(g), ai=l.by_ai, name=g.name))
        wins = {w.entry_id: w for w in s.scalars(select(Win).where(Win.entry_id.in_(ids)).order_by(Win.id))}
        notes: dict[int, str] = {}
        for a in s.scalars(select(JournalAttachment).where(JournalAttachment.entry_id.in_(ids),
                                                           JournalAttachment.kind == "notes")):
            notes.setdefault(a.entry_id, a.body[:1200])
        return [dict(id=e.id, day=e.day, source=SOURCE_LABEL.get(e.source, e.source), kind=e.kind,
                     kind_was=dict(SHEET_KIND).get(e.kind_was, ""),
                     text=e.text, reviewed=e.reviewed, ai_read=e.ai_read, links=links.get(e.id, []),
                     win=wins.get(e.id), notes=notes.get(e.id, "")) for e in rows]

    @app.post("/sheet/{eid}/kind", dependencies=[Depends(check_csrf)])
    def sheet_kind(request: Request, eid: int, kind: str = Form(...), ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            e = s.get(JournalEntry, eid)
            if e and kind in KIND_LABEL:
                if e.kind != kind:
                    e.status = "done" if kind == "task" else ""
                e.kind, e.kind_was = kind, ""
                s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/{eid}/win", dependencies=[Depends(check_csrf)])
    def sheet_win(request: Request, eid: int, size: str = Form("small"), ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            e = s.get(JournalEntry, eid)
            if e is None or size not in SIZE_LABEL:
                return sheet_back(request, s, ret, eid)
            w = s.scalar(select(Win).where(Win.entry_id == eid).order_by(Win.id).limit(1))
            if w:
                w.size, w.by_ai = size, False
            else:
                impact = next((slack_imp.impact_of(a.body) for a in s.scalars(select(JournalAttachment).where(
                    JournalAttachment.entry_id == eid, JournalAttachment.title.startswith(slack_imp.NOTES_TITLE)))), "")
                w = Win(day=e.day, title=e.text[:500], impact=impact, size=size, entry_id=eid, created_at=datetime.now())
                s.add(w)
                s.flush()
                for l in s.scalars(select(GuideLink).where(GuideLink.entry_id == eid)):
                    s.add(GuideLink(item_id=l.item_id, win_id=w.id, created_at=datetime.now(), by_ai=l.by_ai))
            s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/{eid}/unwin", dependencies=[Depends(check_csrf)])
    def sheet_unwin(request: Request, eid: int, ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            for w in s.scalars(select(Win).where(Win.entry_id == eid)):
                gsvc.drop_links(s, win_id=w.id)
                s.delete(w)
            s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/link/{lid}/delete", dependencies=[Depends(check_csrf)])
    def sheet_unlink(request: Request, lid: int, ret: str = Form(""), s: Session = Depends(db)):
        eid = None
        with _write_lock:
            l = s.get(GuideLink, lid)
            if l and l.entry_id:
                eid = l.entry_id
                win_ids = select(Win.id).where(Win.entry_id == eid)
                s.execute(delete(GuideLink).where(GuideLink.item_id == l.item_id, GuideLink.win_id.in_(win_ids)))
                s.delete(l)
                s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/{eid}/ok", dependencies=[Depends(check_csrf)])
    def sheet_ok(request: Request, eid: int, ret: str = Form(""), after: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            gsvc.confirm(s, eid)
        return sheet_back(request, s, ret, eid, after=int(after) if after.isdigit() else None)

    @app.post("/sheet/{eid}/remove", dependencies=[Depends(check_csrf)])
    def sheet_remove(request: Request, eid: int, ret: str = Form(""), after: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            remove_entry(s, eid)
        return sheet_back(request, s, ret, eid, after=int(after) if after.isdigit() else None)

    @app.post("/sheet/removed/{rid}/restore", dependencies=[Depends(check_csrf)])
    def sheet_restore(request: Request, rid: int, ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            restore_entry(s, rid)
        if request.headers.get("x-sheet") == "1":
            return Response("", headers={"X-Row": "gone"})
        return sheet_back(request, s, ret)

    @app.post("/sheet/{eid}/undo", dependencies=[Depends(check_csrf)])
    def sheet_undo(request: Request, eid: int, ret: str = Form(""), s: Session = Depends(db)):
        with _write_lock:
            e = s.get(JournalEntry, eid)
            if e:
                e.reviewed = False
                s.commit()
        return sheet_back(request, s, ret, eid)

    @app.post("/sheet/ai", dependencies=[Depends(check_csrf)])
    def sheet_ai(request: Request, ret: str = Form(""), s: Session = Depends(db)):
        """Have Claude read every record it hasn't read yet against the guide."""
        if not personal:
            return sheet_back(request, s, ret, msg="The Claude review only works with your personal notebook.")
        from ..claude_cli import ClaudeError
        from ..guide.ai_review import review
        try:
            with _write_lock:
                r = review(s)
        except ClaudeError as exc:
            return sheet_back(request, s, ret, msg=f"Claude review didn't finish: {exc}")
        return sheet_back(request, s, ret, msg=f"Claude read {r['read']} records: {r['links']} guide links, {r['wins']} drafted "
                                   f"wins, {r['kinds']} type changes, all marked AI."
                                   + (f" {r['failed']} couldn't be read; press the button again to retry them."
                                      if r["failed"] else ""))

    @app.get("/promo", response_class=HTMLResponse)
    def promo_page(request: Request, msg: str | None = None, s: Session = Depends(db)):
        guided = gsvc.has_guide(s)
        hints = 0
        if guided:
            linked = set(s.scalars(select(GuideLink.entry_id).where(GuideLink.entry_id.is_not(None))))
            hints = sum(1 for eid, text in s.execute(select(JournalEntry.id, JournalEntry.text).where(
                JournalEntry.ai_read.is_(False))) if eid not in linked and suggest(text)[0])
        html = env.get_template("promo.html").render(
            pm=gsvc.promo_map(s) if guided else None, hints=hints, ai=gsvc.ai_counts(s), csrf=csrf_token, msg=msg,
            sync_warning=dd.sync_warning(), theme=theme_of(request), greeting=greeting(), tagline=TAGLINES[0],
            page="/promo", personal=personal, q="")
        return HTMLResponse(html)

    @app.get("/promo/export")
    def promo_export(s: Session = Depends(db)):
        if not gsvc.has_guide(s):
            return back("Load the leveling guide first.", "/promo")
        name = f"promo-case-{date.today().isoformat()}.md"
        return Response(promo_markdown(gsvc.promo_map(s)), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/wins/export")
    def win_export(year: int | None = None, s: Session = Depends(db)):
        year = year or date.today().year
        return Response(wins_markdown(year_wins(s, year), year), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="my-wins-{year}.md"'})

    @app.get("/export/everything")
    def export_everything(s: Session = Depends(db)):
        name = f"career-notebook-{date.today().isoformat()}.zip"
        return Response(notebook_zip(s), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.get("/releases", response_class=HTMLResponse)
    def index(request: Request, msg: str | None = None, s: Session = Depends(db)):
        if personal:
            return HTMLResponse("Not found", status_code=404)
        stale = svc.stale_versions(s)
        episodes = []
        for a in s.scalars(select(Activity).where(Activity.type == "release_row", Activity.state == "present")):
            members = [dict(status=m.status, origin=m.origin, confidence=m.confidence, reason=m.reason,
                            activity_id=m.activity_id, title=s.get(Activity, m.activity_id).title)
                       for m in s.scalars(select(EpisodeMember).where(EpisodeMember.anchor_activity_id == a.id))]
            claims = []
            for c in s.scalars(select(Claim).where(Claim.anchor_activity_id == a.id)):
                ev = []
                for sup in s.scalars(select(ClaimSupport).where(ClaimSupport.claim_id == c.id)):
                    obs = s.get(SourceObservation, sup.observation_id)
                    act = s.scalar(select(Activity).where(Activity.source_record_id == obs.source_record_id))
                    ev.append(dict(ref=svc.provenance_ref(sup), polarity=sup.polarity,
                                   excerpt=svc.excerpt_text(s, sup), url=act.source_url if act else None))
                claims.append(dict(id=c.id, layer=c.layer, text=claim_text(c), object=c.object,
                                   verification_status=c.verification_status, authored_by=c.authored_by,
                                   state_label=STATE_LABEL[c.verification_status], evidence=ev,
                                   violations=[friendly(v) for v in svc.violations(s, c)]
                                   if c.verification_status != "rejected" else []))
            versions = list(s.scalars(select(AccomplishmentVersion).where(
                AccomplishmentVersion.anchor_activity_id == a.id)))
            episodes.append(dict(id=a.id, title=a.title.split(": ", 1)[-1], members=members, claims=claims, versions=versions,
                                 unknowns=svc.unknowns_for(s, a.id),
                                 stale=any(v.id in stale for v in versions)))
        html = env.get_template("review.html").render(
            episodes=episodes, csrf=csrf_token, msg=msg, sync_warning=dd.sync_warning(),
            theme=theme_of(request), greeting=greeting(), sections=SECTIONS, page="/releases", tagline=TAGLINES[0], personal=personal, q="")
        return HTMLResponse(html)

    @app.post("/theme", dependencies=[Depends(check_csrf)])
    def set_theme(theme: str = Form(...), next: str = Form("/")):
        resp = back(to=next if next in PAGES else "/")
        resp.set_cookie("theme", "light" if theme == "light" else "dark", max_age=31_536_000,
                        httponly=True, samesite="strict")
        return resp

    @app.post("/claims/{cid}/approve", dependencies=[Depends(check_csrf)])
    def approve(cid: int, s: Session = Depends(db)):
        return guarded(lambda: svc.approve(s, cid))

    @app.post("/claims/{cid}/reject", dependencies=[Depends(check_csrf)])
    def reject(cid: int, s: Session = Depends(db)):
        return guarded(lambda: svc.reject(s, cid))

    @app.post("/claims/{cid}/edit", dependencies=[Depends(check_csrf)])
    def edit(cid: int, object: str = Form(..., max_length=500), s: Session = Depends(db)):
        return guarded(lambda: svc.edit_claim(s, cid, object=object))

    @app.post("/episodes/{aid}/link", dependencies=[Depends(check_csrf)])
    def do_link(aid: int, activity_id: int = Form(...), s: Session = Depends(db)):
        return guarded(lambda: (link(s, activity_id, aid), svc.draft_episode(s, aid)))

    @app.post("/episodes/{aid}/unlink", dependencies=[Depends(check_csrf)])
    def do_unlink(aid: int, activity_id: int = Form(...), s: Session = Depends(db)):
        return guarded(lambda: (unlink(s, activity_id, aid), svc.draft_episode(s, aid)))

    @app.post("/episodes/{aid}/impact", dependencies=[Depends(check_csrf)])
    def impact(aid: int, text: str = Form(..., min_length=1, max_length=1000), s: Session = Depends(db)):
        return guarded(lambda: svc.add_impact_claim(s, aid, text))

    @app.post("/episodes/{aid}/redraft", dependencies=[Depends(check_csrf)])
    def redraft(aid: int, s: Session = Depends(db)):
        return guarded(lambda: svc.draft_episode(s, aid))

    @app.post("/episodes/{aid}/publish", dependencies=[Depends(check_csrf)])
    def publish(aid: int, s: Session = Depends(db)):
        def run():
            ids = [c.id for c in s.scalars(select(Claim).where(
                Claim.anchor_activity_id == aid, Claim.verification_status == "human_approved"))]
            if not ids:
                raise svc.ClaimBlocked(["nothing_confirmed"])
            svc.publish(s, aid, ids)
        return guarded(run)

    app.state.csrf_token = csrf_token
    return app
