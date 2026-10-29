#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end tests for StopFailure hook recovery; no real API calls."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "bin", "429-wait-hook.py")
PY = sys.executable or "python"


class ProbeServer:
    def __init__(self, fail_first=0, gate=None):
        self.fail_first = fail_first
        self.gate = gate
        self.calls = 0
        self.lock = threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                with outer.lock:
                    outer.calls += 1
                    call = outer.calls
                if outer.gate is not None:
                    outer.gate.wait(15)
                code = 429 if call <= outer.fail_first else 200
                payload = ({"error": {"type": "rate_limit_error", "message": "limited"}}
                           if code == 429 else {"content": [{"type": "text", "text": "ok"}]})
                raw = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def write_mock_claude(workdir):
    script = os.path.join(workdir, "mock_claude.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(r'''import json, os, subprocess, sys
args = sys.argv[1:]
old = args[args.index("--resume") + 1]
new = "forked-" + old
with open(os.path.join(os.environ["MOCK_CLAUDE_STATE"], "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"args": args, "cwd": os.getcwd(), "old": old}) + "\n")
if old == "handoff-source":
    payload = {
        "session_id": new,
        "transcript_path": "",
        "cwd": os.getcwd(),
        "hook_event_name": "StopFailure",
        "error": "rate_limit",
        "last_assistant_message": "API Error: Request rejected (429)",
    }
    subprocess.run(json.loads(os.environ["MOCK_HOOK_COMMAND"]),
                   input=json.dumps(payload), text=True, check=True)
    print(json.dumps({"session_id": new, "is_error": True,
                      "api_error_status": 429, "result": "API Error: 429"}))
    sys.exit(1)
print(json.dumps({"session_id": new, "is_error": False, "result": "ok"}))
''')
    if os.name == "nt":
        command = os.path.join(workdir, "mock-claude.cmd")
        with open(command, "w", encoding="ascii") as f:
            f.write('@echo off\r\n"%s" "%s" %%*\r\n' % (PY, script))
    else:
        command = os.path.join(workdir, "mock-claude")
        with open(command, "w", encoding="utf-8") as f:
            f.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (PY, script))
        os.chmod(command, 0o755)
    return command


def wait_for(paths, timeout=25):
    if isinstance(paths, str):
        paths = [paths]
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(os.path.exists(p) and os.path.getsize(p) > 0 for p in paths):
            return True
        time.sleep(0.1)
    return False


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def recovery_calls(state_dir):
    path = os.path.join(state_dir, "calls.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class Harness:
    def __init__(self, fail_first=0, gate=None):
        self.workdir = tempfile.mkdtemp(prefix="429-hook-test-")
        self.state = os.path.join(self.workdir, "state")
        self.config = os.path.join(self.workdir, "config")
        self.cwd = os.path.join(self.workdir, "project")
        os.makedirs(self.state)
        os.makedirs(self.config)
        os.makedirs(self.cwd)
        self.server = ProbeServer(fail_first, gate)
        with open(os.path.join(self.config, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"env": {"ANTHROPIC_BASE_URL": self.server.url,
                               "ANTHROPIC_API_KEY": "test-key",
                               "ANTHROPIC_MODEL": "test-model"}}, f)
        self.claude = write_mock_claude(self.workdir)
        self.env = os.environ.copy()
        self.env.update({"HOME": self.workdir, "USERPROFILE": self.workdir,
                         "CLAUDE_CONFIG_DIR": self.config,
                         "MOCK_CLAUDE_STATE": self.state,
                         "NO_PROXY": "127.0.0.1,localhost"})
        self.hook_command = [PY, HOOK, "--state-dir", self.state,
                             "--claude-command", self.claude,
                             "--interval", "1", "--max-attempts", "10"]
        self.env["MOCK_HOOK_COMMAND"] = json.dumps(self.hook_command)

    def close(self):
        self.server.close()

    def hook(self, session_id, error="rate_limit", message="API Error: 429"):
        payload = {"session_id": session_id, "transcript_path": "",
                   "cwd": self.cwd, "hook_event_name": "StopFailure",
                   "error": error, "last_assistant_message": message}
        return subprocess.run(self.hook_command, input=json.dumps(payload), text=True,
                              env=self.env, capture_output=True, timeout=10)

    def result_path(self, session_id):
        return os.path.join(self.state, "nanny-claude-%s.result.json" % session_id)


def test_filter_and_recovery():
    h = Harness(fail_first=2)
    try:
        assert h.hook("ignored", error="authentication_error").returncode == 0
        subprocess.run(h.hook_command, input="not-json", text=True, env=h.env,
                       capture_output=True, timeout=10)
        assert not os.path.exists(h.result_path("ignored"))
        assert h.hook("session-A").returncode == 0
        assert wait_for(h.result_path("session-A")), "recovery result missing"
        result = read_json(h.result_path("session-A"))
        calls = recovery_calls(h.state)
        assert result["status"] == "completed"
        assert result["session_id"] == "forked-session-A"
        assert len(calls) == 1
        assert calls[0]["cwd"] == h.cwd
        assert "--fork-session" in calls[0]["args"]
        assert "--continue" not in calls[0]["args"]
        assert h.server.calls == 3
    finally:
        h.close()


def test_duplicate_hook():
    gate = threading.Event()
    h = Harness(gate=gate)
    try:
        assert h.hook("duplicate").returncode == 0
        pid_path = os.path.join(h.state, "nanny-claude-duplicate.pid")
        assert wait_for(pid_path), "daemon did not start"
        assert h.hook("duplicate").returncode == 0
        time.sleep(0.5)
        assert h.server.calls == 1, "duplicate daemon probed the endpoint"
        gate.set()
        assert wait_for(h.result_path("duplicate")), "recovery did not finish"
        assert len(recovery_calls(h.state)) == 1, "duplicate recovery"
    finally:
        gate.set()
        h.close()


def test_two_sessions():
    h = Harness()
    try:
        h.hook("session-A")
        h.hook("session-B")
        assert wait_for([h.result_path("session-A"), h.result_path("session-B")])
        a = read_json(h.result_path("session-A"))
        b = read_json(h.result_path("session-B"))
        assert a["session_id"] == "forked-session-A"
        assert b["session_id"] == "forked-session-B"
        assert len(recovery_calls(h.state)) == 2
    finally:
        h.close()


def test_second_429_handoff():
    h = Harness()
    try:
        h.hook("handoff-source")
        assert wait_for([h.result_path("handoff-source"),
                         h.result_path("forked-handoff-source")])
        parent = read_json(h.result_path("handoff-source"))
        child = read_json(h.result_path("forked-handoff-source"))
        assert parent["status"] == "handed_off"
        assert child["status"] == "completed"
        assert len(recovery_calls(h.state)) == 2
    finally:
        h.close()


def main():
    tests = [test_filter_and_recovery, test_duplicate_hook,
             test_two_sessions, test_second_429_handoff]
    failed = 0
    for test in tests:
        try:
            test()
            print("PASS  " + test.__name__)
        except Exception as exc:
            failed += 1
            print("FAIL  %s: %s" % (test.__name__, exc))
    print("--- result: %s ---" % ("PASS" if not failed else "%d FAILED" % failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
