#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Receive Claude Code StopFailure events and start a per-session nanny."""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid


def log(state_dir, tag, message):
    line = "%s [hook:%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), tag, message)
    try:
        with open(os.path.join(state_dir, "hook-%s.log" % tag), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main():
    default_state = os.path.expanduser(os.path.join("~", ".429-wait"))
    ap = argparse.ArgumentParser(description="429-wait Claude Code StopFailure hook")
    ap.add_argument("--state-dir", default=default_state)
    ap.add_argument("--daemon", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "429-wait.py"))
    ap.add_argument("--claude-command", default="claude")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--max-attempts", type=int, default=120)
    args = ap.parse_args()

    try:
        payload = json.load(sys.stdin)
    except (ValueError, TypeError):
        return 0
    if not isinstance(payload, dict):
        return 0

    session_id = payload.get("session_id") or ""
    cwd = payload.get("cwd") or ""
    error = payload.get("error") or ""
    message = payload.get("last_assistant_message") or ""
    if error != "rate_limit" or not re.search(r"429|rate.limit|usage.limit|quota", message, re.I):
        return 0
    if not session_id or not cwd:
        return 0

    event_file = os.environ.get("429_WAIT_EVENT_FILE", "")
    if event_file:
        event = dict(payload)
        event["event_id"] = "%s:%s" % (session_id, payload.get("prompt_id") or uuid.uuid4().hex)
        event["hook_pid"] = os.getpid()
        try:
            os.makedirs(os.path.dirname(event_file), exist_ok=True)
            temp = "%s.tmp-%d" % (event_file, os.getpid())
            with open(temp, "w", encoding="utf-8") as f:
                json.dump(event, f, ensure_ascii=False)
            os.replace(temp, event_file)
        except OSError:
            pass
        return 0

    tag = "claude-" + re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)
    os.makedirs(args.state_dir, exist_ok=True)
    if not os.path.isfile(args.daemon):
        log(args.state_dir, tag, "daemon not found; recovery not started")
        return 0

    daemon_log = open(os.path.join(args.state_dir, "hook-%s.daemon.log" % tag), "a", encoding="utf-8")
    try:
        cmd = [sys.executable, args.daemon,
               "--session-id", session_id,
               "--cwd", cwd,
               "--recover-agent", "claude-code",
               "--claude-command", args.claude_command,
               "--tag", tag,
               "--state-dir", args.state_dir,
               "--interval", str(args.interval),
               "--max-attempts", str(args.max_attempts)]
        kwargs = {"stdin": subprocess.DEVNULL, "stdout": daemon_log,
                  "stderr": subprocess.STDOUT, "cwd": cwd, "close_fds": True}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(cmd, **kwargs)
        log(args.state_dir, tag, "launch requested; nanny pid=%d" % proc.pid)
    except OSError as exc:
        log(args.state_dir, tag, "cannot launch nanny: %s" % exc)
    finally:
        daemon_log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
