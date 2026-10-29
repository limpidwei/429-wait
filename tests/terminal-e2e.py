#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Terminal supervisor state-machine tests; no real Claude or API calls."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
TERMINAL = os.path.join(HERE, "..", "bin", "429-wait-terminal.py")
HOOK = os.path.join(HERE, "..", "bin", "429-wait-hook.py")
DAEMON = os.path.join(HERE, "..", "bin", "429-wait.py")
PY = sys.executable or "python"


class ProbeServer:
    def __init__(self, fail_first=0, gate=None, always_limited=False):
        self.fail_first = fail_first
        self.gate = gate
        self.always_limited = always_limited
        self.calls = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                self.rfile.read(length)
                outer.calls += 1
                call = outer.calls
                if outer.gate is not None:
                    outer.gate.wait(10)
                limited = outer.always_limited or call <= outer.fail_first
                code = 429 if limited else 200
                payload = ({"error": {"type": "rate_limit_error", "message": "limited"}}
                           if limited else {"content": [{"type": "text", "text": "ok"}]})
                raw = json.dumps(payload).encode()
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except ConnectionResetError:
                    pass

            def log_message(self, *_args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return "http://127.0.0.1:%d" % self.server.server_address[1]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def write_mock_claude(workdir):
    script = os.path.join(workdir, "mock_terminal_claude.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(r'''import json, os, subprocess, sys, time
args = sys.argv[1:]
state = os.environ["MOCK_STATE"]
with open(os.path.join(state, "calls.jsonl"), "a", encoding="utf-8") as f:
    f.write(json.dumps({"args": args, "cwd": os.getcwd(), "pid": os.getpid()}) + "\n")
count_file = os.path.join(state, "count.txt")
count = int(open(count_file).read()) + 1 if os.path.exists(count_file) else 1
with open(count_file, "w") as f: f.write(str(count))
fail_cycles = int(os.environ.get("MOCK_FAIL_CYCLES", "1"))
if count <= fail_cycles:
    session = os.environ["MOCK_SESSION"]
    transcript = os.environ["MOCK_TRANSCRIPT"]
    prompt = "prompt-%d" % count
    payload = {"session_id": session, "transcript_path": transcript, "cwd": os.getcwd(),
               "prompt_id": prompt, "hook_event_name": "StopFailure", "error": "rate_limit",
               "last_assistant_message": "API Error: Request rejected (429)"}
    command = [sys.executable, os.environ["MOCK_HOOK"]]
    for _ in range(int(os.environ.get("MOCK_HOOK_TWICE", "1"))):
        subprocess.run(command, input=json.dumps(payload), text=True, env=os.environ, check=True)
    with open(transcript, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "assistant", "isApiErrorMessage": True,
                            "apiErrorStatus": 429, "promptId": prompt}) + "\n")
    while not os.path.exists(os.environ["MOCK_EXIT_FILE"]):
        time.sleep(0.05)
