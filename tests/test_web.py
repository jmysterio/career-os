import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from typer.testing import CliRunner

from careeros.cli import app as cli
from careeros.config import DataDir, NotDemoData, resolve
from careeros.storage.db import make_engine, make_session_factory
from careeros.storage.models import Claim
from careeros.web.app import create_app

BASE = "http://127.0.0.1"


@pytest.fixture
def seeded(tmp_path):
    root = tmp_path / "demo"
    r = CliRunner().invoke(cli, ["demo", "seed", "--data-dir", str(root)])
    assert r.exit_code == 0, r.output
    dd = DataDir(root)
    app = create_app(dd)
    return dd, TestClient(app, base_url=BASE), app.state.csrf_token


def anchor_id(dd) -> int:
    from careeros.storage.models import Activity
    with make_session_factory(make_engine(dd.db))() as s:
        return s.scalar(select(Activity).where(Activity.title.contains("R-2026-10-B"))).id


def form(c, path, token, **data):
    return c.post(path, data={"csrf": token, **data}, follow_redirects=False)


def test_refuses_non_demo_dir(tmp_path):
    (tmp_path / "real").mkdir()
    with pytest.raises(NotDemoData):
        create_app(DataDir(tmp_path / "real"))


def test_host_origin_and_csrf_checks(seeded):
    dd, c, tok = seeded
    assert TestClient(create_app(dd), base_url="http://evil.example.com").get("/").status_code == 400
    assert c.get("/").status_code == 200
    assert c.post("/claims/1/approve", data={}).status_code == 403                     # no token
    assert c.post("/claims/1/approve", data={"csrf": "x"}).status_code == 403          # wrong token
    r = c.post("/claims/1/approve", data={"csrf": tok}, headers={"Origin": "http://evil.example.com"})
    assert r.status_code == 403                                                        # cross origin
    assert "default-src 'none'" in c.get("/").headers["content-security-policy"]


def test_imported_text_is_escaped(seeded):
    dd, c, tok = seeded
    aid = anchor_id(dd)
    form(c, f"/episodes/{aid}/impact", tok, text="<script>alert(1)</script>")
    html = c.get("/").text
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_page_shows_layers_provenance_and_traps(seeded):
    _, c, _ = seeded
    html = c.get("/").text
    assert "SYNTHETIC DATA" in html and "cos://obs/" in html
    assert "Unconfirmed link" in html and "Impact / why it mattered is unknown" in html
    assert "Team deployed 12 changes" in html or "team deployed 12 changes" in html.lower()


def test_review_flow_approve_publish_export(seeded):
    dd, c, tok = seeded
    aid = anchor_id(dd)
    engine = make_engine(dd.db)
    with make_session_factory(engine)() as s:
        obs = [x.id for x in s.scalars(select(Claim).where(Claim.layer == "observation"))]
        attr = [x.id for x in s.scalars(select(Claim).where(Claim.layer == "attribution"))]
    # publish with nothing approved is blocked with a message, not a crash
    r = form(c, f"/episodes/{aid}/publish", tok)
    assert r.status_code == 303 and "Blocked" in r.headers["location"]
    for cid in obs + attr:
        assert form(c, f"/claims/{cid}/approve", tok).status_code == 303
    form(c, f"/episodes/{aid}/impact", tok, text="Fewer failed deployments")
    with make_session_factory(engine)() as s:
        imp = s.scalar(select(Claim).where(Claim.layer == "interpretation")).id
    form(c, f"/claims/{imp}/approve", tok)
    form(c, f"/episodes/{aid}/publish", tok)
    r = CliRunner().invoke(cli, ["export", "--anchor", str(aid), "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    md = next(dd.exports.glob("*.md")).read_text()
    assert "[attribution | human_approved]" in md and "Fewer failed deployments" in md


def test_unlink_via_ui_persists_constraint(seeded):
    dd, c, tok = seeded
    aid = anchor_id(dd)
    html = c.get("/").text
    assert "Unlink" in html
    with make_session_factory(make_engine(dd.db))() as s:
        from careeros.storage.models import Activity
        m1 = s.scalar(select(Activity).where(Activity.title.contains("DEMO-101"))).id
    form(c, f"/episodes/{aid}/unlink", tok, activity_id=m1)
    r = CliRunner().invoke(cli, ["import", "--data-dir", str(dd.root)])  # full rebuild
    assert r.exit_code == 0
    assert "DEMO-101-fix-validation" not in c.get("/").text.split("Attribution claims")[0]


def test_cli_edit_flags_and_purge_flow(seeded):
    dd, c, tok = seeded
    runner = CliRunner()
    assert runner.invoke(cli, ["demo", "edit", "--data-dir", str(dd.root)]).exit_code == 0
    assert runner.invoke(cli, ["demo", "tombstone", "--data-dir", str(dd.root)]).exit_code == 0
    r = runner.invoke(cli, ["purge", "--source", "demo-sheet", "--reason", "test", "--yes",
                            "--data-dir", str(dd.root)])
    assert r.exit_code == 0, r.output
    assert b"October B" not in dd.db.read_bytes()


def test_data_files_are_owner_only(seeded):
    import stat
    dd, c, _ = seeded
    c.get("/")
    for p in [dd.db, dd.secret_file, *dd.root.glob("careeros.db-*"), *dd.approvals.glob("*.toml"),
              *(dd.inbox / "processed").glob("*.json")]:
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, p
    assert stat.S_IMODE(dd.root.stat().st_mode) == 0o700


def test_export_without_published_version_is_a_friendly_error(seeded):
    dd, _, _ = seeded
    r = CliRunner().invoke(cli, ["export", "--anchor", str(anchor_id(dd)), "--data-dir", str(dd.root)])
    assert r.exit_code == 1 and "Publish approved claims" in r.output and "Traceback" not in r.output
