#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
429-wait - usage-limit watchdog with optional per-session Claude recovery.

The probe talks directly to the API instead of launching `claude -p` (which
retries internally) or scraping the interactive UI. A Claude Code StopFailure
hook supplies --session-id and --cwd; recovery forks that conversation so an
open interactive session is never killed or written to concurrently.

Legacy standalone usage remains available:
  python 429-wait.py --interval 300 --tag mytask \
      --on-recover "claude --resume <session-id> -p continue"
"""
import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request


def default_settings_path():
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser(os.path.join("~", ".claude"))
    return os.path.join(config, "settings.json")


def read_cfg(settings_path):
    """Return (base_url, api_key, model) from the Claude Code settings file."""
    with open(settings_path, encoding="utf-8") as f:
        env = json.load(f).get("env", {})
    base = (env.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
    key = env.get("ANTHROPIC_API_KEY") or ""
    model = env.get("ANTHROPIC_MODEL") or ""
    return base, key, model


def probe(base, key, model, max_tokens=64, timeout=25):
    """Return ('ok'|'limited'|'error', detail); errors are not recovery."""
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
            "User-Agent": "429-wait/1.0",
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
    except Exception as e:  # noqa: BLE001 - transport failure is "not yet"
        return "error", "%s: %s" % (type(e).__name__, str(e)[:120])


def pid_is_running(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


def acquire_pid(pid_path):
    """Atomically claim a per-tag PID file. Return (claimed, active_pid)."""
    for _ in range(2):
        try:
            fd = os.open(pid_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as f:
                f.write(str(os.getpid()))
            return True, 0
        except FileExistsError:
            try:
                with open(pid_path, encoding="ascii") as f:
                    old = int(f.read().strip())
            except (OSError, ValueError):
                old = 0
            if old and pid_is_running(old):
                return False, old
            try:
                os.remove(pid_path)
            except OSError:
                pass
    return False, 0


def write_json(path, data):
    temp = path + ".tmp-%d" % os.getpid()
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(temp, path)


def parse_recovery_json(text):
    try:
        data = json.loads(text.strip())
        return data if isinstance(data, dict) else {}
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        try:
            data = json.loads(line)
            if isinstance(data, dict):
                return data
        except ValueError:
            continue
    return {}


def run_claude_recovery(args, paths, log):
    command = shutil.which(args.claude_command) or args.claude_command
    cmd = [command,
           "--resume", args.session_id,
           "--fork-session",
           "-p", "继续",
           "--output-format", "json"]
    log("running Claude recovery: resume=%s fork=true cwd=%s" % (args.session_id, args.cwd))
    result = {"source_session_id": args.session_id, "status": "failed", "exit_code": None}
    try:
        proc = subprocess.run(cmd, cwd=args.cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", shell=False)
        with open(paths["resume_log"], "w", encoding="utf-8") as f:
            f.write(proc.stdout or "")
            if proc.stderr:
                f.write("\n--- stderr ---\n" + proc.stderr)
        data = parse_recovery_json(proc.stdout or "")
        result["exit_code"] = proc.returncode
        result["session_id"] = data.get("session_id") or ""
        message = str(data.get("result", ""))
        limited = (data.get("api_error_status") == 429 or data.get("error") == "rate_limit"
                   or "429" in message and "API Error" in message)
        if limited:
            result["status"] = "handed_off"
            log("recovery hit another 429; handed off to the new session's StopFailure hook")
        elif proc.returncode == 0 and not data.get("is_error"):
            result["status"] = "completed"
            with open(paths["recovery_ok"], "w", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
            log("background recovery completed; new session=%s" % (result["session_id"] or "unknown"))
        else:
            log("background recovery failed: exit=%d" % proc.returncode)
    except OSError as exc:
        result["error"] = str(exc)
        log("cannot run background recovery: %s" % exc)
    write_json(paths["result"], result)
    return 0 if result["status"] in ("completed", "handed_off") else 1


def main():
    ap = argparse.ArgumentParser(description="Wait out an LLM usage limit, then resume.")
    ap.add_argument("--interval", type=int, default=300, help="seconds between probes")
    ap.add_argument("--max-attempts", type=int, default=120, help="give up after N probes")
    ap.add_argument("--tag", default="default", help="instance tag, one nanny per tag")
    ap.add_argument("--state-dir", default=os.path.expanduser(os.path.join("~", ".429-wait")))
    ap.add_argument("--on-recover", default="", help="legacy shell command to run once quota is back")
    ap.add_argument("--probe-max-tokens", type=int, default=64,
                    help="must be big enough that the relay meters it (64 is calibrated)")
    ap.add_argument("--settings", default=default_settings_path(), help="Claude Code settings.json")
    ap.add_argument("--base-url", default="", help="override ANTHROPIC_BASE_URL")
    ap.add_argument("--api-key", default="", help="override ANTHROPIC_API_KEY")
    ap.add_argument("--model", default="", help="override ANTHROPIC_MODEL")
    ap.add_argument("--session-id", default="", help="source Claude session for background recovery")
    ap.add_argument("--cwd", default="", help="working directory of the source Claude session")
    ap.add_argument("--recover-agent", choices=("claude-code",), default="",
                    help="recover a session through its agent instead of --on-recover")
    ap.add_argument("--claude-command", default="claude", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.recover_agent and (not args.session_id or not args.cwd):
        ap.error("--recover-agent requires --session-id and --cwd")

    os.makedirs(args.state_dir, exist_ok=True)
    paths = {
        "log": os.path.join(args.state_dir, "nanny-%s.log" % args.tag),
        "pid": os.path.join(args.state_dir, "nanny-%s.pid" % args.tag),
        "ok": os.path.join(args.state_dir, "nanny-%s.ok" % args.tag),
        "recovery_ok": os.path.join(args.state_dir, "nanny-%s.recovery.ok" % args.tag),
        "result": os.path.join(args.state_dir, "nanny-%s.result.json" % args.tag),
        "resume_log": os.path.join(args.state_dir, "resume-%s.log" % args.tag),
    }

    def log(msg):
        line = "%s [pid %d] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), os.getpid(), msg)
        with open(paths["log"], "a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(line, flush=True)

    claimed, active_pid = acquire_pid(paths["pid"])
    if not claimed:
        log("another nanny for this session is already running (pid %s); exit" % active_pid)
        return 0

    for key in ("ok", "recovery_ok", "result"):
        if os.path.exists(paths[key]):
            os.remove(paths[key])

    try:
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
            return 64

        log("START tag=%s interval=%ss max=%d model=%s probe_max_tokens=%s base=%s"
            % (args.tag, args.interval, args.max_attempts, model, args.probe_max_tokens, base))

        for attempt in range(1, args.max_attempts + 1):
            status, detail = probe(base, key, model, args.probe_max_tokens)
            if status == "limited":
                log("attempt %d/%d: STILL LIMITED :: %s" % (attempt, args.max_attempts, detail))
                if attempt < args.max_attempts:
                    time.sleep(args.interval)
                continue
            if status == "error":
                log("attempt %d/%d: ERROR (not recovering) :: %s" % (attempt, args.max_attempts, detail))
                if attempt < args.max_attempts:
                    time.sleep(min(args.interval, 120))
                continue

            log("attempt %d/%d: RECOVERED :: %s" % (attempt, args.max_attempts, detail))
            with open(paths["ok"], "w", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
            if args.recover_agent == "claude-code":
                return run_claude_recovery(args, paths, log)
            if args.on_recover:
                log("running on-recover: %s" % args.on_recover)
                try:
                    p = subprocess.run(args.on_recover, shell=True, cwd=os.path.expanduser("~"))
                    log("on-recover exit=%s" % p.returncode)
                    if p.returncode != 0:
                        return p.returncode
                except Exception as e:  # noqa: BLE001
                    log("on-recover failed: %s" % e)
                    return 1
            log("SUCCESS - quota restored, nanny exiting")
            return 0
        log("GIVE UP after %d attempts" % args.max_attempts)
        return 2
    finally:
        try:
            os.remove(paths["pid"])
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
