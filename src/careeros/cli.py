"""careeros CLI. Milestone 1 operates on demo data dirs only."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Optional

import typer
from sqlalchemy import select

from .claims import service as svc
from .config import PERSONAL_DIR, DataDir, NotDemoData, load_approvals, resolve, write_approval
from .correlate.engine import rebuild_episodes
from .correlate.project import ensure_self, project_activities
from .export.markdown import export_markdown
from .fixtures import demo as fx
from .ingest.files import handoff, ingest_ready_dir
from .lifecycle.purge import purge_source
from .storage.db import init_db, make_engine, make_session_factory
from .storage.models import Activity, ConnectorInstance

app = typer.Typer(no_args_is_help=True)
demo_app = typer.Typer(no_args_is_help=True, help="Synthetic-data helpers")
app.add_typer(demo_app, name="demo")
DataOpt = typer.Option(None, "--data-dir", help="Demo data dir (default: CAREEROS_DATA_DIR or app support)")


def _open(dd: DataDir):
    os.umask(0o077)  # db, WAL, and SHM files are created owner-only
    dd.require_demo()
    engine = make_engine(dd.db)
    init_db(engine)
    return make_session_factory(engine)()


def _refresh(s, dd: DataDir) -> dict:
    counts = ingest_ready_dir(s, dd.inbox, load_approvals(dd))
    project_activities(s)
    rebuild_episodes(s)
    return counts


@demo_app.command("seed")
def demo_seed(data_dir: Optional[str] = DataOpt) -> None:
    """Create a demo workspace, ingest the synthetic story, and draft claims."""
    dd = resolve(data_dir, demo=True)
    if dd.is_personal:
        typer.echo("That folder is your personal notebook. Demo data is never put there.")
        raise typer.Exit(1)
    dd.create()
    dd.demo_marker.write_text("synthetic data only\n")
    expires = fx.T0 + timedelta(days=365)
    for cid, fields in fx.ALLOWED.items():
        write_approval(dd, cid, fields, expires, approver="demo-fixture")
    with _open(dd) as s:
        for cid, (stype, ns) in fx.CONNECTORS.items():
            if s.get(ConnectorInstance, cid) is None:
                s.add(ConnectorInstance(id=cid, source_type=stype, namespace=ns, is_fixture=True))
        s.commit()
        ensure_self(s, fx.SELF_EMAIL)
        s.commit()
        for env in fx.initial_envelopes():
            handoff(env, dd.inbox)
        counts = _refresh(s, dd)
        for a in s.scalars(select(Activity).where(Activity.type == "release_row", Activity.state == "present")):
            svc.draft_episode(s, a.id)
    typer.echo(f"seeded {dd.root} ({counts})")


@demo_app.command("edit")
def demo_edit(data_dir: Optional[str] = DataOpt) -> None:
    """Deliver a later sheet export that renames the release row (source edit scenario)."""
    dd = resolve(data_dir, demo=True)
    handoff(fx.sheet_title_edit(), dd.inbox)
    with _open(dd) as s:
        typer.echo(str(_refresh(s, dd)))


@demo_app.command("tombstone")
def demo_tombstone(data_dir: Optional[str] = DataOpt) -> None:
    """Deliver an export that explicitly deletes release row C."""
    dd = resolve(data_dir, demo=True)
    handoff(fx.sheet_tombstone_c(), dd.inbox)
    with _open(dd) as s:
        typer.echo(str(_refresh(s, dd)))


@app.command("import")
def import_cmd(data_dir: Optional[str] = DataOpt) -> None:
    """Ingest envelopes waiting in inbox/ready."""
    dd = resolve(data_dir)
    with _open(dd) as s:
        typer.echo(str(_refresh(s, dd)))


@app.command("draft")
def draft(data_dir: Optional[str] = DataOpt) -> None:
    """Re-draft claims for every episode and print open questions."""
    dd = resolve(data_dir)
    with _open(dd) as s:
        for a in s.scalars(select(Activity).where(Activity.type == "release_row", Activity.state == "present")):
            typer.echo(a.title)
            for u in svc.draft_episode(s, a.id):
                typer.echo(f"  ? {u}")


@app.command("export")
def export_cmd(anchor: int = typer.Option(..., help="Episode anchor activity id"),
               data_dir: Optional[str] = DataOpt) -> None:
    dd = resolve(data_dir)
    with _open(dd) as s:
        try:
            typer.echo(str(export_markdown(s, anchor, dd.exports)))
        except ValueError:
            typer.echo("Nothing to export yet: approve some claims and click 'Publish approved claims' "
                       "on the review page first.")
            raise typer.Exit(1)


@app.command("purge")
def purge_cmd(source: str = typer.Option(..., help="Connector instance id"),
              reason: str = typer.Option(...), yes: bool = typer.Option(False, "--yes"),
              data_dir: Optional[str] = DataOpt) -> None:
    dd = resolve(data_dir)
    if not yes:
        typer.confirm(f"Permanently purge all content from '{source}'?", abort=True)
    with _open(dd) as s:
        rep = purge_source(s, source, inbox=dd.inbox, export_dir=dd.exports, reason=reason)
    typer.echo(f"purged {rep.observations} observations, {rep.claims} claims, "
               f"{rep.versions_withdrawn} versions withdrawn, {len(rep.files_deleted)} files")
    for m in rep.manual_actions:
        typer.echo(f"  ! {m}")


notebook_app = typer.Typer(no_args_is_help=True, help="Your personal notebook")
app.add_typer(notebook_app, name="notebook")


@notebook_app.command("init")
def notebook_init(data_dir: Optional[str] = typer.Option(None, "--data-dir", help="Default: ~/Library/Application Support/CareerOS")) -> None:
    """Create your real, permanent notebook (journal only). Imports of work data stay off."""
    os.umask(0o077)
    dd = DataDir(__import__("pathlib").Path(data_dir).expanduser()) if data_dir else DataDir(PERSONAL_DIR)
    try:
        dd.init_personal()
    except NotDemoData as exc:
        typer.echo(str(exc))
        raise typer.Exit(1)
    with_db = make_engine(dd.db)
    init_db(with_db)
    typer.echo(f"Your notebook is ready at {dd.root}")
    typer.echo("Start it with:  uv run careeros serve" + (f" --data-dir {dd.root}" if data_dir else ""))


@app.command("serve")
def serve(port: int = 8765, data_dir: Optional[str] = DataOpt) -> None:
    """Serve the review UI on loopback only (host is not configurable)."""
    import uvicorn
    from .web.app import create_app
    dd = resolve(data_dir)
    uvicorn.run(create_app(dd), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    app()
