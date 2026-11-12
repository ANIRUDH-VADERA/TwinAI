from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from importlib import resources
from pathlib import Path

from .config import TwinConfig
from .daemon import make_server
from .events import Event
from .router import route
from .twin import Twin

DEFAULT_ROOT = Path.home() / ".twinai"


def load_events(path: Path) -> list[Event]:
    return [Event.from_dict(json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def print_answer(a) -> None:
    print(f"\nQ: {a.question}\n[{a.status} | confidence {a.confidence:.2f}]")
    print(a.text)
    if a.breakdown:
        print("   score parts:", ", ".join(f"{k}={v:.2f}" for k, v in a.breakdown.items()))


def cmd_init(args) -> int:
    root = Path(args.root)
    TwinConfig(owner=args.owner).save(root)
    print(f"Created twin for {args.owner} at {root}. Capture token is in {TwinConfig.path(root)}")
    return 0


def cmd_ingest(args) -> int:
    twin = Twin(Path(args.root))
    print(twin.ingest(load_events(Path(args.file))))
    return 0


def cmd_ask(args) -> int:
    print_answer(Twin(Path(args.root)).ask(args.question))
    return 0


def cmd_serve(args) -> int:
    server = make_server(Twin(Path(args.root)), args.port)
    print(f"TwinAI daemon on http://127.0.0.1:{args.port} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def cmd_demo(_args) -> int:
    sample = resources.files("twinai").joinpath("data/sample_events.ndjson")
    with tempfile.TemporaryDirectory() as tmp:
        alice_root, bob_root = Path(tmp, "alice"), Path(tmp, "bob")
        TwinConfig(owner="alice").save(alice_root)
        TwinConfig(owner="bob", enabled_sources=["terminal", "ide", "pr_review", "runbook", "chat"]).save(bob_root)
        events = [Event.from_dict(json.loads(line)) for line in sample.read_text().splitlines() if line.strip()]
        # Shift the sample so its newest event happened yesterday; recency is part of the confidence score.
        shift = datetime.now(UTC) - timedelta(days=1) - max(e.time for e in events)
        events = [Event(e.source, e.content, (e.time + shift).isoformat(timespec="seconds"), e.meta) for e in events]
        alice, bob = Twin(alice_root), Twin(bob_root)
        print("alice ingest:", alice.ingest([e for e in events if e.meta.get("owner") == "alice"]))
        print("bob ingest:  ", bob.ingest([e for e in events if e.meta.get("owner") == "bob"]))
        print("\nalice knowledge pages:", sorted(p.stem for p in (alice_root / "knowledge").glob("*.md")))
        print("alice graph:", alice.kb.graph())

        for q in ["how do I check kafka consumer lag for the orders topic?",
                  "why was the postgres upsert slow and how was it fixed?",
                  "what is our holiday policy?"]:
            print_answer(alice.ask(q))

        q = "how do I roll back a bad kubernetes deployment?"
        print(f"\nRouting: {q}")
        for r in route(q, [alice, bob], {"bob": "ooo"}):
            print(f"  {r.owner:<6} score={r.score:.2f} domain={r.domain} expertise={r.expertise:.2f} ({r.availability})")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="twinai")
    p.add_argument("--root", default=str(DEFAULT_ROOT), help="knowledge base directory")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init")
    s.add_argument("--owner", required=True)
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("ingest")
    s.add_argument("file")
    s.set_defaults(fn=cmd_ingest)
    s = sub.add_parser("ask")
    s.add_argument("question")
    s.set_defaults(fn=cmd_ask)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=7331)
    s.set_defaults(fn=cmd_serve)
    sub.add_parser("demo").set_defaults(fn=cmd_demo)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
