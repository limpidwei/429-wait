#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Install/uninstall settings helper without touching a real Claude config."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "..", "bin", "429-wait-settings.py")
PY = sys.executable or "python"


def run(*args, env):
    return subprocess.run([PY, HELPER] + list(args), env=env,
                          capture_output=True, text=True, timeout=10)


def main():
    workdir = tempfile.mkdtemp(prefix="429-settings-test-")
    config = os.path.join(workdir, "claude-config")
    os.makedirs(config)
    settings = os.path.join(config, "settings.json")
    original = {
        "env": {"KEEP_ME": "yes"},
        "hooks": {"StopFailure": [{"matcher": "other", "hooks": [
            {"type": "command", "command": "other-command"}
        ]}]},
    }
    with open(settings, "w", encoding="utf-8") as f:
        json.dump(original, f)
    env = os.environ.copy()
    env["CLAUDE_CONFIG_DIR"] = config
    hook_script = os.path.abspath(os.path.join(HERE, "..", "bin", "429-wait-hook.py"))

    checks = []
    first = run("install", "--hook-script", hook_script, env=env)
    second = run("install", "--hook-script", hook_script, env=env)
    with open(settings, encoding="utf-8") as f:
        installed = json.load(f)
    groups = installed["hooks"]["StopFailure"]
    owned = [g for g in groups if "429-wait-hook.py" in json.dumps(g)]
    other = [g for g in groups if "other-command" in json.dumps(g)]
    executed = subprocess.run(owned[0]["hooks"][0]["command"], shell=True,
                              input="not-json", text=True, capture_output=True, timeout=10)
    checks += [("first install", first.returncode == 0),
               ("idempotent install", second.returncode == 0 and len(owned) == 1),
               ("installed hook command executes", executed.returncode == 0),
               ("other hook preserved", len(other) == 1),
               ("other settings preserved", installed["env"]["KEEP_ME"] == "yes")]

    removed = run("uninstall", "--hook-script", hook_script, env=env)
    with open(settings, encoding="utf-8") as f:
        uninstalled = json.load(f)
    remaining = uninstalled["hooks"]["StopFailure"]
    checks += [("uninstall", removed.returncode == 0),
               ("owned hook removed", all("429-wait-hook.py" not in json.dumps(g) for g in remaining)),
               ("other hook survives uninstall", any("other-command" in json.dumps(g) for g in remaining)),
               ("settings survive uninstall", uninstalled["env"]["KEEP_ME"] == "yes")]

    failed = 0
    for name, ok in checks:
        print(("PASS  " if ok else "FAIL  ") + name)
        failed += 0 if ok else 1
    if failed:
        print(first.stdout, first.stderr, second.stdout, second.stderr, removed.stdout, removed.stderr)
    print("--- result: %s ---" % ("PASS" if not failed else "%d FAILED" % failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
