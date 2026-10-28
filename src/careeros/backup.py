"""Daily copies of the notebook: the last 30 days, plus the first copy of each of the last 12 months."""
from __future__ import annotations

import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from .config import DataDir

DAILY = 30
MONTHLY = 12


def _day(p: Path) -> date | None:
    try:
        return date.fromisoformat(p.stem.removeprefix("careeros-"))
    except ValueError:
        return None


def make_backup(dd: DataDir, today: date | None = None) -> Path:
    """A consistent copy via SQLite's backup API, safe while the app is running. Today's copy is replaced."""
    today = today or date.today()
    dd.backups.mkdir(mode=0o700, exist_ok=True)
    os.chmod(dd.backups, 0o700)
    dest = dd.backups / f"careeros-{today:%Y-%m-%d}.db"
    tmp = dest.with_suffix(".db.part")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.close(fd)
    src = sqlite3.connect(dd.db)
    out = sqlite3.connect(tmp)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    os.replace(tmp, dest)
    return dest


def backups(dd: DataDir) -> list[tuple[date, Path]]:
    if not dd.backups.exists():
        return []
    return sorted((d, p) for p in dd.backups.glob("careeros-*.db") if (d := _day(p)))


def prune(dd: DataDir, today: date | None = None, daily: int = DAILY, monthly: int = MONTHLY) -> int:
    """Delete copies older than `daily` days, except the first copy of each of the last `monthly` months."""
    today = today or date.today()
    recent = today - timedelta(days=daily - 1)
    months = set()
    y, m = today.year, today.month
    for _ in range(monthly):
        months.add((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    first_of_month: dict[tuple[int, int], date] = {}
    found = backups(dd)
    for d, _ in found:
        first_of_month.setdefault((d.year, d.month), d)
    keep = {d for d, _ in found if d >= recent} | {d for k, d in first_of_month.items() if k in months}
    removed = 0
    for d, p in found:
        if d not in keep:
            p.unlink()
            removed += 1
    return removed
