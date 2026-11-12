"""A twin = one owner's knowledge base plus the pipeline that feeds it and the engine that answers from it."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .bm25 import BM25, tokenize
from .config import TwinConfig
from .dedup import Deduplicator
from .events import SOURCE_QUALITY, Event
from .kb import KnowledgeBase, Passage
from .sanitize import sanitize
from .sessions import sessionize

ANSWER_AT = 0.75
CAVEAT_AT = 0.50
RECENCY_HALF_LIFE_DAYS = 120


@dataclass
class IngestReport:
    accepted: int = 0
    duplicates: int = 0
    blocked_source: int = 0
    redactions: dict[str, int] = field(default_factory=dict)


@dataclass
class Answer:
    question: str
    status: str  # answered | caveat | gap
    confidence: float
    text: str
    citations: list[Passage]
    domains: list[str]
    breakdown: dict[str, float]


class Twin:
    def __init__(self, root: Path, config: TwinConfig | None = None) -> None:
        self.root = root
        self.config = config or TwinConfig.load(root)
        self.kb = KnowledgeBase(root)
        self.dedup = Deduplicator()

    # ---- capture pipeline: consent -> sanitize -> dedupe -> store -> sessionize -> knowledge ----
    def ingest(self, events: list[Event]) -> IngestReport:
        report = IngestReport()
        kept: list[Event] = []
        for e in events:
            if e.source not in self.config.enabled_sources:
                report.blocked_source += 1
                continue
            clean, counts = sanitize(e.content)
            for k, v in counts.items():
                report.redactions[k] = report.redactions.get(k, 0) + v
            if self.dedup.is_duplicate(e.source, clean):
                report.duplicates += 1
                continue
            kept.append(Event(e.source, clean, e.ts, e.meta))
        if kept:
            self.kb.append_raw(kept)
            for session in sessionize(kept):
                self.kb.add_session(session)
            if self.config.git_autocommit:
                self.kb.commit(f"twin-update: {len(kept)} events")
        report.accepted = len(kept)
        return report

    # ---- query engine: BM25 -> graph expansion -> scoring -> answer ----
    def ask(self, question: str, k: int = 5, now: datetime | None = None, log: bool = True) -> Answer:
        now = now or datetime.now(timezone.utc)
        passages = self.kb.passages()
        if not passages:
            return self._gap(question, log)
        bm25 = BM25([f"{p.domain} {p.text}" for p in passages])
        raw = bm25.scores(question)
        if max(raw) <= 0:
            return self._gap(question, log)

        # The strongest domain plus its graph neighbours get a boost, so related context surfaces too.
        best_domain = passages[max(range(len(raw)), key=raw.__getitem__)].domain
        boost = {best_domain: 1.0, **{d: 0.5 * w for d, w in self.kb.neighbors(best_domain).items()}}
        ranked = sorted(((s * (1 + 0.25 * boost.get(p.domain, 0)), p) for s, p in zip(raw, passages, strict=True) if s > 0),
                        key=lambda x: x[0], reverse=True)
        # The same fact can sit on several domain pages; cite it once.
        scored, seen = [], set()
        for s, p in ranked:
            if p.text not in seen:
                seen.add(p.text)
                scored.append((s, p))
        scored = scored[:k]
        top = [p for _, p in scored]

        quality = sum(SOURCE_QUALITY.get(p.source, 0.3) for p in top) / len(top)
        newest = max(datetime.fromisoformat(p.ts) for p in top)
        recency = math.pow(0.5, max(0, (now - newest).days) / RECENCY_HALF_LIFE_DAYS)
        expertise = self.kb.expertise(best_domain, now)
        corroboration = min(1.0, (len({p.source for p in top}) - 1) / 2)
        # Share of the question's terms found in the cited passages, so a one-word match never looks confident.
        q_terms = set(tokenize(question))
        covered = q_terms & {t for p in top for t in tokenize(f"{p.domain} {p.text}")}
        relevance = len(covered) / len(q_terms) if q_terms else 0.0
        breakdown = {"source_quality": quality, "recency": recency, "expertise": expertise,
                     "corroboration": corroboration, "relevance": relevance}
        confidence = round((0.4 * quality + 0.3 * recency + 0.2 * expertise + 0.1 * corroboration) * relevance, 3)

        status = "answered" if confidence >= ANSWER_AT else "caveat" if confidence >= CAVEAT_AT else "gap"
        if status == "gap":
            return self._gap(question, log, confidence, breakdown)
        lead = f"From {self.config.owner}'s work" + ("" if status == "answered" else f" (low confidence: confirm with {self.config.owner})")
        text = lead + ":\n" + "\n".join(f"- {p.text}  [{p.source}, {p.ts[:10]}]" for p in top)
        answer = Answer(question, status, confidence, text, top, sorted({p.domain for p in top}), breakdown)
        if log:
            self.kb.log("queries", {"question": question, "status": status, "confidence": confidence})
        return answer

    def _gap(self, question: str, log: bool, confidence: float = 0.0, breakdown: dict | None = None) -> Answer:
        if log:
            self.kb.log("gaps", {"question": question, "confidence": confidence})
        text = f"{self.config.owner}'s twin doesn't know this yet. The question was logged as a knowledge gap."
        return Answer(question, "gap", confidence, text, [], [], breakdown or {})
