"""Groups leveling-guide experiences into topics, suggests topics for notebook text, and holds growth ideas.

`match` places a guide bullet in a topic (checked in order, first hit wins). `words` suggest a topic for
something the user logged. Suggestions are only ever pre-ticked boxes; the user confirms every link.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    key: str
    name: str
    match: str
    words: str
    skills: tuple[str, ...]
    ideas: tuple[str, ...]


TOPICS = [
    Topic("governance", "Governance and quality gates", r"release governance|quality gates",
          r"quality gates?|governance|compliance|code scan\w*|static (code )?analysis|pmd|sonar\w*|pre-?checks?",
          ("Demonstrate Technical Governance", "Security Governance - DevSecOps"),
          ("Add a quality gate (static analysis, test coverage, or a pre-deploy check) to a real pipeline and note what it caught.",
           "Write down the release approval steps for a project and get the team to agree to them.",
           "Fold governance into a wider release strategy rather than one-off checks.")),
    Topic("tools", "DevOps tools and toolchains", r"devops tools|toolchain",
          r"copado|gearset|devops center|flosum|autorabit|github actions|jenkins|azure devops|toolchains?|tool selection",
          ("CI/CD frameworks & tools",),
          ("Get hands-on with a second, then a third, Salesforce DevOps tool (Copado, Gearset, DevOps Center, Flosum).",
           "Write a short tool comparison for a customer's architecture and security constraints, and recommend one.",
           "Help a team pick and set up a toolchain, and record why you chose it.")),
    Topic("sandbox", "Sandbox and test data strategy", r"sandbox (refresh )?strateg",
          r"sandbox(es)?|refresh(es|ed)?|scratch orgs?|data load\w*|anonymi[sz]\w*|seed data|test data",
          ("Environment/Sandbox Management",),
          ("Document the refresh cycle for a project's sandboxes and automate one step of it.",
           "Automate anonymized data loading after a refresh.",
           "Own the sandbox strategy for a whole engagement, including pre-refresh automation and back promotions.")),
    Topic("poc", "Proofs of concept and accelerators", r"proofs? of concept|pocs?\b|accelerator",
          r"poc|proof of concept|prototype|accelerators?|spike|automation script",
          ("Build and Deploy Technical Capabilities", "Solve Problems Creatively"),
          ("Build a small proof of concept that removes a manual deployment or refresh step.",
           "Turn a proof of concept into a reusable accelerator other teams can pick up.",
           "Share the accelerator with the practice and track who reuses it.")),
    Topic("docs", "Documentation, runbooks, and playbooks", r"documentation|runbooks|playbooks",
          r"docs?|documentation|documented|runbooks?|playbooks?|user guides?|wiki|readme|confluence|quip",
          ("Communicate Effectively",),
          ("Write the deployment and rollback runbook for a project you're on.",
           "Turn it into a reusable playbook another delivery team can follow.",
           "Write customer enablement material that lets their team run releases without you.")),
    Topic("knowledge", "Mentoring and knowledge sharing", r"mentor|knowledge",
          r"mentor\w*|coach\w*|onboard\w*|pair(ed|ing)?|knowledge transfer|kt|training|taught|teach\w*|office hours|brown ?bag",
          ("Collaborate to Drive Success", "Build Trust & Authenticity"),
          ("Mentor a junior engineer on a tool or practice, and note what they can now do alone.",
           "Run a knowledge-share session for the practice, not just your team.",
           "Lead a knowledge transfer and post-handover plan so a customer team is self-sufficient.")),
    Topic("communication", "Communication, demos, and solution reviews", r"demos|communicat|walkthrough",
          r"demo(s|ed)?|present(ed|ation|ations)?|walk ?through|solution reviews?|architecture reviews?|explain\w*|enablement|readout|stakeholders?",
          ("Communicate Effectively", "Design and Deliver Presentations", "Deliver Compelling Stories", "Leadership Presence"),
          ("Explain a DevOps change to a non-technical stakeholder and capture their reaction.",
           "Lead a technical demo or architecture walkthrough with a customer, including the trade-offs you chose.",
           "Present a solution review internally and defend the design rationale.")),
    Topic("vcs", "Version control and branching", r"version control",
          r"git|branch(es|ing)?|merge\w*|pull requests?|prs?|bitbucket|repos?|repository",
          ("Version Control System",),
          ("Design or clean up a branching strategy for a project and write it down.",
           "Set it up across several orgs or workstreams and keep change tracking consistent.")),
    Topic("strategy", "DevOps strategy and assessment", r"devops strategy|devops processes",
          r"strateg\w*|assessment|maturity|roadmap|process review|recommendations?|optimi[sz]\w*",
          ("Technical Strategy - DevOps", "DevOps Assessment", "Apply Strategic Mindset"),
          ("Assess a customer's DevOps maturity and write up three prioritized recommendations.",
           "Own the end-to-end DevOps strategy for an engagement: release automation, environments, and governance.")),
    Topic("pipelines", "CI/CD pipelines", r"ci/cd pipelines",
          r"pipelines?|ci/?cd|ci|build failures?|sfdx|sf cli|unlocked packag\w*|packaging",
          ("CI/CD frameworks & tools", "DevOps"),
          ("Design and maintain a pipeline for a multi-org project with little oversight.",
           "Lead the pipeline design for an engagement using DevOps Center, SFDX, or unlocked packages.")),
    Topic("deploy", "Deployments and releases", r"deploy|release cutover|troubleshoot",
          r"deploy\w*|releases?|cutovers?|rollbacks?|roll back|hotfix\w*|go-?live|metadata api|change sets?",
          ("Release Management", "Take Accountability"),
          ("Write and run a deployment plan with a rollback plan for a critical release.",
           "Troubleshoot and fix a failed build or deployment on your own, and note the root cause.",
           "Manage a release cutover across orgs with minimal downtime.")),
    Topic("initiatives", "Leading initiatives and planning", r"initiative|resource planning|estimation",
          r"initiatives?|led|estimat\w*|scoping|sizing|resource planning|delivery standards?",
          ("Leadership Presence", "Take Accountability", "Drive Results"),
          ("Lead a small internal initiative with one or two other engineers.",
           "Estimate the DevOps effort for an engagement and compare it with what actually happened.",
           "Contribute a reusable asset or delivery standard to the practice framework.")),
]
TOPIC = {t.key: t for t in TOPICS}
OTHER = Topic("other", "Other experiences", "", "", (), ())

SKILL_WORDS = {
    "Agentforce": r"agentforce",
    "Containerization frameworks & tools": r"docker|kubernetes|k8s|containers?",
    "Observability Frameworks and Tools": r"observability|monitoring|dashboards?|splunk|datadog|grafana|alerts?",
    "Integrating Quality Engineering Framework": r"tests?|testing|qa|selenium|apex tests?|code coverage",
    "AI Fluency": r"ai|claude|gemini|cursor|llm|prompts?|copilot",
    "Data-Driven Decision Making": r"metrics?|data-driven|analysis|analy[sz]ed",
    "Engage in Courageous Conversations": r"escalat\w*|pushed back|difficult conversation|conflict",
}


def _rx(words: str) -> re.Pattern:
    return re.compile(rf"(?<![\w/])(?:{words})(?![\w/])", re.I)


_TOPIC_RX = [(t, _rx(t.words)) for t in TOPICS]
_SKILL_RX = {name: _rx(w) for name, w in SKILL_WORDS.items()}


def topic_of(experience: str) -> Topic:
    return next((t for t in TOPICS if re.search(t.match, experience, re.I)), OTHER)


def suggest(text: str) -> tuple[list[Topic], set[str]]:
    """Topics and skill names that a piece of the user's text seems to relate to."""
    topics = [t for t, rx in _TOPIC_RX if rx.search(text)]
    skills = {s for t in topics for s in t.skills} | {n for n, rx in _SKILL_RX.items() if rx.search(text)}
    return topics, skills
