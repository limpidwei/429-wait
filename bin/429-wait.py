#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
429-wait v2 - usage-limit watchdog (Python rewrite)

Why a rewrite (the PowerShell/bash v1 has three failure modes this avoids):

  1. Probing with `claude -p ping` never returns.
     Claude Code retries a 429 internally forever, so the probe hangs and the
     nanny is stuck at attempt 1. v2 probes the API endpoint directly over
     HTTP with a hard timeout.

  2. A tiny probe lies.
     Some relays meter a request by its declared `max_tokens`. With
     max_tokens=1 an exhausted quota can still answer 200; the same request
     with max_tokens=64 returns 429. Default here is 64 (--probe-max-tokens).

  3. Log-tailing never sees the limit.
     Claude Code prints the limit only in its TUI, it is not written to a log,
     so a log watcher has nothing to read. v2 polls actively - no log source
     needed at all.

Reads endpoint/key/model from ~/.claude/settings.json ("env" block) unless
overridden:

  ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY, ANTHROPIC_MODEL

Usage:
  python 429-wait.py --interval 300 --tag mytask \
      --on-recover "claude --resume <session-id> -p continue"

On recovery (probe returns 200) it runs --on-recover, writes the timestamp to
nanny-<tag>.ok and exits 0. Probe errors that are not quota errors (network
blips) never count as recovery.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

DEFAULT_SETTINGS = os.path.expanduser(os.path.join("~", ".claude", "settings.json"))


def read_cfg(settings_path):
    """Return (base_url, api_key, model) from the Claude Code settings file."""
    with open(settings_path, encoding="utf-8") as f:
        env = json.load(f).get("env", {})
    base = (env.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
    key = env.get("ANTHROPIC_API_KEY") or ""
    model = env.get("ANTHROPIC_MODEL") or ""
    return base, key, model


def probe(base, key, model, max_tokens=64, timeout=25):
    """Return ('ok'|'limited'|'error', detail).

    limited = quota/auth wall (429/401/403); error = anything else, which must
    not be mistaken for recovery.
    """
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": "hi"}],
    }).encode()
    req = urllib.request.Request(
        base + "/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Authorization": "Bearer " + key,
        },
    )
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        r.read()
        return "ok", "HTTP %d" % r.status
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "ignore")
        if e.code in (429, 401, 403):
            return "limited", "%d %s" % (e.code, txt[:160])
        return "error", "HTTP %d %s" % (e.code, txt[:160])
    except Exception as e:  # noqa: BLE001 - any transport failure is "not yet"
        return "error", "%s: %s" % (type(e).__name__, str(e)[:120])


def main():
    ap = argparse.ArgumentParser(description="Wait out an LLM usage limit, then resume.")
    ap.add_argument("--interval", type=int, default=300, help="seconds between probes")
    ap.add_argument("--max-attempts", type=int, default=120, help="give up after N probes")
    ap.add_argument("--tag", default="default", help="instance tag, one nanny per tag")
    ap.add_argument("--state-dir", default=os.path.expanduser(os.path.join("~", ".429-wait")))
    ap.add_argument("--on-recover", default="", help="command to run once quota is back")
    ap.add_argument("--probe-max-tokens", type=int, default=64,
                    help="must be big enough that the relay meters it (64 is calibrated)")
    ap.add_argument("--settings", default=DEFAULT_SETTINGS, help="Claude Code settings.json")
    ap.add_argument("--base-url", default="", help="override ANTHROPIC_BASE_URL")
    ap.add_argument("--api-key", default="", help="override ANTHROPIC_API_KEY")
    ap.add_argument("--model", default="", help="override ANTHROPIC_MODEL")
    args = ap.parse_args()

    os.makedirs(args.state_dir, exist_ok=True)
    log_path = os.path.join(args.state_dir, "nanny-%s.log" % args.tag)
    pid_path = os.path.join(args.state_dir, "nanny-%s.pid" % args.tag)
    ok_path = os.path.join(args.state_dir, "nanny-%s.ok" % args.tag)

    def log(msg):
        line = "%s [pid %d] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(), msg)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line, flush=True)

    # single instance per tag
    if os.path.exists(pid_path):
        try:
            old = int(open(pid_path).read().strip())
            os.kill(old, 0)
            log("another nanny already running (pid %d); exit" % old)
            return 0
        except Exception:
            pass
    with open(pid_path, "w") as f:
        f.write(str(os.getpid()))
    if os.path.exists(ok_path):
        os.remove(ok_path)

    try:
        base, key, model = read_cfg(args.settings)
    except Exception as e:  # missing file or malformed JSON
        base, key, model = "", "", ""
        log("cannot read %s (%s); relying on flags only" % (args.settings, e))
    base = (args.base_url or base).rstrip("/")
    key = args.api_key or key
    model = args.model or model
    missing = [n for n, v in (("base url", base), ("api key", key), ("model", model)) if not v]
    if missing:
        log("missing %s (set them in %s or pass flags)" % (", ".join(missing), args.settings))
        if os.path.exists(pid_path):
            os.remove(pid_path)
        return 64

    log("START tag=%s interval=%ss max=%d model=%s probe_max_tokens=%d base=%s"
        % (args.tag, args.interval, args.max_attempts, model, args.probe_max_tokens, base))

    try:
        for attempt in range(1, args.max_attempts + 1):
            status, detail = probe(base, key, model, args.probe_max_tokens)
            if status == "limited":
                log("attempt %d/%d: STILL LIMITED :: %s" % (attempt, args.max_attempts, detail))
                time.sleep(args.interval)
                continue
            if status == "error":
                # a network blip is neither recovery nor a quota wall - keep waiting
                log("attempt %d/%d: ERROR (not recovering) :: %s"
                    % (attempt, args.max_attempts, detail))
                time.sleep(min(args.interval, 120))
                continue
            log("attempt %d/%d: RECOVERED :: %s" % (attempt, args.max_attempts, detail))
            with open(ok_path, "w") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
            if args.on_recover:
                log("running on-recover: %s" % args.on_recover)
                try:
                    p = subprocess.run(args.on_recover, shell=True,
                                       cwd=os.path.expanduser("~"))
                    log("on-recover exit=%s" % p.returncode)
                except Exception as e:  # noqa: BLE001
                    log("on-recover failed: %s" % e)
            log("SUCCESS - quota restored, nanny exiting")
            return 0
        log("GIVE UP after %d attempts" % args.max_attempts)
        return 2
    finally:
        if os.path.exists(pid_path):
            os.remove(pid_path)


if __name__ == "__main__":
    sys.exit(main())
