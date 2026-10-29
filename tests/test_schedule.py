import plistlib
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from careeros import schedule, sync_all
from careeros.cli import app as cli
from careeros.config import DataDir
from careeros.storage.db import init_db, make_engine, make_session_factory
from careeros.storage.models import SyncRun


@pytest.fixture
def dd(tmp_path):
    d = DataDir(tmp_path / "nb")
    d.init_personal()
    init_db(make_engine(d.db))
    return d


def fake_syncs(monkeypatch, fail=None):
    """Replace the two real syncs with ones that log a SyncRun, or fail one step."""
    calls = []

    def runner(name, source):
        def run(job, Session_, lock, *rest):
            calls.append(name)
            if fail == name:
                job.fail(0, "Claude Code's Slack sign-in has expired. Sign in again.")
                for i in range(1, len(job.steps)):
                    job.skip(i)
                job.finish("Slack sync couldn't read the tracker, so nothing changed.")
                return
            with Session_() as s:
                s.add(SyncRun(source=source, at=datetime.now(), added=1))
                s.commit()
            for i in range(len(job.steps)):
                job.done(i, "ok")
            job.finish(f"{name} synced")
        return run
    monkeypatch.setattr(sync_all.syncs, "run_slack", runner("slack", "slack"))
    monkeypatch.setattr(sync_all.syncs, "run_google", runner("google", "calendar"))
    monkeypatch.setattr(sync_all.syncs, "run_github", runner("github", "github"))
    return calls


def test_sync_all_backs_up_runs_each_and_logs(dd, monkeypatch):
    calls = fake_syncs(monkeypatch)
    notes = []
    assert sync_all.run(dd, force=True, notify=lambda t, m: notes.append((t, m))) == 0
    assert calls == ["slack", "google", "github"] and not notes
    assert list(dd.backups.glob("careeros-*.db"))
    log = next((dd.root / "logs").glob("sync-*.log")).read_text()
    assert "slack synced" in log and "google synced" in log and "backup" in log.lower()


def test_failure_notifies_and_exits_nonzero(dd, monkeypatch):
    fake_syncs(monkeypatch, fail="slack")
    notes = []
    assert sync_all.run(dd, force=True, notify=lambda t, m: notes.append((t, m))) == 1
    assert len(notes) == 1 and "Slack" in notes[0][0] and "sign in again" in notes[0][1].lower()


def test_catch_up_is_a_no_op_after_a_covered_run(dd, monkeypatch):
    calls = fake_syncs(monkeypatch)
    with make_session_factory(make_engine(dd.db))() as s:
        for src in ("slack", "calendar"):
            s.add(SyncRun(source=src, at=datetime(2026, 10, 28, 18, 5), added=0))
        s.commit()
    assert sync_all.run(dd, now=datetime(2026, 10, 28, 21, 0), notify=lambda *a: None) == 0
    assert calls == []  # 6 PM run already happened
    assert sync_all.run(dd, now=datetime(2026, 10, 29, 9, 0), notify=lambda *a: None) == 0
    assert calls == ["slack", "google", "github"]  # 8 AM not covered yet


def test_sync_all_waits_out_a_save_in_the_running_app(dd, monkeypatch):
    import sqlite3
    import threading
    import time
    fake_syncs(monkeypatch)
    app = sqlite3.connect(dd.db, check_same_thread=False)
    app.execute("BEGIN IMMEDIATE")  # the app is in the middle of a save

    def finish_save():
        time.sleep(1)
        app.commit()
    t = threading.Thread(target=finish_save)
    t.start()
    try:
        assert sync_all.run(dd, force=True, notify=lambda *a: None) == 0
    finally:
        t.join()
        app.close()
    with make_session_factory(make_engine(dd.db))() as s:
        assert s.query(SyncRun).count() == 3


