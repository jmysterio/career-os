"""Rule checks over structured claims (plan §5).

These are *rule* checks, reported as `rule_checked` -- never as factual
verification. Pure functions over views so every failure class is testable
with hand-built claims.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

FIRST_PERSON_ROLES = {"author", "reviewer", "owner", "lead", "coordinator"}
NON_SELF_SUBJECTS = {"team", "we", "they"}
PLANNING_CUE = re.compile(r"(?i)\b(target|goal|expected|planned|aim|aims|aiming)\b")
COMPLETION_CUE = re.compile(r"(?i)\b(deployed|merg(?:e|ed)|completed|released|done|landed)\b")


@dataclass
class SupportView:
    observation_id: int
    excerpt: str
    record_id: str
    polarity: str = "supports"
    is_current: bool = True
    in_episode: bool = True  # cited activity is the anchor, user's own note, or a linked member
    self_roles: set[str] = field(default_factory=set)


@dataclass
class ClaimView:
    layer: str            # observation | attribution | interpretation
    subject: str
    status: str           # planned | in_progress | completed | cancelled
    contribution_role: str | None = None
    metric_value: float | None = None
    metric_unit: str | None = None
    metric_scope: str | None = None
    authored_by: str = "template"
    supports: list[SupportView] = field(default_factory=list)


def _has_number(text: str, value: float) -> bool:
    v = str(int(value)) if float(value).is_integer() else str(value)
    return re.search(rf"(?<![\d.]){re.escape(v)}(?![\d.])", text) is not None


def check(c: ClaimView) -> list[str]:
    out: list[str] = []
    pro = [s for s in c.supports if s.polarity == "supports"]
    if not pro:
        out.append("uncited: claim has no supporting evidence")
    if any(s.polarity == "contradicts" for s in c.supports):
        out.append("contradicted: resolve contradicting evidence before approval")
    if any(not s.is_current for s in c.supports):
        out.append("stale_evidence: a cited source changed or was removed after this claim")

    if any(not s.in_episode for s in c.supports):
        out.append("stale_link: a cited activity is no longer linked to this episode")

    if c.layer == "interpretation" and c.authored_by != "user":
        out.append("interpretation_not_user_authored: impact must come from you, not be inferred")

    if c.layer in ("observation", "attribution"):
        if c.status == "completed" and not any(COMPLETION_CUE.search(s.excerpt) for s in pro):
            out.append("no_completion_evidence: status 'completed' needs a completion statement in the source")

    if c.metric_value is not None:
        bearing = [s for s in pro if _has_number(s.excerpt, c.metric_value)]
        if not bearing:
            out.append("metric_not_in_evidence: metric value not found in any cited excerpt")
        else:
            if c.metric_unit and not any(c.metric_unit.lower() in s.excerpt.lower() for s in bearing):
                out.append("metric_unit_not_in_evidence")
            if any(s.record_id != c.metric_scope for s in bearing):
                out.append("metric_scope_mismatch: metric comes from a different record than its scope")
            if c.status == "completed" and any(PLANNING_CUE.search(s.excerpt) for s in bearing):
                out.append("metric_is_target: source states a target/goal, not an achieved result")

    subj = c.subject.strip().lower()
    if c.contribution_role is not None:
        if subj in NON_SELF_SUBJECTS:
            out.append("team_result_claimed_as_self: team-level subject given a personal role")
        if not any(c.contribution_role in s.self_roles for s in pro):
            out.append(f"role_not_supported: no record that you acted as '{c.contribution_role}'")
    if subj == "i" and c.contribution_role is None:
        out.append("first_person_without_role: 'I' claims need a supported contribution role")
    if c.layer == "attribution" and c.contribution_role is None:
        out.append("attribution_without_role")
    return out
