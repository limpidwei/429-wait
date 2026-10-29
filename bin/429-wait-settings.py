#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Idempotently add or remove 429-wait's Claude Code StopFailure hook."""
import argparse
import json
import os
import shlex
import sys
import tempfile


def settings_path(args):
    if args.settings:
        return os.path.abspath(os.path.expanduser(args.settings))
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser(os.path.join("~", ".claude"))
    return os.path.join(config, "settings.json")


def load(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("settings root must be a JSON object")
    return data


def owned(group):
    if not isinstance(group, dict):
        return False
    for hook in group.get("hooks", []):
        if isinstance(hook, dict) and "429-wait-hook.py" in str(hook.get("command", "")):
            return True
    return False


def write_atomic(path, data):
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    if os.path.exists(path):
        backup = path + ".429-wait-backup"
        with open(path, "rb") as src, open(backup, "wb") as dst:
            dst.write(src.read())
    fd, temp = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        if os.path.exists(path):
            os.chmod(temp, os.stat(path).st_mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.remove(temp)


def hook_command(script):
    parts = [sys.executable, "-I", os.path.abspath(script)]
    if os.name == "nt":
        # Claude executes hook commands through a shell. Always quote absolute
        # Windows paths; list2cmdline leaves paths without spaces unquoted,
        # which then fail with status 127 in the hook shell.
        return " ".join('"' + p.replace('"', '\\"') + '"' for p in parts)
    return shlex.join(parts)


def install(data, command):
    hooks = data.setdefault("hooks", {})
    groups = hooks.setdefault("StopFailure", [])
    if not isinstance(groups, list):
        raise ValueError("hooks.StopFailure must be an array")
    remaining = [g for g in groups if not owned(g)]
    remaining.append({"hooks": [{"type": "command", "command": command, "timeout": 10}]})
    changed = remaining != groups
    if changed:
        hooks["StopFailure"] = remaining
    return changed


def uninstall(data):
    hooks = data.get("hooks")
    if not isinstance(hooks, dict) or "StopFailure" not in hooks:
        return False
    groups = hooks["StopFailure"]
    if not isinstance(groups, list):
        raise ValueError("hooks.StopFailure must be an array")
    remaining = [g for g in groups if not owned(g)]
    if remaining == groups:
        return False
    if remaining:
        hooks["StopFailure"] = remaining
    else:
        del hooks["StopFailure"]
    if not hooks:
        data.pop("hooks", None)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("install", "uninstall"))
    ap.add_argument("--hook-script", required=True)
    ap.add_argument("--settings", default="")
    args = ap.parse_args()
    path = settings_path(args)
    try:
        data = load(path)
        changed = install(data, hook_command(args.hook_script)) if args.action == "install" else uninstall(data)
        if changed:
            write_atomic(path, data)
        print("429-wait hook %s: %s" % (args.action, "updated" if changed else "unchanged"))
        print("settings: %s" % path)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("429-wait settings error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
