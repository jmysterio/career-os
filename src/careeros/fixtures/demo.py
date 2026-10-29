"""The practice notebook: a week of made-up records, a few wins, and a tiny made-up leveling guide.

Everything here is fake. It exists so every page has something to show without touching real data.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..storage.models import GuideItem, GuideLink, JournalAttachment, JournalEntry, Win

# (days ago, kind, source, text, notes) - notes are shown under the record like a Slack tracker note
RECORDS = [
    (0, "meeting", "calendar", "9:30 AM–10:00 AM  Release readiness review", ""),
    (0, "task", "tasks", "Update the sandbox refresh checklist", ""),
    (1, "conversation", "slack", "Deployment: Pine 2.4 release to UAT",
     "Action: Deployed Pine 2.4 to UAT and posted the change log.\n"
     "Why it mattered: QA could start testing a day early."),
    (1, "meeting", "calendar", "2:00 PM–2:30 PM  Sprint planning", ""),
    (2, "document", "slack", "Documentation: Rollback runbook for the Pine pipeline",
     "Action: Wrote the rollback steps and shared them with the team.\n"
     "Why it mattered: anyone on call can now roll back without help."),
    (2, "task", "tasks", "Review three feature-branch pull requests", ""),
    (3, "conversation", "slack", "Sandbox / Environment: Full sandbox refresh planning",
     "Action: Lined up four teams for Friday's refresh and owned the timeline.\n"
     "Why it mattered: no team lost test data during the refresh."),
    (4, "note", "", "Office hours: answered branching questions from two new engineers", ""),
    (5, "meeting", "calendar", "11:00 AM–11:30 AM  1:1 with my manager", ""),
    (6, "task", "tasks", "Ship the Pine 2.3 hotfix", ""),
]

WINS = [  # (record index, title, why it mattered, size, theme)
    (2, "Wrote the Pine rollback runbook", "Anyone on call can now roll back without help.", "medium", "Process improvement"),
    (6, "Planned and ran a full sandbox refresh for four teams", "No team lost test data.", "large", "Leadership"),
]

GUIDE = [  # (kind, grade, name, description)
    ("summary", 6, "Senior: owns delivery for a project and guides others.", ""),
    ("summary", 7, "Lead: sets the approach across teams and programs.", ""),
    ("experience", 6, "Designs sandbox refresh strategies for a project.", ""),
    ("experience", 6, "Develops and executes deployment strategies with minimal downtime.", ""),
    ("experience", 6, "Generates end-to-end DevOps documentation and runbooks.", ""),
    ("experience", 6, "Proactively shares knowledge with teammates and mentors newer engineers.", ""),
    ("experience", 7, "Leads sandbox strategy across teams, including refresh cycles.", ""),
    ("experience", 7, "Independently deploys and manages releases across environments.", ""),
    ("skill", None, "Communicate Effectively", "Conveys information clearly."),
    ("skill", None, "Environment/Sandbox Management", "Manages sandboxes and refreshes."),
]

ACTIVITY = {2: "deployment", 4: "document", 5: "pr_review", 6: "sandbox_refresh", 7: "mentoring",
            9: "hotfix"}  # record index -> what it counts toward on the Promo map

LINKS = {  # record index -> guide names it shows
    2: ["Generates end-to-end DevOps documentation and runbooks."],
    6: ["Leads sandbox strategy across teams, including refresh cycles."],
    7: ["Proactively shares knowledge with teammates and mentors newer engineers."],
    9: ["Develops and executes deployment strategies with minimal downtime."],
}


def seed(s: Session, today: date | None = None) -> dict[str, int]:
    """Fill an empty practice notebook. Does nothing if it already has records."""
    if s.query(JournalEntry).first() is not None:
        return dict(records=0, wins=0, guide=0)
    today = today or date.today()
    now = datetime.now()
    entries = []
    for ago, kind, source, text, notes in RECORDS:
        e = JournalEntry(day=(today - timedelta(days=ago)).isoformat(), kind=kind, text=text, created_at=now,
                         source=source, external_id=f"demo:{len(entries)}" if source else None,
                         status="done" if kind == "task" else "", activity=ACTIVITY.get(len(entries), ""),
                         activity_read=True, grouped=True)
        s.add(e)
        s.flush()
        if notes:
            s.add(JournalAttachment(entry_id=e.id, kind="notes", title="From Slack (AI-written), Slack tracker",
                                    body=notes, created_at=now))
        entries.append(e)
    items = {}
    for pos, (kind, grade, name, desc) in enumerate(GUIDE):
        g = GuideItem(key=f"demo:{pos}", kind=kind, grade=grade, category="Practice", name=name,
                      description=desc, targets={"5": 2, "6": 3, "7": 4} if kind == "skill" else {},
                      position=pos, active=True)
        s.add(g)
        items[name] = g
    s.flush()
    for idx, names in LINKS.items():
        for n in names:
            s.add(GuideLink(item_id=items[n].id, entry_id=entries[idx].id, created_at=now))
    for idx, title, impact, size, theme in WINS:
        e = entries[idx]
        w = Win(day=e.day, title=title, impact=impact, size=size, theme=theme, entry_id=e.id, created_at=now)
        s.add(w)
        s.flush()
        for n in LINKS.get(idx, []):
            s.add(GuideLink(item_id=items[n].id, win_id=w.id, created_at=now))
    s.commit()
    return dict(records=len(entries), wins=len(WINS), guide=len(GUIDE))
