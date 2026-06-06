#!/usr/bin/env python3
"""
arm-synthetics-runner.py — Port 7 (Phase D) probe runner.

Reads <arm>/synthetics.yaml and runs each probe in sequence. Exits 0 if
all probes pass, 1 if any fail. Writes a JSON summary to --out so the
calling workflow can post a structured failure notification.

This script lives in the brain repo and is fetched at runtime by each
arm's GH Action workflow (see synthetics.yml.workflow-template).
Centralising the runner keeps probe semantics consistent across arms
without duplicating code.

Dependencies: pyyaml (install in the workflow). Everything else is stdlib.

Arm-isolation rule: the script NEVER writes the arm slug, the URLs, or
the response bodies to anywhere outside the calling workflow's stdout /
the --out file. The arm's own repo holds that data. The brain is never
read from or written to by this runner.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from typing import Any
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass



def load_config(path: str) -> dict:
    import yaml  # required for the runner; the workflow installs it
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _walk_json_path(obj: Any, path: str) -> Any:
    # Minimal JSON-path: supports $.a.b.c — no array indexing yet.
    if not path or path == "$":
        return obj
    if path.startswith("$."):
        path = path[2:]
    parts = path.split(".")
    cur = obj
    for p in parts:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def run_probe(probe: dict) -> tuple[bool, str]:
    """Run a single probe. Returns (passed, message)."""
    name = probe.get("name", "(unnamed)")
    url = probe.get("url")
    if not url:
        return False, f"{name}: missing url"
    method = probe.get("method", "GET").upper()
    timeout = float(probe.get("timeout_seconds", 30))

    # User-Agent: identify the synthetic prober so site owners see who it is and
    # so the request doesn't get WAF-blocked as bare urllib. Probe-specific UA
    # can override via the `user_agent` field in synthetics.yaml.
    # ASCII-only — urllib rejects non-latin1 header values.
    ua = probe.get("user_agent") or "BrainSynthetics/1.0 (Port 7, github.com/CarlosCaPe/octorato)"
    req = urllib.request.Request(url, method=method, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read(64 * 1024)  # cap at 64 KB to bound memory
            content_type = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        status = e.code
        body = b""
        content_type = ""
    except Exception as e:
        return False, f"{name}: request failed — {type(e).__name__}: {e}"

    expected_status = probe.get("expect_status")
    if expected_status is not None and status != int(expected_status):
        return False, f"{name}: status {status} != {expected_status}"

    expect_regex = probe.get("expect_regex")
    if expect_regex:
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        if not re.search(expect_regex, text):
            return False, f"{name}: regex /{expect_regex}/ not found"

    expect_json_path = probe.get("expect_json_path")
    if expect_json_path:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return False, f"{name}: body is not JSON (content-type={content_type})"
        actual = _walk_json_path(data, expect_json_path)
        if "expect_json_value" in probe:
            if actual != probe["expect_json_value"]:
                return False, f"{name}: {expect_json_path}={actual!r} != {probe['expect_json_value']!r}"
        elif not actual:
            return False, f"{name}: {expect_json_path} is falsy ({actual!r})"

    return True, f"{name}: ok ({status})"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Brain Synthetics probe runner.")
    p.add_argument("--config", required=True, help="Path to synthetics.yaml")
    p.add_argument("--out", default="-", help="Output JSON summary (default: stdout)")
    args = p.parse_args(argv)

    try:
        cfg = load_config(args.config)
    except Exception as e:
        sys.stderr.write(f"✗ Could not load config {args.config}: {e}\n")
        return 2

    probes = cfg.get("probes") or []
    if not isinstance(probes, list):
        sys.stderr.write("✗ probes must be a list\n")
        return 2

    passed: list[str] = []
    failed: list[str] = []
    for probe in probes:
        ok, msg = run_probe(probe)
        if ok:
            passed.append(msg)
            print(f"  ✓ {msg}")
        else:
            failed.append(msg)
            print(f"  ✗ {msg}")

    summary = {
        "total": len(probes),
        "passed": passed,
        "failed": failed,
        "exit_code": 0 if not failed else 1,
    }
    payload = json.dumps(summary, indent=2)
    if args.out == "-":
        print(payload)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(payload + "\n")

    return summary["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
