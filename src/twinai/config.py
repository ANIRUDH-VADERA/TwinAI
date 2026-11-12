from __future__ import annotations

import json
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Sources that can carry personal or third-party content stay off until the owner opts in.
DEFAULT_SOURCES = ["terminal", "ide", "pr_review", "runbook"]
OPT_IN_SOURCES = ["browser", "chat", "llm_chat"]


@dataclass
class TwinConfig:
    owner: str
    enabled_sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    git_autocommit: bool = False

    @staticmethod
    def path(root: Path) -> Path:
        return root / "config.json"

    def save(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True)
        p = self.path(root)
        p.write_text(json.dumps(asdict(self), indent=2))
        p.chmod(0o600)  # holds the capture token

    @classmethod
    def load(cls, root: Path) -> TwinConfig:
        return cls(**json.loads(cls.path(root).read_text()))
