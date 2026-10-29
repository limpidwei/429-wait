#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Supervise a real Claude TUI and resume the same session in the same terminal."""
import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
import uuid


def find_real_binary(command, shim_dir):
    shim_dir = os.path.normcase(os.path.abspath(shim_dir)) if shim_dir else ""
    extensions = [".CMD", ".cmd", ".EXE", ".exe", ".BAT", ".bat", ""] if os.name == "nt" else [""]
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        if shim_dir and os.path.normcase(os.path.abspath(directory)) == shim_dir:
            continue
        for ext in extensions:
            candidate = os.path.join(directory, command + ext)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                try:
                    with open(candidate, "r", errors="ignore") as f:
                        if "429-wait-terminal.py" in f.read(512):
                            continue
                except OSError:
                    pass
                if os.name == "nt" and candidate.lower().endswith(".cmd"):
                    native = os.path.join(os.path.dirname(candidate), "node_modules",
                                          "@anthropic-ai", "claude-code", "bin", "claude.exe")
                    if os.path.isfile(native):
                        return native
                return candidate
    return ""


def pid_is_running(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


class TerminalState:
    def __init__(self):
        self.unix_attrs = None
        self.windows_modes = []
        if os.name == "nt":
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            kernel32.GetStdHandle.restype = wintypes.HANDLE
            for number in (-10, -11):
                handle = kernel32.GetStdHandle(number)
                mode = wintypes.DWORD()
                if handle and kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    self.windows_modes.append((number, mode.value))
        elif sys.stdin.isatty():
            import termios
            self.unix_attrs = termios.tcgetattr(sys.stdin.fileno())

    def restore(self):
        if os.name == "nt":
            kernel32 = ctypes.windll.kernel32
            for number, mode in self.windows_modes:
                kernel32.SetConsoleMode(kernel32.GetStdHandle(number), mode)
        elif self.unix_attrs is not None:
            import termios
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, self.unix_attrs)


