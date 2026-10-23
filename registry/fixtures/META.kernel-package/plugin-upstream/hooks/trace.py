#!/usr/bin/env python3
"""STUB upstream tracing hook (test fixture, not the vendor's code).

Stands in for the LangSmith plugin's hook script so the Tracing_Wrapper can be
built, signed, installed and benchmarked offline. It does what a tracer does on
the wire and nothing more: read the hook payload on stdin and POST it to
LANGSMITH_ENDPOINT, with a short timeout, swallowing every error. Without the
variable it targets 127.0.0.1 port 9 (discard, normally closed), so a stray run
never leaves the machine. It prints nothing and always exits 0.
"""
import json
import os
import sys
import urllib.request

for _s in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def main() -> int:
    if str(os.environ.get("TRACE_TO_LANGSMITH", "")).strip().lower() not in ("1", "true", "yes", "on"):
        return 0
    data = sys.stdin.buffer.read()
    event = sys.argv[1] if len(sys.argv) > 1 else "unknown"
    body = json.dumps({"event": event, "bytes": len(data)}).encode("utf-8")
    url = os.environ.get("LANGSMITH_ENDPOINT") or "http://127.0.0.1:9/"
    try:
        req = urllib.request.Request(url.rstrip("/") + "/runs", data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