def test_last_scheduled_time():
    at = sync_all.last_scheduled
    assert at(datetime(2026, 10, 28, 7, 59)) == datetime(2026, 10, 27, 18, 0)
    assert at(datetime(2026, 10, 28, 8, 0)) == datetime(2026, 10, 28, 8, 0)
    assert at(datetime(2026, 10, 28, 17, 59)) == datetime(2026, 10, 28, 8, 0)
    assert at(datetime(2026, 10, 28, 18, 30)) == datetime(2026, 10, 28, 18, 0)


def test_notification_text_is_escaped(monkeypatch):
    seen = []
    monkeypatch.setattr(sync_all.subprocess, "run", lambda args, **kw: seen.append(args))
    sync_all.mac_notify('Slack "sync"', 'it said \\ "no"')
    assert seen[0][0] == "osascript" and '\\"sync\\"' in seen[0][2] and '\\\\' in seen[0][2]


def test_plists_have_absolute_paths_and_the_right_schedule(dd, tmp_path):
    agents = schedule.plists(dd, uv="/opt/uv", repo=Path("/repo"))
    app, sync = agents[schedule.APP], agents[schedule.SYNC]
    assert app["ProgramArguments"] == ["/opt/uv", "run", "--project", "/repo", "careeros", "serve"]
    assert app["KeepAlive"] is True and app["RunAtLoad"] is True and app["WorkingDirectory"] == "/repo"
    assert sync["ProgramArguments"][-2:] == ["sync", "all"]
    assert sync["StartCalendarInterval"] == [{"Hour": 8, "Minute": 0}, {"Hour": 18, "Minute": 0}]
    assert sync["RunAtLoad"] is True and "KeepAlive" not in sync
    assert str(dd.root / "logs") in app["StandardErrorPath"]
    assert "/.local/bin" in app["EnvironmentVariables"]["PATH"]


def test_install_and_uninstall_write_and_remove_only_their_files(dd, tmp_path, monkeypatch):
    agents_dir = tmp_path / "LaunchAgents"
    agents_dir.mkdir()
    (agents_dir / "com.other.plist").write_text("keep me")
    ran = []
    monkeypatch.setattr(schedule, "launchctl", lambda *args: ran.append(args) or 0)
    schedule.install(dd, agents_dir=agents_dir, uv="/opt/uv", repo=Path("/repo"))
    files = sorted(p.name for p in agents_dir.glob("com.careeros.*.plist"))
    assert files == ["com.careeros.app.plist", "com.careeros.digest.plist", "com.careeros.sync.plist"]
    digest = plistlib.loads((agents_dir / "com.careeros.digest.plist").read_bytes())
    assert digest["StartCalendarInterval"] == [{"Weekday": 5, "Hour": 12, "Minute": 0}] and "RunAtLoad" not in digest
    assert digest["ProgramArguments"][-2:] == ["digest", "notify"]
    assert plistlib.loads((agents_dir / "com.careeros.sync.plist").read_bytes())["Label"] == "com.careeros.sync"
    assert any(a[0] == "bootstrap" for a in ran)
    schedule.uninstall(agents_dir=agents_dir)
    assert not list(agents_dir.glob("com.careeros.*")) and (agents_dir / "com.other.plist").exists()
    assert any(a[0] == "bootout" for a in ran)


def test_a_signed_out_connector_gets_a_plain_message(monkeypatch):
    import json as _json
    from types import SimpleNamespace
    from careeros import claude_cli
    init = {"type": "system", "subtype": "init", "mcp_servers": [
        {"name": "plugin:google-workspace:google-workspace", "status": "failed"},
        {"name": "plugin:slack:slack", "status": "connected"}]}
    monkeypatch.setattr(claude_cli, "_claude", lambda: "claude")
    monkeypatch.setattr(claude_cli.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(stdout=_json.dumps(init) + "\n", stderr=""))
    with pytest.raises(claude_cli.ClaudeError, match="Google Workspace connector isn't signed in"):
        claude_cli.call_tool("x", "mcp__plugin_google-workspace_google-workspace__list_task_lists")
    with pytest.raises(claude_cli.ClaudeError, match="didn't get an answer"):  # Slack is up; a different problem
        claude_cli.call_tool("x", "mcp__plugin_slack_slack__slack_read_canvas")


