"""Explicit-key correlation anchored on release rows (plan §4/§8).

Same-day or time proximity never creates a link. A key shared by several
release rows yields only *suggested* links. User decisions live in
CorrelationConstraint and survive full rebuilds.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..storage.models import Activity, CorrelationConstraint, EpisodeMember


def _ent(activity_id: int) -> str:
    return f"activity:{activity_id}"


def _constraint(session: Session, a: int, b: int, relation: str) -> CorrelationConstraint | None:
    for l, r in ((a, b), (b, a)):
        c = session.scalar(select(CorrelationConstraint).where(
            CorrelationConstraint.left_entity == _ent(l),
            CorrelationConstraint.right_entity == _ent(r),
            CorrelationConstraint.relation == relation))
        if c:
            return c
    return None


def rebuild_episodes(session: Session) -> None:
    session.execute(delete(EpisodeMember))
    anchors = session.scalars(select(Activity).where(
        Activity.type == "release_row", Activity.state == "present")).all()
    others = session.scalars(select(Activity).where(
        Activity.type.in_(["merge_commit", "commit"]), Activity.state == "present")).all()
    for act in others:
        matches = []
        for anc in anchors:
            shared = sorted(set(act.keys) & set(anc.keys))
            if shared and not _constraint(session, act.id, anc.id, "cannot_link"):
                matches.append((anc, shared))
        for anc, shared in matches:
            explicit = len(matches) == 1
            session.add(EpisodeMember(
                anchor_activity_id=anc.id, activity_id=act.id,
                origin="explicit" if explicit else "ambiguous",
                status="linked" if explicit else "suggested",
                confidence=0.9 if explicit else 0.4,
                reason=f"shared key {', '.join(shared)}"
                       + ("" if explicit else f" (also matches {len(matches) - 1} other release(s))")))
    session.flush()
    for c in session.scalars(select(CorrelationConstraint).where(
            CorrelationConstraint.relation == "must_link")):
        l, r = int(c.left_entity.split(":")[1]), int(c.right_entity.split(":")[1])
        la, ra = session.get(Activity, l), session.get(Activity, r)
        anc, act = (la, ra) if la.type == "release_row" else (ra, la)
        if anc.type != "release_row" or anc.state != "present" or act.state != "present":
            continue
        # a manual link replaces any other membership row for the pair
        session.execute(delete(EpisodeMember).where(
            EpisodeMember.anchor_activity_id == anc.id, EpisodeMember.activity_id == act.id))
        session.add(EpisodeMember(anchor_activity_id=anc.id, activity_id=act.id, origin="manual",
                                  status="linked", confidence=1.0, reason="user link"))
    session.commit()


def link(session: Session, activity_id: int, anchor_id: int) -> None:
    old = _constraint(session, activity_id, anchor_id, "cannot_link")
    if old:
        session.delete(old)
    if not _constraint(session, activity_id, anchor_id, "must_link"):
        session.add(CorrelationConstraint(left_entity=_ent(activity_id), right_entity=_ent(anchor_id),
                                          relation="must_link"))
    session.commit()
    rebuild_episodes(session)


def unlink(session: Session, activity_id: int, anchor_id: int) -> None:
    old = _constraint(session, activity_id, anchor_id, "must_link")
    if old:
        session.delete(old)
    if not _constraint(session, activity_id, anchor_id, "cannot_link"):
        session.add(CorrelationConstraint(left_entity=_ent(activity_id), right_entity=_ent(anchor_id),
                                          relation="cannot_link"))
    session.commit()
    rebuild_episodes(session)
