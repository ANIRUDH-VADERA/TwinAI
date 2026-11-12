import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from twinai.bm25 import BM25
from twinai.config import TwinConfig
from twinai.daemon import make_server
from twinai.dedup import BloomFilter, Deduplicator
from twinai.events import Event
from twinai.router import route
from twinai.sanitize import sanitize
from twinai.sessions import detect_domains, sessionize
from twinai.twin import Twin

NOW = datetime.now(timezone.utc)


def ev(source, content, minutes_ago=60, **meta):
    return Event(source, content, (NOW - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds"), meta)


class SanitizerTests(unittest.TestCase):
    def test_redacts_common_secrets(self):
        text = ("export DB_PASSWORD=hunter2 token=abc123 key AKIAABCDEFGHIJKLMNOP "
                "ghp_" + "a" * 36 + " mail me at a.b@corp.com psql postgres://user:pw@db:5432/app")
        clean, counts = sanitize(text)
        for secret in ("hunter2", "abc123", "AKIAABCDEFGHIJKLMNOP", "ghp_", "a.b@corp.com", "user:pw@"):
            self.assertNotIn(secret, clean)
        self.assertEqual(counts["email"], 1)
        self.assertIn("DB_PASSWORD=[REDACTED]", clean)

    def test_leaves_ordinary_text_alone(self):
        text = "kubectl rollout undo deployment/api -n payments"
        self.assertEqual(sanitize(text), (text, {}))


class DedupTests(unittest.TestCase):
    def test_bloom_filter_has_no_false_negatives(self):
        bf = BloomFilter(capacity=1000)
        items = [f"item-{i}" for i in range(500)]
        self.assertFalse(any(bf.add(i) for i in items))
        self.assertTrue(all(bf.add(i) for i in items))

    def test_near_duplicates_are_dropped(self):
        d = Deduplicator(threshold=0.6)
        self.assertFalse(d.is_duplicate("ide", "commit offsets only after the batch is written to postgres"))
        self.assertTrue(d.is_duplicate("ide", "commit offsets only after the batch is written to postgres!"))
        self.assertFalse(d.is_duplicate("ide", "helm rollback restores the previous release"))


class SessionTests(unittest.TestCase):
    def test_gap_splits_sessions_and_domains_are_tagged(self):
        events = [ev("terminal", "kubectl get pods", 200), ev("terminal", "helm list", 195),
                  ev("terminal", "psql -h db", 10)]
        sessions = sessionize(events)
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sessions[0].domains, {"kubernetes"})
        self.assertEqual(sessions[1].domains, {"postgres"})

    def test_detect_domains(self):
        self.assertEqual(detect_domains("kafka consumer lag on topic orders"), {"kafka"})


class BM25Tests(unittest.TestCase):
    def test_ranks_relevant_document_first(self):
        bm = BM25(["kafka consumer lag partition", "postgres copy unlogged table", "helm rollback release"])
        self.assertEqual(bm.top("why is consumer lag high")[0][0], 0)
        self.assertEqual(bm.top("unrelated words entirely"), [])


class TwinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        TwinConfig(owner="alice").save(self.root)
        self.twin = Twin(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_consent_blocks_disabled_sources(self):
        report = self.twin.ingest([ev("browser", "reading kafka docs"), ev("terminal", "kcat -L")])
        self.assertEqual((report.accepted, report.blocked_source), (1, 1))

    def test_secrets_never_reach_disk(self):
        self.twin.ingest([ev("terminal", "export API_KEY=sk-live-123 && kubectl apply -f x.yaml")])
        on_disk = "".join(p.read_text() for p in self.root.rglob("*") if p.is_file() and p.suffix in {".md", ".ndjson"})
        self.assertNotIn("sk-live-123", on_disk)

    def test_answers_with_citations_and_logs_gaps(self):
        self.twin.ingest([
            ev("runbook", "Kafka consumer lag: describe the consumer group, then check the hottest partition.", 30),
            ev("terminal", "kafka-consumer-groups --describe --group orders", 29),
            ev("pr_review", "Commit kafka offsets only after the postgres write succeeds.", 28),
        ])
        a = self.twin.ask("how do I debug kafka consumer lag?")
        self.assertIn(a.status, {"answered", "caveat"})
        self.assertTrue(a.citations)
        self.assertIn("kafka", a.domains)

        gap = self.twin.ask("what is the office wifi password?")
        self.assertEqual(gap.status, "gap")
        self.assertIn("wifi", (self.root / "logs" / "gaps.ndjson").read_text())

    def test_graph_links_domains_used_together(self):
        self.twin.ingest([ev("terminal", "kcat -C -t orders", 5), ev("terminal", "psql -c 'select 1'", 4)])
        self.assertEqual(self.twin.kb.graph(), {"kafka|postgres": 1})
        self.assertEqual(self.twin.kb.neighbors("kafka"), {"postgres": 1.0})


class RouterTests(unittest.TestCase):
    def test_prefers_expert_and_out_of_office_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            twins = []
            for owner, n in (("alice", 1), ("bob", 6)):
                root = Path(tmp, owner)
                TwinConfig(owner=owner).save(root)
                t = Twin(root)
                t.ingest([ev("terminal", f"kubectl rollout undo deployment/api-{i}", 10 + i) for i in range(n)]
                         + [ev("terminal", "psql -h db", 300)])
                twins.append(t)
            routes = route("how to roll back a kubernetes deployment", twins, {"bob": "ooo"})
            self.assertEqual(routes[0].owner, "bob")
            self.assertGreater(routes[0].score, routes[1].score)


class DaemonTests(unittest.TestCase):
    def test_capture_requires_token_and_query_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = TwinConfig(owner="alice")
            cfg.save(root)
            server = make_server(Twin(root), port=0)
            port = server.server_address[1]
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                def post(path, body, token=None):
                    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", json.dumps(body).encode(), method="POST",
                                                 headers={"content-type": "application/json", **({"x-twinai-token": token} if token else {})})
                    with urllib.request.urlopen(req) as r:
                        return r.status, json.loads(r.read())

                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    post("/capture", {"source": "terminal", "content": "kcat -L"})
                self.assertEqual(ctx.exception.code, 401)
                ctx.exception.close()

                status, body = post("/capture", {"source": "terminal", "content": "kcat -C -t orders"}, cfg.token)
                self.assertEqual((status, body["accepted"]), (202, 1))
                status, body = post("/query", {"question": "kcat orders topic"}, cfg.token)
                self.assertEqual(status, 200)
                self.assertIn("kcat", body["answer"])
            finally:
                server.shutdown()


if __name__ == "__main__":
    unittest.main()