def test_reinstall_waits_for_the_old_copy_to_stop(dd, tmp_path, monkeypatch):
    agents_dir = tmp_path / "LaunchAgents"
    tries = []

    def launchctl(*args):
        if args[0] == "bootstrap":
            tries.append(args[-1])
            return 5 if len(tries) <= 2 else 0  # macOS refuses while the old copy is still unloading
        return 0
    monkeypatch.setattr(schedule, "launchctl", launchctl)
    monkeypatch.setattr(schedule, "pause", lambda s: None)
    assert len(schedule.install(dd, agents_dir=agents_dir, uv="/opt/uv", repo=Path("/repo"))) == 3
    assert len(tries) == 5  # two refusals, then the app, sync and digest agents load
    monkeypatch.setattr(schedule, "launchctl", lambda *a: 5 if a[0] == "bootstrap" else 0)
    with pytest.raises(RuntimeError, match="wouldn't load"):
        schedule.install(dd, agents_dir=agents_dir, uv="/opt/uv", repo=Path("/repo"))


def test_cli_sync_all_refuses_practice_notebook(tmp_path):
    d = DataDir(tmp_path / "practice")
    d.init_demo()
    r = CliRunner().invoke(cli, ["sync", "all", "--data-dir", str(d.root)])
    assert r.exit_code == 1 and "personal notebook" in r.output


def test_status_shows_the_dated_sync_log_not_the_launchd_one(dd, monkeypatch):
    monkeypatch.setattr(schedule, "launchctl", lambda *a: 1)
    logs = dd.root / "logs"
    logs.mkdir()
    (logs / "sync-2026-10-28.log").write_text("18:00:09  Google: Google synced\n")
    (logs / "sync-agent.log").write_text("launchd noise\n")
    assert "Google synced" in schedule.status(dd)[-1]


def test_install_says_so_when_macos_refuses_to_load_an_agent(dd, tmp_path, monkeypatch):
    monkeypatch.setattr(schedule, "launchctl", lambda *args: 1 if args[0] == "bootstrap" else 0)
    with pytest.raises(RuntimeError, match="wouldn't load"):
        schedule.install(dd, agents_dir=tmp_path / "LaunchAgents", uv="/opt/uv", repo=Path("/repo"))


def test_a_crashing_sync_does_not_stop_the_other_and_notifies(dd, monkeypatch):
    calls = fake_syncs(monkeypatch)

    def crash(job, Session_, lock, *rest):
        raise ValueError("canvas exploded")
    monkeypatch.setattr(sync_all.syncs, "run_slack", crash)
    notes = []
    assert sync_all.run(dd, force=True, notify=lambda t, m: notes.append((t, m))) == 1
    assert calls == ["google", "github"] and len(notes) == 1 and "Slack" in notes[0][0]


def test_a_second_sync_exits_while_one_is_running(dd, monkeypatch):
    import fcntl
    calls = fake_syncs(monkeypatch)
    (dd.root / "logs").mkdir()
    with (dd.root / "logs" / "sync.lock").open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert sync_all.run(dd, force=True, notify=lambda *a: None) == sync_all.LOCKED
    assert calls == []


def test_a_stuck_notification_is_ignored(monkeypatch):
    def hang(*a, **k):
        raise sync_all.subprocess.TimeoutExpired("osascript", 10)
    monkeypatch.setattr(sync_all.subprocess, "run", hang)
    sync_all.mac_notify("t", "m")


def test_cli_install_prints_the_error_instead_of_a_traceback(dd, monkeypatch):
    def refuse(*a, **k):
        raise RuntimeError("macOS wouldn't load it")
    monkeypatch.setattr(schedule, "install", refuse)
    r = CliRunner().invoke(cli, ["schedule", "install", "--data-dir", str(dd.root)])
    assert r.exit_code == 1 and "wouldn't load" in r.output and "Traceback" not in r.output