''')
    return script


def wait_for(paths, timeout=15):
    if isinstance(paths, str):
        paths = [paths]
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(os.path.exists(p) and os.path.getsize(p) > 0 for p in paths):
            return True
        time.sleep(0.05)
    return False


def calls(state):
    path = os.path.join(state, "calls.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


class Harness:
    def __init__(self, name, fail_first=0, gate=None, always_limited=False, fail_cycles=1, hook_twice=1, initial_prompt=None, with_session_id=False):
        self.workdir = tempfile.mkdtemp(prefix="429-terminal-%s-" % name)
        self.state = os.path.join(self.workdir, "state")
        self.config = os.path.join(self.workdir, "config")
        self.cwd = os.path.join(self.workdir, "project")
        os.makedirs(self.state)
        os.makedirs(self.config)
        os.makedirs(self.cwd)
        self.server = ProbeServer(fail_first, gate, always_limited)
        with open(os.path.join(self.config, "settings.json"), "w", encoding="utf-8") as f:
            json.dump({"env": {"ANTHROPIC_BASE_URL": self.server.url,
                               "ANTHROPIC_API_KEY": "test", "ANTHROPIC_MODEL": "test"}}, f)
        self.mock = write_mock_claude(self.workdir)
        self.transcript = os.path.join(self.state, "transcript.jsonl")
        self.exit_file = os.path.join(self.state, "exit.marker")
        self.env = os.environ.copy()
        self.env.update({"HOME": self.workdir, "USERPROFILE": self.workdir,
                         "CLAUDE_CONFIG_DIR": self.config, "MOCK_STATE": self.state,
                         "MOCK_SESSION": "session-" + name,
                         "MOCK_TRANSCRIPT": self.transcript, "MOCK_EXIT_FILE": self.exit_file,
                         "MOCK_HOOK": HOOK, "MOCK_FAIL_CYCLES": str(fail_cycles),
                         "MOCK_HOOK_TWICE": str(hook_twice), "NO_PROXY": "127.0.0.1,localhost"})
        self.command = [PY, TERMINAL, "--claude-command", self.mock,
                        "--probe-script", DAEMON, "--state-dir", self.state,
                        "--interval", "1", "--max-attempts", "3", "--poll", "0.05",
                        "--stop-timeout", "0.2", "--stability", "0.1"]
        self.command.append("--")
        if with_session_id:
            self.command += ["--session-id", "session-" + name]
        if initial_prompt:
            self.command.append(initial_prompt)

    def popen(self):
        return subprocess.Popen(self.command, cwd=self.cwd, env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def close(self):
        self.server.close()


def assert_resume(state, session, count):
    items = calls(state)
    assert len(items) == count, items
    resumed = items[-1]["args"]
    assert resumed[resumed.index("--resume") + 1] == session
    assert "继续" in resumed
    assert "--fork-session" not in resumed
    assert "--continue" not in resumed
    assert "-p" not in resumed
    assert "--session-id" not in resumed


def test_recovery_and_duplicate_hook():
    h = Harness("basic", fail_first=2, hook_twice=2, initial_prompt="do not replay", with_session_id=True)
    try:
        proc = h.popen()
        out, err = proc.communicate(timeout=25)
        assert proc.returncode == 0, (out, err)
        assert_resume(h.state, "session-basic", 2)
        assert "do not replay" in calls(h.state)[0]["args"]
        assert all("do not replay" not in item["args"] for item in calls(h.state)[1:])
        assert h.server.calls == 3, h.server.calls
    finally:
        if proc.poll() is None:
            proc.kill()
        h.close()


def test_manual_continue_cancels():
    gate = threading.Event()
    h = Harness("manual", gate=gate)
    proc = h.popen()
    try:
        assert wait_for(h.transcript)
        deadline = time.time() + 10
        while h.server.calls == 0 and time.time() < deadline:
            time.sleep(0.05)
        assert h.server.calls == 1
        with open(h.transcript, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "promptSource": "typed",
                                "message": {"content": "继续"}}) + "\n")
        time.sleep(0.5)
        gate.set()
        assert len(calls(h.state)) == 1, "manual input was overridden"
        with open(h.exit_file, "w") as f:
            f.write("exit")
        proc.communicate(timeout=10)
        assert proc.returncode == 0
        assert len(calls(h.state)) == 1
    finally:
        gate.set()
        if proc.poll() is None:
            proc.kill()
        h.close()


def test_two_windows():
    hs = [Harness("A"), Harness("B")]
    procs = []
    try:
        for h in hs:
            procs.append(h.popen())
        for h, proc in zip(hs, procs):
            proc.communicate(timeout=20)
            assert proc.returncode == 0
        assert_resume(hs[0].state, "session-A", 2)
        assert_resume(hs[1].state, "session-B", 2)
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
        for h in hs:
            h.close()


def test_second_429():
    h = Harness("repeat", fail_cycles=2)
    try:
        proc = h.popen()
        proc.communicate(timeout=25)
        assert proc.returncode == 0
        assert_resume(h.state, "session-repeat", 3)
        assert h.server.calls == 2
    finally:
        h.close()


def test_probe_failure_preserves_original():
    h = Harness("failure", always_limited=True)
    proc = h.popen()
    try:
        time.sleep(2)
        assert len(calls(h.state)) == 1, "probe failure killed the original"
        with open(h.exit_file, "w") as f:
            f.write("exit")
        proc.communicate(timeout=10)
        assert proc.returncode == 0
        assert len(calls(h.state)) == 1
    finally:
        if proc.poll() is None:
            proc.kill()
        h.close()


def main():
    tests = [test_recovery_and_duplicate_hook, test_manual_continue_cancels,
             test_two_windows, test_second_429, test_probe_failure_preserves_original]
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
