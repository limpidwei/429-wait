#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-end test for bin/429-wait.py - never touches a real API.

A local mock endpoint answers 429 for the first N probes, then 200. The test
asserts the nanny logs STILL LIMITED, writes nanny-<tag>.ok, and runs
--on-recover exactly once after recovery.

  python tests/py-e2e.py           # exit 0 = pass
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

FAILS_BEFORE_OK = 2
HERE = os.path.dirname(os.path.abspath(__file__))
NANNY = os.path.join(HERE, "..", "bin", "429-wait.py")
PY = sys.executable or "python"

state = {"calls": 0, "limited": 0, "ok": 0}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        state["calls"] += 1
        # a relay that meters by declared max_tokens
        if body.get("max_tokens", 0) < 64:
            state["ok"] += 1
            self._send(200, {"content": [{"type": "text", "text": "hi"}]})
            return
        if state["calls"] <= FAILS_BEFORE_OK:
            state["limited"] += 1
            self._send(429, {"type": "error", "error": {"type": "rate_limit_error",
                                                        "message": "hit usage limit"}})
            return
        state["ok"] += 1
        self._send(200, {"content": [{"type": "text", "text": "hi"}]})

    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):  # keep test output clean
        pass


def main():
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    workdir = tempfile.mkdtemp(prefix="nanny-py-test-")
    marker = os.path.join(workdir, "resumed.txt")
    on_recover = '"%s" -c "open(r\'%s\',\'w\').write(\'ok\')"' % (PY, marker.replace("\\", "\\\\"))

    cmd = [
        PY, NANNY,
        "--base-url", "http://127.0.0.1:%d" % port,
        "--api-key", "test-key",
        "--model", "test-model",
        "--interval", "1",
        "--max-attempts", "6",
        "--tag", "e2e",
        "--state-dir", workdir,
        "--on-recover", on_recover,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    srv.shutdown()

    log_path = os.path.join(workdir, "nanny-e2e.log")
    ok_path = os.path.join(workdir, "nanny-e2e.ok")
    log = open(log_path, encoding="utf-8").read() if os.path.exists(log_path) else ""

    checks = [
        ("exit code 0", proc.returncode == 0),
        ("saw STILL LIMITED", "STILL LIMITED" in log),
        ("saw RECOVERED", "RECOVERED" in log),
        ("ok file written", os.path.exists(ok_path)),
        ("on-recover ran exactly once", os.path.exists(marker)),
        ("probe count == 3", state["calls"] == FAILS_BEFORE_OK + 1),
        ("limited count == 2", state["limited"] == FAILS_BEFORE_OK),
        ("pid file cleaned up", not os.path.exists(os.path.join(workdir, "nanny-e2e.pid"))),
    ]

    print("--- nanny log ---")
    print(log.strip() or "(empty)")
    print("--- checks ---")
    failed = 0
    for name, ok in checks:
        print(("PASS  " if ok else "FAIL  ") + name)
        failed += 0 if ok else 1
    print("--- result: %s ---" % ("PASS" if failed == 0 else "%d FAILED" % failed))
    if failed:
        print(proc.stdout)
        print(proc.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
