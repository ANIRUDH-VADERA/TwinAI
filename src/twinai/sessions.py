"""Groups events into work sessions and tags each session with the domains it touched."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

from .events import Event

# Signals that map raw activity to a knowledge domain. Extend freely.
DOMAIN_SIGNALS: dict[str, list[str]] = {
    "kubernetes": ["kubectl", "helm", "k8s", "pod", "deployment", "namespace", "kustomize"],
    "kafka": ["kafka", "consumer lag", "topic", "partition", "offset", "kcat"],
    "postgres": ["psql", "postgres", "pg_", "vacuum", "copy ", "unlogged", "wal"],
    "spark": ["spark", "pyspark", "dataframe", "executor", "shuffle"],
    "git": ["git rebase", "git merge", "git cherry-pick", "pull request", "merge conflict"],
    "docker": ["docker", "dockerfile", "container image"],
    "gcp": ["gcloud", "gsutil", "bigquery", "pubsub", "gcs", "storage transfer"],
    "terraform": ["terraform", "tfstate", ".tf"],
    "incident-response": ["incident", "pagerduty", "rollback", "postmortem", "sev1", "p0", "outage"],
    "python": ["python", "pip install", "pytest", "venv", ".py"],
    "scala": ["sbt", "scala", "zio", "akka"],
}
_SIGNAL_RES = {d: re.compile("|".join(re.escape(s) for s in sigs), re.I) for d, sigs in DOMAIN_SIGNALS.items()}


def detect_domains(text: str) -> set[str]:
    return {d for d, rx in _SIGNAL_RES.items() if rx.search(text)}


@dataclass
class Session:
    events: list[Event] = field(default_factory=list)
    domains: set[str] = field(default_factory=set)

    @property
    def start(self):
        return self.events[0].time

    @property
    def end(self):
        return self.events[-1].time


def sessionize(events: list[Event], gap: timedelta = timedelta(minutes=20)) -> list[Session]:
    sessions: list[Session] = []
    for e in sorted(events, key=lambda x: x.ts):
        if not sessions or e.time - sessions[-1].end > gap:
            sessions.append(Session())
        sessions[-1].events.append(e)
        sessions[-1].domains |= detect_domains(e.content)
    return sessions
