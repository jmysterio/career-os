"""Local review UI. Loopback-only, CSRF + Host/Origin checks, autoescaped rendering."""
from __future__ import annotations

import hashlib
import os
import hmac
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..claims import service as svc
from ..config import DataDir
from ..correlate.engine import link, rebuild_episodes, unlink
from ..storage.db import init_db, make_engine, make_session_factory
from ..storage.models import (
    AccomplishmentVersion, Activity, Claim, ClaimSupport, EpisodeMember, JournalAttachment, JournalEntry, SourceObservation,
)

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
CSP = ("default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
       "base-uri 'none'; frame-ancestors 'none'")
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
PAGES = {"/", "/releases", "/search", *TABS}
LIST_LIMIT = 300


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


def create_app(dd: DataDir) -> FastAPI:
    dd.require_known()
    personal = dd.is_personal
    os.umask(0o077)
    engine = make_engine(dd.db)
    init_db(engine)
    Session_ = make_session_factory(engine)
    csrf_token = hmac.new(dd.secret(), b"csrf", hashlib.sha256).hexdigest()
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True)
    env.globals["tabs"] = TABS
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
                url=a.body.strip() if link else None))
        return [dict(id=e.id, day=e.day, text=e.text, kind_label=KIND_LABEL.get(e.kind, "Note"),
                     from_calendar=e.source == "calendar", status=e.status, attachments=atts.get(e.id, []))
                for e in rows]

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
            sync_warning=dd.sync_warning(), theme=theme_of(request), greeting=greeting(), page="/", personal=personal, q="")
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
        except gcal.CalendarError as exc:
            return back(str(exc), "/")
        return back(f"Calendar synced: {r['added']} new, {r['updated']} changed, {r['removed']} removed.", "/")

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
            e = s.get(JournalEntry, eid)
            if e:
                for a in s.scalars(select(JournalAttachment).where(JournalAttachment.entry_id == eid)):
                    s.delete(a)
                s.delete(e)
                s.commit()
        return back(to="/")

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
