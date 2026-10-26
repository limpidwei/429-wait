#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""End-to-end test for 429-wait-shim.py.

Spins up:
  1. A mock "agent" script that exits with a rate-limit-like stderr on first run,
     then succeeds on second run.
  2. A mock HTTP probe server that returns 429 twice, then 200.
  3. A temporary adapter TOML pointing at both.

Runs the shim and verifies the full cycle:
  agent fails -> shim detects -> probe 429x2 -> probe 200 -> agent re-launched -> success

  python tests/shim-e2e.py    # exit 0 = pass
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
SHIM = os.path.join(HERE, "..", "bin", "429-wait-shim.py")
PY = sys.executable or "python"

FAILS_BEFORE_OK = 2  # probe returns 429 this many times before 200
probe_state = {"calls": 0}
agent_state = {"calls": 0}


# ---------------------------------------------------------------------------
# Mock probe server
# ---------------------------------------------------------------------------
class ProbeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        probe_state["calls"] += 1
        if probe_state["calls"] <= FAILS_BEFORE_OK:
            self._send(429, {"type": "error", "error": {"type": "rate_limit_error",
                                                        "message": "hit usage limit"}})
        else:
            self._send(200, {"content": [{"type": "text", "text": "hi"}]})

    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


# ---------------------------------------------------------------------------
# Mock agent script
# ---------------------------------------------------------------------------
def write_mock_agent(workdir):
    """Write a Python script that fails with rate-limit stderr on first call,
    succeeds on second call. Uses a counter file to track calls."""
    counter_file = os.path.join(workdir, "agent_counter.txt")
    script = os.path.join(workdir, "mock-agent.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent('''\
            import sys, os
            counter_file = r"%s"
            n = 0
            if os.path.exists(counter_file):
                n = int(open(counter_file).read().strip())
            n += 1
            with open(counter_file, "w") as f:
                f.write(str(n))
            if n == 1:
                print("Error: hit usage limit for this billing period", file=sys.stderr)
                sys.exit(1)
            else:
                print("SUCCESS", flush=True)
                sys.exit(0)
        ''' % counter_file.replace("\\", "\\\\")))
    return script, counter_file


def write_mock_adapter(workdir, probe_port, agent_script):
    """Write a temporary adapter TOML for the mock agent."""
    adapter_dir = os.path.join(workdir, "adapters")
    os.makedirs(adapter_dir, exist_ok=True)
    toml_path = os.path.join(adapter_dir, "mock-agent.toml")
    with open(toml_path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent('''\
            [agent]
            name = "mock-agent"
            command = "mock-agent"

            [detection]
            exit_codes = [1]
            require_stderr_match = true
            stderr_patterns = ["hit usage limit", "rate limit", "429"]

            [probe]
            type = "http"
            endpoint_path = "/v1/messages"
            auth_header = "x-api-key"

            [probe.settings_keys]
            base_url = "env.MOCK_BASE_URL"
            api_key = "env.MOCK_API_KEY"
            model = "env.MOCK_MODEL"

            [probe.body]
            format = "anthropic"

            [probe.params]
            max_tokens = 64
            timeout = 10
            interval = 1
            max_attempts = 10
            limited_status_codes = [429]

            [recovery]
            strategy = "replay"
        '''))
    return toml_path, adapter_dir


# ---------------------------------------------------------------------------
# Shim wrapper script (fake binary that calls shim)
# ---------------------------------------------------------------------------
def write_shim_wrapper(workdir, agent_script):
    """On Windows we need a wrapper that the shim's find_real_binary can discover.
    We put the real agent in a subdir so the shim skips the shim-dir."""
    real_dir = os.path.join(workdir, "real-bin")
    os.makedirs(real_dir, exist_ok=True)
    if os.name == "nt":
        wrapper = os.path.join(real_dir, "mock-agent.cmd")
        with open(wrapper, "w") as f:
            f.write('@echo off\r\n"%s" "%s" %%*\r\n' % (PY, agent_script))
    else:
        wrapper = os.path.join(real_dir, "mock-agent")
        with open(wrapper, "w") as f:
            f.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (PY, agent_script))
        os.chmod(wrapper, 0o755)
    return real_dir


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------
def main():
    workdir = tempfile.mkdtemp(prefix="shim-e2e-")

    # start probe server
    srv = HTTPServer(("127.0.0.1", 0), ProbeHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # write mock pieces
    agent_script, counter_file = write_mock_agent(workdir)
    _toml_path, adapter_dir = write_mock_adapter(workdir, port, agent_script)
    real_dir = write_shim_wrapper(workdir, agent_script)

    # set up PATH so find_real_binary finds the mock agent
    env = os.environ.copy()
    env["PATH"] = real_dir + os.pathsep + env.get("PATH", "")
    env["MOCK_BASE_URL"] = "http://127.0.0.1:%d" % port
    env["MOCK_API_KEY"] = "test-key"
    env["MOCK_MODEL"] = "test-model"

    # override adapter search path — put adapters dir beside bin/
    # We do this by symlinking/copying the shim next to the adapter dir
    bin_dir = os.path.join(workdir, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    import shutil
    shutil.copy2(SHIM, os.path.join(bin_dir, "429-wait-shim.py"))
    shim_copy = os.path.join(bin_dir, "429-wait-shim.py")

    state_dir = os.path.join(workdir, "state")
    cmd = [
        PY, shim_copy,
        "--adapter", "mock-agent",
        "--shim-dir", workdir,  # exclude workdir from PATH search (shim lives here)
        "--state-dir", state_dir,
        "--",
    ]

    print("--- running shim e2e test ---")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)

    # read logs
    log_path = os.path.join(state_dir, "shim-mock-agent.log")
    log = ""
    if os.path.isfile(log_path):
        log = open(log_path, encoding="utf-8").read()

    # read agent counter
    agent_calls = 0
    if os.path.isfile(counter_file):
        agent_calls = int(open(counter_file).read().strip())

    checks = [
        ("exit code 0 (success)", proc.returncode == 0),
        ("agent called twice (fail + success)", agent_calls == 2),
        ("probe server hit 3 times (2 limited + 1 ok)", probe_state["calls"] == FAILS_BEFORE_OK + 1),
        ("log contains STILL LIMITED", "STILL LIMITED" in log),
        ("log contains RECOVERED", "RECOVERED" in log),
        ("stdout contains SUCCESS", "SUCCESS" in proc.stdout),
        ("pid file cleaned up", not os.path.isfile(os.path.join(state_dir, "shim-mock-agent.pid"))),
    ]

    print("--- shim log ---")
    print(log.strip() or "(empty)")
    print("--- stdout ---")
    print(proc.stdout.strip() or "(empty)")
    print("--- stderr ---")
    print(proc.stderr.strip() or "(empty)")
    print("--- checks ---")
    failed = 0
    for name, ok in checks:
        print(("PASS  " if ok else "FAIL  ") + name)
        failed += 0 if ok else 1
    print("--- result: %s ---" % ("ALL PASSED" if failed == 0 else "%d FAILED" % failed))

    srv.shutdown()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
