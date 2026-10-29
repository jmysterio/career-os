"""GitHub pull requests you merged or reviewed, through the `gh` command. Title, repo, date and link only; no Claude."""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage.models import JournalAttachment, JournalEntry

SOURCE = "github"
FIRST_LOOKBACK = timedelta(days=365)  # the promo case's default window
LIMIT = 1000  # GitHub search's ceiling
FIELDS = "title,repository,number,url,author,closedAt,updatedAt"
REVIEW_CHUNK = timedelta(days=30)
PAUSE = 2.0  # seconds between searches
LIST_TITLE = "Pull requests reviewed"


class GitHubError(Exception):
    pass


@dataclass(frozen=True)
class PR:
    repo: str
    number: int
    title: str
    url: str
    role: str  # "author" or "reviewer"
    day: date

    @property
    def key(self) -> str:
        return f"gh:{self.repo}#{self.number}:{self.role}"

    @property
    def text(self) -> str:
        verb = "Merged" if self.role == "author" else "Reviewed"
        return f"{verb} PR: {self.title} ({self.repo}#{self.number})"[:500]


def _gh(*args: str) -> str:
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=120, check=False)
    except FileNotFoundError:
        raise GitHubError("The GitHub command `gh` isn't installed (brew install gh, then gh auth login).")
    except subprocess.TimeoutExpired:
        raise GitHubError("GitHub didn't answer within 2 minutes. Try again later.")
    if p.returncode:
        raise GitHubError((p.stderr.strip().splitlines() or ["gh failed"])[-1][:300])
    return p.stdout


def login() -> str:
    try:
        return _gh("api", "user", "--jq", ".login").strip()
    except GitHubError:
        raise GitHubError("GitHub isn't signed in. In Terminal run: gh auth login")


def _local_day(ts: str) -> date:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()


def parse(text: str, role: str, me: str) -> list[PR]:
    out = []
    for r in json.loads(text or "[]"):
        if role == "reviewer" and (r.get("author") or {}).get("login", "").lower() == me.lower():
            continue  # your own PR shows up as "reviewed" when you comment on it
        ts = r.get("closedAt") or r.get("updatedAt")
        if not ts or str(ts).startswith("0001"):
            ts = r.get("updatedAt")
        out.append(PR(r["repository"]["nameWithOwner"], int(r["number"]), r["title"].strip(), r["url"], role,
                      _local_day(ts)))
    return out


def fetch(since: date, today: date | None = None) -> tuple[str, list[PR]]:
    """PRs you authored and merged since `since`, and ones you reviewed that closed (or changed) since then.
    Reviews are searched a month at a time: one search returns at most 1,000 and a year of reviews is more."""
    me, today = login(), today or date.today()
    common = ["--limit", str(LIMIT), "--json", FIELDS]
    prs = parse(_gh("search", "prs", "--author=@me", f"--merged-at=>={since}", *common), "author", me)
    start = since
    while start <= today:
        end = min(start + REVIEW_CHUNK, today)
        time.sleep(PAUSE)  # GitHub's secondary rate limit trips on back-to-back searches
        prs += parse(_gh("search", "prs", "--reviewed-by=@me", f"--updated={start}..{end}", *common), "reviewer", me)
        start = end + timedelta(days=1)
    return me, list({p.key: p for p in prs if p.day >= since}.values())


def since(s: Session) -> date:
    from ..storage.sync_log import status
    last = status(s)[SOURCE]["at"]
    return (last - timedelta(days=2)).date() if last else date.today() - FIRST_LOOKBACK


def week_key(repo: str, monday: date) -> str:
    return f"gh:reviews:{repo}:{monday}"


def _week_text(repo: str, monday: date, n: int) -> str:
    return f"Reviewed {n} pull request{'' if n == 1 else 's'} in {repo}, week of {monday:%b} {monday.day}"


def _list_body(prs: dict[str, str]) -> str:
    return "\n".join(f"- {title} — {url}" for url, title in sorted(prs.items()))


def _listed(body: str) -> dict[str, str]:
    return {line.rsplit(" — ", 1)[1]: line[2:].rsplit(" — ", 1)[0] for line in body.splitlines() if " — " in line}


def merge(s: Session, prs: list[PR]) -> dict[str, int]:
    """PRs you merged come in one record each. Reviews come in as one record per repo per week, which grows as the
    week's reviews arrive. Never deletes: the search only covers recent PRs."""
    from ..storage.removal import removed_ids, skip_patterns
    from ..storage.sync_log import record
    mine = {e.external_id: e for e in s.scalars(select(JournalEntry).where(JournalEntry.source == SOURCE))}
    gone, skips = removed_ids(s, SOURCE), skip_patterns(s, SOURCE)
    today = date.today()
    added = updated = skipped = 0
    weeks: dict[tuple[str, date], list[PR]] = {}
    for pr in prs:
        if any(p in pr.text.lower() for p in skips):
            skipped += 1
        elif pr.role == "reviewer":
            weeks.setdefault((pr.repo, pr.day - timedelta(days=pr.day.weekday())), []).append(pr)
        elif pr.key not in mine and pr.key not in gone:
            e = JournalEntry(day=min(pr.day, today).isoformat(), kind="task", text=pr.text, source=SOURCE,
                             created_at=datetime.now(), external_id=pr.key, status="done")
            s.add(e)
            s.flush()
            s.add(JournalAttachment(entry_id=e.id, kind="link", title="Pull request", body=pr.url,
                                    created_at=datetime.now()))
            mine[pr.key] = e
            added += 1
    for (repo, monday), got in weeks.items():
        key = week_key(repo, monday)
        if key in gone or any(p in repo.lower() for p in skips):
            continue
        e = mine.get(key)
        att = e and s.scalar(select(JournalAttachment).where(JournalAttachment.entry_id == e.id,
                                                             JournalAttachment.title == LIST_TITLE))
        listed = _listed(att.body) if att else {}
        new = {p.url: p.title for p in got if p.url not in listed}
        if e and not new:
            continue
        listed |= new
        day = min(max([p.day for p in got] + ([date.fromisoformat(e.day)] if e else [])), today).isoformat()
        if e is None:
            e = JournalEntry(kind="task", source=SOURCE, created_at=datetime.now(), external_id=key, status="done")
            s.add(e)
            added += 1
        else:
            updated += 1
        e.text, e.day = _week_text(repo, monday, len(listed)), day
        s.flush()
        if att:
            att.body = _list_body(listed)
        else:
            s.add(JournalAttachment(entry_id=e.id, kind="notes", title=LIST_TITLE, body=_list_body(listed),
                                    created_at=datetime.now()))
    record(s, SOURCE, added)
    s.commit()
    return dict(added=added, updated=updated, skipped=skipped)
