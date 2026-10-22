"""Data directory layout and the demo-only guard (milestone 1 never touches real data)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .ingest.importer import Approval

DEFAULT_DEMO_DIR = Path.home() / "Library" / "Application Support" / "CareerOS-demo"
SYNC_HINTS = ("iCloud", "Mobile Documents", "Dropbox", "Google Drive", "OneDrive")


class NotDemoData(RuntimeError):
    pass


@dataclass(frozen=True)
class DataDir:
    root: Path

    @property
    def db(self) -> Path: return self.root / "careeros.db"
    @property
    def inbox(self) -> Path: return self.root / "inbox"
    @property
    def exports(self) -> Path: return self.root / "exports"
    @property
    def approvals(self) -> Path: return self.root / "approvals"
    @property
    def secret_file(self) -> Path: return self.root / ".secret"
    @property
    def demo_marker(self) -> Path: return self.root / ".demo"

    def create(self) -> None:
        for d in (self.root, self.inbox, self.exports, self.approvals):
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)

    def require_demo(self) -> None:
        if not self.demo_marker.exists():
            raise NotDemoData(f"{self.root} is not a demo data dir; milestone 1 is synthetic-only")

    def sync_warning(self) -> str | None:
        r = str(self.root.resolve())
        return next((f"data dir is under a synced folder ({h})" for h in SYNC_HINTS if h in r), None)

    def secret(self) -> bytes:
        if not self.secret_file.exists():
            fd = os.open(self.secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(os.urandom(32))
        return self.secret_file.read_bytes()


def resolve(path: str | None) -> DataDir:
    return DataDir(Path(path or os.environ.get("CAREEROS_DATA_DIR") or DEFAULT_DEMO_DIR).expanduser())


def write_approval(dd: DataDir, cid: str, fields: set[str], expires: datetime, approver: str) -> None:
    body = (f'connector_instance_id = "{cid}"\napprover = "{approver}"\n'
            f'expires_at = "{expires.isoformat()}"\n'
            f"allowed_fields = [{', '.join(repr(f).replace(chr(39), chr(34)) for f in sorted(fields))}]\n")
    p = dd.approvals / f"{cid}.toml"
    p.write_text(body)
    os.chmod(p, 0o600)


def load_approvals(dd: DataDir) -> dict[str, Approval]:
    out: dict[str, Approval] = {}
    for p in dd.approvals.glob("*.toml"):
        d = tomllib.loads(p.read_text())
        out[d["connector_instance_id"]] = Approval(
            d["connector_instance_id"], frozenset(d["allowed_fields"]),
            datetime.fromisoformat(d["expires_at"]))
    return out
