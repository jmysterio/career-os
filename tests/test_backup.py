import sqlite3
import stat
from datetime import date, datetime, timedelta

from typer.testing import CliRunner

from careeros.backup import make_backup, prune
from careeros.cli import app as cli
from careeros.config import DataDir
from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import JournalEntry


def notebook(tmp_path, n=3):
    dd = DataDir(tmp_path / "nb")
    dd.init_personal()
    engine = make_engine(dd.db)
    init_db(engine)
    with make_session_factory(engine)() as s:
        for i in range(n):
            s.add(JournalEntry(day="2026-10-20", kind="note", text=f"entry {i}", created_at=datetime.now()))
        s.commit()
    return dd


def rows(db):
    with sqlite3.connect(db) as c:
        return [r[0] for r in c.execute("SELECT text FROM journal_entry ORDER BY id")]


def test_backup_has_the_same_rows_and_is_owner_only(tmp_path):
    dd = notebook(tmp_path)
    path = make_backup(dd, today=date(2026, 10, 28))
    assert path == dd.backups / "careeros-2026-10-28.db"
    assert rows(path) == ["entry 0", "entry 1", "entry 2"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(dd.backups.stat().st_mode) == 0o700
    with sqlite3.connect(dd.db) as c:
        c.execute("INSERT INTO journal_entry (day, kind, text, created_at, source, status, kind_was, ai_read, reviewed)"
                  " VALUES ('2026-10-28', 'note', 'later', '2026-10-28', '', '', '', 0, 0)")
    assert make_backup(dd, today=date(2026, 10, 28)) == path  # same day: overwritten, not duplicated
    assert rows(path)[-1] == "later" and len(list(dd.backups.glob("*.db"))) == 1


def test_backup_while_another_connection_is_writing(tmp_path):
    dd = notebook(tmp_path)
    busy = sqlite3.connect(dd.db)
    busy.execute("BEGIN IMMEDIATE")
    busy.execute("INSERT INTO journal_entry (day, kind, text, created_at, source, status, kind_was, ai_read, reviewed)"
                 " VALUES ('2026-10-28', 'note', 'not yet committed', '2026-10-28', '', '', '', 0, 0)")
    try:
        path = make_backup(dd, today=date(2026, 10, 28))
    finally:
        busy.rollback()
        busy.close()
    assert rows(path) == ["entry 0", "entry 1", "entry 2"]  # a consistent copy, without the half-done save


def test_prune_keeps_30_days_and_one_per_month(tmp_path):
    dd = notebook(tmp_path, n=0)
    dd.backups.mkdir(mode=0o700, exist_ok=True)
    start = date(2025, 9, 1)
    for i in range(420):
        (dd.backups / f"careeros-{start + timedelta(days=i):%Y-%m-%d}.db").write_bytes(b"x")
    (dd.backups / "notes.txt").write_text("not a backup")
    today = start + timedelta(days=419)  # 2026-10-24
    removed = prune(dd, today=today)
    kept = sorted(p.stem.removeprefix("careeros-") for p in dd.backups.glob("careeros-*.db"))
    daily = [d for d in kept if d >= (today - timedelta(days=29)).isoformat()]
    monthly = [d for d in kept if d not in daily]
    assert len(daily) == 30
    assert monthly == [f"{m}-01" for m in ("2025-11", "2025-12", "2026-01", "2026-02", "2026-03", "2026-04",
                                           "2026-05", "2026-06", "2026-07", "2026-08", "2026-09")]
    assert removed == 420 - len(kept) and (dd.backups / "notes.txt").exists()


def test_cli_backup_now_and_list(tmp_path):
    dd = notebook(tmp_path)
    r = CliRunner().invoke(cli, ["backup", "now", "--data-dir", str(dd.root)])
    assert r.exit_code == 0 and "Backed up to" in r.output, r.output
    r = CliRunner().invoke(cli, ["backup", "list", "--data-dir", str(dd.root)])
    assert r.exit_code == 0 and f"careeros-{date.today():%Y-%m-%d}.db" in r.output
