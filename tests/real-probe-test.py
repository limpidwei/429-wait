#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real-network probe smoke test — hits the actual Anthropic API with a fake key.

Verifies the full probe chain against a live endpoint:
  1. Credential reading from ~/.claude/settings.json (base_url, model)
  2. HTTP request construction (headers, body, endpoint path)
  3. Response parsing (expects 401 from fake key, which is in limited_status_codes)
  4. 3-state classification: should return "limited", not "error" or "ok"

Cost: $0 (fake key always rejected before any token usage).
Requires: network access to the Anthropic API (or your configured relay).

  python tests/real-probe-test.py    # exit 0 = pass
"""
import json
import os
import random
import string
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHIM = os.path.join(HERE, "..", "bin", "429-wait-shim.py")

# import probe machinery from the shim
sys.path.insert(0, os.path.join(HERE, "..", "bin"))
import importlib.util
spec = importlib.util.spec_from_file_location("shim", os.path.join(HERE, "..", "bin", "429-wait-shim.py"))
shim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shim)


def random_fake_key():
    """Generate a random fake API key that looks plausible but is invalid."""
    suffix = ''.join(random.choices(string.ascii_letters + string.digits, k=40))
    return "sk-ant-fake-" + suffix


def main():
    print("=== 429-wait real-network probe smoke test ===")
    print()

    # 1. Read real settings for base_url and model
    settings_path = os.path.expanduser(os.path.join("~", ".claude", "settings.json"))
    settings_data = shim.load_settings(settings_path)
    env_block = settings_data.get("env", {})

    base_url = (
        os.environ.get("ANTHROPIC_BASE_URL")
        or env_block.get("ANTHROPIC_BASE_URL", "")
    ).rstrip("/")
    model = (
        os.environ.get("ANTHROPIC_MODEL")
        or env_block.get("ANTHROPIC_MODEL", "")
        or "claude-sonnet-4-20250514"  # fallback
    )

    if not base_url:
        print("SKIP: no ANTHROPIC_BASE_URL configured (neither env nor settings.json)")
        return 0

    fake_key = random_fake_key()
    print("  base_url: %s" % base_url)
    print("  model:    %s" % model)
    print("  fake_key: %s...%s" % (fake_key[:12], fake_key[-4:]))
    print()

    # 2. Load the claude-code adapter to get probe config
    adapter_cfg = shim.find_adapter("claude-code")

    # 3. Run probe with fake key
    print("Sending probe to %s/v1/messages ..." % base_url)
    status, detail = shim.probe(base_url, fake_key, model, adapter_cfg)
    print("  status: %s" % status)
    print("  detail: %s" % detail[:200])
    print()

    # 4. Checks
    checks = [
        ("status is 'limited' (not 'ok' or 'error')", status == "limited"),
        ("detail contains 401 or 403",
         "401" in detail or "403" in detail or "authentication" in detail.lower() or "invalid" in detail.lower()),
    ]

    # 5. Bonus: also probe with real key if available, should return 'ok'
    real_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or env_block.get("ANTHROPIC_API_KEY", "")
    )
    if real_key:
        print("Bonus: probing with real key (should return 'ok') ...")
        real_status, real_detail = shim.probe(base_url, real_key, model, adapter_cfg)
        print("  status: %s" % real_status)
        print("  detail: %s" % real_detail[:200])
        print()
        checks.append(("real key returns 'ok'", real_status == "ok"))
    else:
        print("Bonus: skipped (no real ANTHROPIC_API_KEY found)")
        print()

    # 6. Report
    print("--- checks ---")
    failed = 0
    for name, ok in checks:
        print(("PASS  " if ok else "FAIL  ") + name)
        failed += 0 if ok else 1
    print("--- result: %s ---" % ("ALL PASSED" if failed == 0 else "%d FAILED" % failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