class Supervisor:
    def __init__(self, args):
        self.args = args
        self.token = uuid.uuid4().hex
        os.makedirs(args.state_dir, exist_ok=True)
        self.event_file = os.path.join(args.state_dir, "terminal-%s.json" % self.token)
        self.log_path = os.path.join(args.state_dir, "terminal-%s.log" % self.token)
        self.command = args.claude_command
        if self.command == "claude":
            self.command = find_real_binary("claude", args.shim_dir)
        if not self.command:
            raise RuntimeError("cannot find the real Claude binary")
        self.env = os.environ.copy()
        self.env["429_WAIT_EVENT_FILE"] = self.event_file
        self.env["429_WAIT_SUPERVISOR_TOKEN"] = self.token
        self.base_args = self.recovery_base_args(args.agent_args)
        self.probe = None
        self.terminal = TerminalState()

    def log(self, message):
        line = "%s [terminal:%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), self.token[:8], message)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    @staticmethod
    def recovery_base_args(original):
        """Preserve configuration flags but drop session controls and the initial prompt."""
        value_options = {
            "--agent", "--agents", "--append-system-prompt", "--autocompact",
            "--debug-file", "--effort", "--fallback-model", "--input-format",
            "--json-schema", "--max-budget-usd", "--mcp-config", "--model",
            "--name", "--output-format", "--permission-mode", "--permission-prompt",
            "--plugin-dir", "--plugin-url", "--remote-control",
            "--remote-control-session-name-prefix", "--session-id", "--setting-sources",
            "--settings", "--system-prompt", "--system-prompt-file",
            "--system-prompt-snapshot", "--tools",
        }
        result = []
        i = 0
        while i < len(original):
            arg = original[i]
            if arg == "--":
                break
            if arg in ("--resume", "-r", "--session-id"):
                i += 2
                continue
            if arg in ("--continue", "-c", "--fork-session", "-p", "--print"):
                i += 1
                continue
            if not arg.startswith("-"):
                break  # positional prompt: do not replay it after recovery
            result.append(arg)
            if arg in value_options and i + 1 < len(original):
                result.append(original[i + 1])
                i += 2
            else:
                i += 1
        return result

    def start_child(self, command_args, cwd=None):
        cmd = [self.command] + command_args
        if self.command.lower().endswith(".py"):
            cmd.insert(0, sys.executable)
        self.log("start child: %s" % " ".join(cmd))
        return subprocess.Popen(cmd, cwd=cwd or os.getcwd(), env=self.env,
                                stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)

    def read_event(self):
        if not os.path.isfile(self.event_file):
            return {}
        try:
            with open(self.event_file, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def start_probe(self, event):
        self.cancel_probe()
        tag = "terminal-" + self.token
        cmd = [sys.executable, self.args.probe_script,
               "--tag", tag, "--state-dir", self.args.state_dir,
               "--interval", str(self.args.interval),
               "--max-attempts", str(self.args.max_attempts)]
        output = open(os.path.join(self.args.state_dir, "terminal-%s.probe.log" % self.token),
                      "a", encoding="utf-8")
        try:
            self.probe = subprocess.Popen(cmd, cwd=event.get("cwd") or os.getcwd(), env=self.env,
                                          stdin=subprocess.DEVNULL, stdout=output,
                                          stderr=subprocess.STDOUT)
            self.log("probe started for session=%s" % event.get("session_id"))
        finally:
            output.close()

    def cancel_probe(self):
        if self.probe is not None and self.probe.poll() is None:
            try:
                self.probe.terminate()
                self.probe.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    self.probe.kill()
                except OSError:
                    pass
        self.probe = None

    @staticmethod
    def transcript_action(pending):
        path = pending["event"].get("transcript_path") or ""
        if not path:
            return "unsafe" if pending["ready_at"] is not None else ""
        if not os.path.isfile(path):
            return "unsafe" if pending["ready_at"] is not None else ""
        try:
            with open(path, "rb") as f:
                f.seek(pending["offset"])
                raw = f.read()
                pending["offset"] = f.tell()
        except OSError:
            return "unsafe"
        for line in raw.decode("utf-8", "replace").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if item.get("type") == "user" and item.get("promptSource") == "typed":
                return "manual"
            if item.get("type") == "user" and item.get("turnOrigin") == "task_notification":
                return "unsafe"
        return ""

    @staticmethod
    def stop_child(proc, timeout):
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
        except OSError:
            return
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=timeout)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def run_child(self, command_args, cwd=None):
        proc = self.start_child(command_args, cwd)
        pending = None
        handled_event = ""
        try:
            while True:
                code = proc.poll()
                if code is not None:
                    self.cancel_probe()
                    return code, None

                event = self.read_event()
                event_id = event.get("event_id", "")
                if event and event_id and event_id != handled_event:
                    handled_event = event_id
                    transcript = event.get("transcript_path") or ""
                    pending = {"event": event,
                               "offset": os.path.getsize(transcript) if os.path.isfile(transcript) else 0,
                               "ready_at": None}
                    self.start_probe(event)

                if pending is not None:
                    action = self.transcript_action(pending)
                    if action:
                        self.log("automatic recovery cancelled: %s" % action)
                        self.cancel_probe()
                        pending = None
                    elif self.probe is not None and self.probe.poll() is not None:
                        probe_code = self.probe.returncode
                        self.probe = None
                        if probe_code != 0:
                            self.log("probe failed; original Claude left running (exit=%s)" % probe_code)
                            pending = None
                        else:
                            pending["ready_at"] = time.time()
                            self.log("quota restored; waiting for stable handoff")

                    if pending is not None and pending["ready_at"] is not None:
                        stable = time.time() - pending["ready_at"] >= self.args.stability
                        hook_done = not pid_is_running(int(pending["event"].get("hook_pid") or 0))
                        if stable and hook_done:
                            if self.transcript_action(pending):
                                self.log("recovery cancelled during final handoff")
                                pending = None
                            else:
                                event = pending["event"]
                                self.log("stopping idle Claude for same-window resume")
                                self.stop_child(proc, self.args.stop_timeout)
                                self.cancel_probe()
                                return None, event
                time.sleep(self.args.poll)
        except BaseException:
            self.cancel_probe()
            self.stop_child(proc, self.args.stop_timeout)
            raise

    def run(self):
        exit_code = 0
        cwd = None
        try:
            command_args = list(self.args.agent_args)
            while True:
                code, event = self.run_child(command_args, cwd)
                if event is None:
                    exit_code = code
                    break
                session_id = event.get("session_id")
                cwd = event.get("cwd") or cwd
                if not session_id:
                    exit_code = 1
                    break
                self.terminal.restore()
                print("429-wait: quota restored; resuming the original session...", file=sys.stderr, flush=True)
                try:
                    os.remove(self.event_file)
                except OSError:
                    pass
                command_args = list(self.base_args) + ["--resume", session_id, self.args.resume_prompt]
        except KeyboardInterrupt:
            exit_code = 130
        finally:
            self.cancel_probe()
            self.terminal.restore()
            try:
                os.remove(self.event_file)
            except OSError:
                pass
        return exit_code


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--shim-dir", default="")
    ap.add_argument("--state-dir", default=os.path.expanduser(os.path.join("~", ".429-wait")))
    ap.add_argument("--claude-command", default="claude")
    ap.add_argument("--probe-script", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "429-wait.py"))
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--max-attempts", type=int, default=120)
    ap.add_argument("--poll", type=float, default=0.25, help=argparse.SUPPRESS)
    ap.add_argument("--stop-timeout", type=float, default=5, help=argparse.SUPPRESS)
    ap.add_argument("--stability", type=float, default=0.5, help=argparse.SUPPRESS)
    ap.add_argument("--resume-prompt", default="继续")
    ap.add_argument("agent_args", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    if args.agent_args and args.agent_args[0] == "--":
        args.agent_args = args.agent_args[1:]
    try:
        return Supervisor(args).run()
    except RuntimeError as exc:
        print("429-wait: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
