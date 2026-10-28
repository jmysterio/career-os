"""Two macOS launch agents: one keeps the app running, one runs `careeros sync all` at 8 AM, 6 PM, and login."""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

from .config import DataDir

APP, SYNC = "com.careeros.app", "com.careeros.sync"
AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
REPO = Path(__file__).resolve().parents[2]
PATH = ":".join([str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"])


def launchctl(*args: str) -> int:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True).returncode


def _uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("Couldn't find the `uv` command; install it or run this from a Terminal where `uv` works.")
    return str(Path(uv).resolve())


def plists(dd: DataDir, uv: str, repo: Path = REPO) -> dict[str, dict]:
    logs = dd.root / "logs"
    base = ["run", "--project", str(repo), "careeros"]
    env = {"PATH": PATH, "CAREEROS_DATA_DIR": str(dd.root)}
    return {
        APP: dict(Label=APP, ProgramArguments=[uv, *base, "serve"], WorkingDirectory=str(repo), RunAtLoad=True,
                  KeepAlive=True, EnvironmentVariables=env, StandardOutPath=str(logs / "app.log"),
                  StandardErrorPath=str(logs / "app.log")),
        SYNC: dict(Label=SYNC, ProgramArguments=[uv, *base, "sync", "all"], WorkingDirectory=str(repo),
                   RunAtLoad=True, StartCalendarInterval=[{"Hour": 8, "Minute": 0}, {"Hour": 18, "Minute": 0}],
                   EnvironmentVariables=env, StandardOutPath=str(logs / "sync-agent.log"),
                   StandardErrorPath=str(logs / "sync-agent.log")),
    }


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(dd: DataDir, agents_dir: Path = AGENTS_DIR, uv: str | None = None, repo: Path = REPO) -> list[Path]:
    (dd.root / "logs").mkdir(mode=0o700, exist_ok=True)
    agents_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for label, spec in plists(dd, uv or _uv(), repo).items():
        path = agents_dir / f"{label}.plist"
        launchctl("bootout", f"{_domain()}/{label}")
        path.write_bytes(plistlib.dumps(spec))
        launchctl("bootstrap", _domain(), str(path))
        written.append(path)
    return written


def uninstall(agents_dir: Path = AGENTS_DIR) -> list[Path]:
    removed = []
    for label in (APP, SYNC):
        launchctl("bootout", f"{_domain()}/{label}")
        path = agents_dir / f"{label}.plist"
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def status(dd: DataDir, agents_dir: Path = AGENTS_DIR) -> list[str]:
    lines = []
    for label, what in ((APP, "Keeps the app running"), (SYNC, "Syncs at 8 AM, 6 PM, and login")):
        installed = (agents_dir / f"{label}.plist").exists()
        loaded = installed and launchctl("print", f"{_domain()}/{label}") == 0
        lines.append(f"{what}: {'on' if loaded else 'installed but not loaded' if installed else 'off'}")
    logs = sorted((dd.root / "logs").glob("sync-*.log"))
    if logs:
        last = [l for l in logs[-1].read_text().splitlines() if l.strip()]
        lines.append(f"Last sync log ({logs[-1].name}): {last[-1] if last else 'empty'}")
    return lines
