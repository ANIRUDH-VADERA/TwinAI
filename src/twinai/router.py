"""Routes a question to the teammate whose twin is most likely to answer it."""
from __future__ import annotations

from dataclasses import dataclass

from .bm25 import BM25
from .twin import Twin

# A twin is most useful exactly when its owner can't answer, so out-of-office scores highest.
AVAILABILITY_BONUS = {"ooo": 1.0, "busy": 0.6, "available": 0.3}


@dataclass
class Route:
    owner: str
    score: float
    domain: str | None
    expertise: float
    availability: str


def route(question: str, twins: list[Twin], availability: dict[str, str] | None = None) -> list[Route]:
    availability = availability or {}
    routes = []
    for twin in twins:
        passages = twin.kb.passages()
        domain, expertise = None, 0.0
        if passages:
            scores = BM25([f"{p.domain} {p.text}" for p in passages]).scores(question)
            best = max(range(len(scores)), key=scores.__getitem__)
            if scores[best] > 0:
                domain = passages[best].domain
                expertise = twin.kb.expertise(domain)
        status = availability.get(twin.config.owner, "available")
        score = 0.7 * expertise + 0.3 * AVAILABILITY_BONUS.get(status, 0.3) if domain else 0.0
        routes.append(Route(twin.config.owner, round(score, 3), domain, round(expertise, 3), status))
    return sorted(routes, key=lambda r: r.score, reverse=True)
