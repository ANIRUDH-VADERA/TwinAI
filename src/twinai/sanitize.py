"""Redacts secrets and personal data before anything is stored. Runs on every event."""
from __future__ import annotations

import re

RULES: list[tuple[str, re.Pattern[str]]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack_token", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("bearer", re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("assignment", re.compile(r"(?i)\b([a-z0-9_]*(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|token))\s*[=:]\s*\S+")),
    ("url_credentials", re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@/]+@")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("card_number", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("aadhaar", re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")),
    ("pan", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
]


def sanitize(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for name, pattern in RULES:
        def repl(m: re.Match[str], name: str = name) -> str:
            counts[name] = counts.get(name, 0) + 1
            if name == "assignment":
                return f"{m.group(1)}=[REDACTED]"
            if name == "url_credentials":
                return f"{m.group(1)}[REDACTED]@"
            return f"[REDACTED:{name}]"
        text = pattern.sub(repl, text)
    return text, counts
