"""The on-disk knowledge base: plain Markdown and JSON, so it can live in a private Git repo you own.

    <root>/
      config.json              owner, enabled sources, capture token
      events/raw.ndjson        append-only, already-sanitized events
      knowledge/<domain>.md    one page per domain, every line cited
      graph/relations.json     domain co-occurrence weights
      profile.json             expertise score per domain
      logs/queries.ndjson      every question the twin answered
      logs/gaps.ndjson         questions it could not answer
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

from .events import Event, now_iso
from .sessions import Session, detect_domains

LINE_RE = re.compile(r"^- (?P<text>.+) _\((?P<source>[a-z_]+), (?P<ts>[0-9T:+\-]+)\)_$")
EXPERTISE_HALF_LIFE_DAYS = 90


@dataclass
class Passage:
    domain: str
    text: str
    source: str
    ts: str


def summarize_event(e: Event) -> str:
    """One line per event. Terminal commands keep their exact text; prose is trimmed at a sentence boundary."""
    text = " ".join(e.content.split())
    if e.source == "terminal":
        status = e.meta.get("exit_code")
        suffix = "" if status in (None, 0, "0") else f" (exit {status})"
        return f"`{text[:200]}`{suffix}"
    if len(text) <= 400:
        return text
    cut = text[:400]
    return cut[: cut.rfind(". ") + 1] or cut


class KnowledgeBase:
    def __init__(self, root: Path) -> None:
        self.root = root
        for d in ("events", "knowledge", "graph", "logs"):
            (root / d).mkdir(parents=True, exist_ok=True)

    # ---- writes -------------------------------------------------------------
    def append_raw(self, events: list[Event]) -> None:
        with (self.root / "events" / "raw.ndjson").open("a") as f:
            for e in events:
                f.write(json.dumps(e.to_dict()) + "\n")

    def add_session(self, session: Session) -> None:
        for domain in session.domains:
            lines = [f"- {summarize_event(e)} _({e.source}, {e.ts})_" for e in session.events if domain in detect_domains(e.content)]
            if lines:
                page = self.root / "knowledge" / f"{domain}.md"
                existing = page.read_text() if page.exists() else f"# {domain}\n\n"
                page.write_text(existing + "\n".join(lines) + "\n")
        self._update_graph(session.domains)
        self._update_expertise(session)

    def _update_graph(self, domains: set[str]) -> None:
        graph = self.graph()
        for a, b in combinations(sorted(domains), 2):
            graph[f"{a}|{b}"] = graph.get(f"{a}|{b}", 0) + 1
        (self.root / "graph" / "relations.json").write_text(json.dumps(graph, indent=1, sort_keys=True))

    def _update_expertise(self, session: Session) -> None:
        profile = self.profile()
        for domain in session.domains:
            hits = sum(1 for e in session.events if domain in detect_domains(e.content))
            entry = profile["expertise"].setdefault(domain, {"score": 0, "last": session.end.isoformat()})
            entry["score"] += hits
            entry["last"] = max(entry["last"], session.end.isoformat())
        (self.root / "profile.json").write_text(json.dumps(profile, indent=1, sort_keys=True))

    def log(self, name: str, record: dict) -> None:
        with (self.root / "logs" / f"{name}.ndjson").open("a") as f:
            f.write(json.dumps({"ts": now_iso(), **record}) + "\n")

    def commit(self, message: str) -> None:
        """Commits the knowledge base if it is a Git repo. Push is left to the owner."""
        if (self.root / ".git").exists():
            subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(self.root), "commit", "-q", "-m", message], check=False)

    # ---- reads --------------------------------------------------------------
    def graph(self) -> dict[str, int]:
        p = self.root / "graph" / "relations.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def neighbors(self, domain: str) -> dict[str, float]:
        """Neighbouring domains with weights normalised to 0..1."""
        out: dict[str, int] = {}
        for key, w in self.graph().items():
            a, b = key.split("|")
            if domain in (a, b):
                out[b if a == domain else a] = w
        top = max(out.values(), default=1)
        return {d: w / top for d, w in out.items()}

    def profile(self) -> dict:
        p = self.root / "profile.json"
        return json.loads(p.read_text()) if p.exists() else {"expertise": {}}

    def expertise(self, domain: str, now: datetime | None = None) -> float:
        """0..1: activity relative to the owner's strongest domain, halved every 90 days without activity."""
        scores = self.profile()["expertise"]
        if domain not in scores:
            return 0.0
        top = max(s["score"] for s in scores.values())
        days = ((now or datetime.now(UTC)) - datetime.fromisoformat(scores[domain]["last"])).days
        return scores[domain]["score"] / top * math.pow(0.5, max(0, days) / EXPERTISE_HALF_LIFE_DAYS)

    def passages(self) -> list[Passage]:
        out = []
        for page in sorted((self.root / "knowledge").glob("*.md")):
            for line in page.read_text().splitlines():
                if m := LINE_RE.match(line):
                    out.append(Passage(page.stem, m["text"], m["source"], m["ts"]))
        return out
