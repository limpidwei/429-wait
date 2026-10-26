#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Demo scenario for screenshots / promotional material.

Simulates a realistic Claude Code rate-limit -> recovery -> resume cycle
with realistic timing and output. Runs entirely locally (mock agent + mock probe).

Usage:
  python tests/demo-scenario.py

Then screenshot the terminal.
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
PY = sys.executable or "python"

# --- Config ---
PROBE_FAILS = 3       # probe returns 429 this many times (simulates ~15 min wait)
PROBE_INTERVAL = 2    # seconds between probes (fast for demo, real = 300)

probe_state = {"calls": 0}


class ProbeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        probe_state["calls"] += 1
        if probe_state["calls"] <= PROBE_FAILS:
            self._send(429, {"type": "error", "error": {
                "type": "rate_limit_error",
                "message": "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."}})
        else:
            self._send(200, {"id": "msg_demo", "type": "message", "role": "assistant",
                            "content": [{"type": "text", "text": "ok"}],
                            "model": "claude-sonnet-4-20250514",
                            "stop_reason": "end_turn",
                            "usage": {"input_tokens": 10, "output_tokens": 1}})

    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def write_mock_agent(workdir):
    """Mock agent that simulates Claude Code output."""
    counter_file = os.path.join(workdir, "agent_counter.txt")
    script = os.path.join(workdir, "mock-claude.py")
    with open(script, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent('''\
            import sys, os, time
            counter_file = r"%s"
            n = 0
            if os.path.exists(counter_file):
                n = int(open(counter_file).read().strip())
            n += 1
            with open(counter_file, "w") as f:
                f.write(str(n))

            if n == 1:
                # Simulate Claude Code working then hitting limit
                print("Claude Code session started.", flush=True)
                time.sleep(0.5)
                print("Reading project files...", flush=True)
                time.sleep(0.3)
                print("Analyzing codebase structure...", flush=True)
                time.sleep(0.5)
                print("Writing implementation for auth module...", flush=True)
                time.sleep(0.3)
                # Hit the wall
                print("Error: hit usage limit for this billing period", file=sys.stderr, flush=True)
                print("Your credit balance is too low. Please upgrade or wait for reset.", file=sys.stderr, flush=True)
                sys.exit(1)
            else:
                # Resumed session
                print("Claude Code session resumed.", flush=True)
                time.sleep(0.3)
                print("Continuing implementation for auth module...", flush=True)
                time.sleep(0.3)
                print("Writing tests for auth module...", flush=True)
                time.sleep(0.3)
                print("All tasks completed successfully.", flush=True)
                sys.exit(0)
        ''' % counter_file.replace("\\", "\\\\")))
    return script, counter_file


def write_demo_adapter(workdir, probe_port):
    adapter_dir = os.path.join(workdir, "adapters")
    os.makedirs(adapter_dir, exist_ok=True)
    toml_path = os.path.join(adapter_dir, "claude-code.toml")
    with open(toml_path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent('''\
            [agent]
            name = "claude-code"
            command = "claude"

            [detection]
            exit_codes = [1]
            require_stderr_match = true
            stderr_patterns = ["hit usage limit", "usage limit", "rate limit", "429", "403", "overloaded", "credit balance"]

            [probe]
            type = "http"
            endpoint_path = "/v1/messages"
            auth_header = "x-api-key"
            extra_headers = { "anthropic-version" = "2023-06-01" }

            [probe.settings_keys]
            base_url = "env.MOCK_BASE_URL"
            api_key = "env.MOCK_API_KEY"
            model = "env.MOCK_MODEL"

            [probe.body]
            format = "anthropic"

            [probe.params]
            max_tokens = 64
            timeout = 10
            interval = %d
            max_attempts = 20
            limited_status_codes = [429]

            [recovery]
            strategy = "continue"
            command_template = "{command} --continue"
        ''' % PROBE_INTERVAL))
    return adapter_dir


def write_shim_wrapper(workdir, agent_script):
    real_dir = os.path.join(workdir, "real-bin")
    os.makedirs(real_dir, exist_ok=True)
    if os.name == "nt":
        wrapper = os.path.join(real_dir, "claude.cmd")
        with open(wrapper, "w") as f:
            f.write('@echo off\r\n"%s" "%s" %%*\r\n' % (PY, agent_script))
    else:
        wrapper = os.path.join(real_dir, "claude")
        with open(wrapper, "w") as f:
            f.write('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (PY, agent_script))
        os.chmod(wrapper, 0o755)
    return real_dir


def main():
    workdir = tempfile.mkdtemp(prefix="429-demo-")

    # start probe server
    srv = HTTPServer(("127.0.0.1", 0), ProbeHandler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # set up mock pieces
    agent_script, _ = write_mock_agent(workdir)
    adapter_dir = write_demo_adapter(workdir, port)
    real_dir = write_shim_wrapper(workdir, agent_script)

    # copy shim next to adapters dir
    import shutil
    bin_dir = os.path.join(workdir, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    shutil.copy2(
        os.path.join(HERE, "..", "bin", "429-wait-shim.py"),
        os.path.join(bin_dir, "429-wait-shim.py"),
    )

    env = os.environ.copy()
    env["PATH"] = real_dir + os.pathsep + env.get("PATH", "")
    env["MOCK_BASE_URL"] = "http://127.0.0.1:%d" % port
    env["MOCK_API_KEY"] = "sk-ant-api01-xxxxxxxxxxxxxxxxxxxx"
    env["MOCK_MODEL"] = "claude-sonnet-4-20250514"

    state_dir = os.path.join(workdir, "state")
    cmd = [
        PY, os.path.join(bin_dir, "429-wait-shim.py"),
        "--adapter", "claude-code",
        "--shim-dir", workdir,
        "--state-dir", state_dir,
        "--",
        "--continue",  # simulates user running: claude --continue
    ]

    print()
    print("  $ claude --continue")
    print()

    proc = subprocess.run(cmd, env=env, timeout=120)

    srv.shutdown()
    print()
    if proc.returncode == 0:
        print("  [demo completed successfully]")
    else:
        print("  [demo exited with code %d]" % proc.returncode)


if __name__ == "__main__":
    sys.exit(main())
