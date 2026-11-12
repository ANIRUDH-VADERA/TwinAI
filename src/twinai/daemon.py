"""Local capture daemon. Listens on 127.0.0.1 only and requires the per-install token on every write."""
from __future__ import annotations

import hmac
import json
import threading
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .events import Event
from .twin import Twin

MAX_BODY = 64 * 1024


def make_server(twin: Twin, port: int = 7331) -> ThreadingHTTPServer:
    lock = threading.Lock()  # the knowledge base is plain files; serialize writers

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # keep captured content out of stdout
            pass

        def _send(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            return hmac.compare_digest(self.headers.get("x-twinai-token", ""), twin.config.token)

        def _json(self) -> dict:
            length = int(self.headers.get("content-length", 0))
            if length > MAX_BODY:
                raise ValueError("body too large")
            return json.loads(self.rfile.read(length) or b"{}")

        def do_GET(self) -> None:
            if self.path == "/health":
                return self._send(200, {"status": "ok", "owner": twin.config.owner,
                                        "sources": twin.config.enabled_sources,
                                        "passages": len(twin.kb.passages())})
            self._send(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authorized():
                return self._send(401, {"error": "missing or wrong x-twinai-token"})
            try:
                body = self._json()
                if self.path == "/capture":
                    events = [Event.from_dict(e) for e in (body if isinstance(body, list) else [body])]
                    with lock:
                        return self._send(202, asdict(twin.ingest(events)))
                if self.path == "/query":
                    q = str(body.get("question", ""))[:1000]
                    with lock:
                        a = twin.ask(q)
                    return self._send(200, {"status": a.status, "confidence": a.confidence, "answer": a.text,
                                            "domains": a.domains, "breakdown": a.breakdown})
            except (ValueError, json.JSONDecodeError) as err:
                return self._send(400, {"error": str(err)})
            self._send(404, {"error": "not found"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
