"""Local review UI. Loopback-only, CSRF + Host/Origin checks, autoescaped rendering."""
from __future__ import annotations

import hashlib
import os
import hmac
import threading
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..claims import service as svc
from ..config import DataDir
from ..correlate.engine import link, rebuild_episodes, unlink
from ..storage.db import init_db, make_engine, make_session_factory
from ..storage.models import (
    AccomplishmentVersion, Activity, Claim, ClaimSupport, EpisodeMember, SourceObservation,
)

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
CSP = ("default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
       "base-uri 'none'; frame-ancestors 'none'")
_write_lock = threading.Lock()


def _hostname(value: str) -> str:
    return urlparse(f"//{value}").hostname or ""


def create_app(dd: DataDir) -> FastAPI:
    dd.require_demo()
    os.umask(0o077)
    engine = make_engine(dd.db)
    init_db(engine)
    Session_ = make_session_factory(engine)
    csrf_token = hmac.new(dd.secret(), b"csrf", hashlib.sha256).hexdigest()
    env = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"), autoescape=True)
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
        resp.headers["Referrer-Policy"] = "no-referrer"
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

    def back(msg: str | None = None) -> RedirectResponse:
        return RedirectResponse("/" + (f"?msg={quote(msg[:300])}" if msg else ""), status_code=303)

    def guarded(fn):
        try:
            with _write_lock:
                fn()
        except svc.ClaimBlocked as exc:
            return back("Blocked: " + "; ".join(exc.violations))
        return back()

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, msg: str | None = None, s: Session = Depends(db)):
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
                claims.append(dict(id=c.id, layer=c.layer, text=svc.render_claim(c), object=c.object,
                                   verification_status=c.verification_status, authored_by=c.authored_by,
                                   evidence=ev, violations=svc.violations(s, c)))
            versions = list(s.scalars(select(AccomplishmentVersion).where(
                AccomplishmentVersion.anchor_activity_id == a.id)))
            episodes.append(dict(anchor=a, members=members, claims=claims, versions=versions,
                                 unknowns=svc.unknowns_for(s, a.id),
                                 stale=any(v.id in stale for v in versions)))
        html = env.get_template("review.html").render(
            episodes=episodes, csrf=csrf_token, msg=msg, sync_warning=dd.sync_warning())
        return HTMLResponse(html)

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
            svc.publish(s, aid, ids)
        return guarded(run)

    app.state.csrf_token = csrf_token
    return app
