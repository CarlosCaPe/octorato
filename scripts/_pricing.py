"""
_pricing.py — shared multi-vendor API pricing helpers.

Single source of truth for USD conversion across the FinOps pipeline.
Used by skill-cost-profiler, brain-digest, watchdog cost_spike, and the
budget-check halt hook.

Prices are per 1M tokens (USD), list price as published by each vendor.
Update the dict when a vendor changes rates or a new engine is first
metered in an Octorato session. Unknown models fall back to family
heuristics so callers always get a number.

Vendors currently metered:
  - Anthropic Claude — https://www.anthropic.com/pricing
  - xAI Grok — https://docs.x.ai/developers/pricing

Critical billing notes (operator-internal):
  - With a flat subscription (Claude Max/Pro, Cursor, etc.), the USD
    figure is "what this would cost at list price" — value extracted,
    not money owed, unless reconciling a real invoice.
  - Anthropic: cache_creation_input_tokens is 1.25× input; cache_read
    is ~10% of input — high cache-read volume is GOOD news.
  - xAI: cached input is a flat list price (see PRICING cache_r).
  - Synthetic messages (model='<synthetic>') are harness-generated, $0.
"""
from __future__ import annotations
import sys

# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# Pricing per 1M tokens (USD).
# Anthropic last verified 2026-05-20. xAI last verified 2026-07-10.
PRICING: dict[str, dict[str, float]] = {
    # --- Anthropic Claude ---
    "claude-opus-4-7":     {"in": 15.00, "out": 75.00, "cache_w": 18.75, "cache_r": 1.50},
    "claude-opus-4-6":     {"in": 15.00, "out": 75.00, "cache_w": 18.75, "cache_r": 1.50},
    "claude-opus-4":       {"in": 15.00, "out": 75.00, "cache_w": 18.75, "cache_r": 1.50},
    "claude-sonnet-4-6":   {"in":  3.00, "out": 15.00, "cache_w":  3.75, "cache_r": 0.30},
    "claude-sonnet-4-5":   {"in":  3.00, "out": 15.00, "cache_w":  3.75, "cache_r": 0.30},
    "claude-sonnet-4":     {"in":  3.00, "out": 15.00, "cache_w":  3.75, "cache_r": 0.30},
    "claude-haiku-4-5":    {"in":  0.80, "out":  4.00, "cache_w":  1.00, "cache_r": 0.08},
    "claude-haiku-4":      {"in":  0.80, "out":  4.00, "cache_w":  1.00, "cache_r": 0.08},
    "claude-3-5-sonnet":   {"in":  3.00, "out": 15.00, "cache_w":  3.75, "cache_r": 0.30},
    "claude-3-5-haiku":    {"in":  0.80, "out":  4.00, "cache_w":  1.00, "cache_r": 0.08},
    # --- xAI Grok (docs.x.ai/developers/pricing, 2026-07-10) ---
    # cache_w unused by xAI list table; set = input. cache_r = cached input.
    "grok-4.5":            {"in":  2.00, "out":  6.00, "cache_w":  2.00, "cache_r": 0.50},
    "grok-4.5-fast-xhigh": {"in":  2.00, "out":  6.00, "cache_w":  2.00, "cache_r": 0.50},
    "grok-4.5-latest":     {"in":  2.00, "out":  6.00, "cache_w":  2.00, "cache_r": 0.50},
    "grok-4.3":            {"in":  1.25, "out":  2.50, "cache_w":  1.25, "cache_r": 1.25},
    "grok-4.20-0309-reasoning":     {"in": 1.25, "out": 2.50, "cache_w": 1.25, "cache_r": 1.25},
    "grok-4.20-0309-non-reasoning": {"in": 1.25, "out": 2.50, "cache_w": 1.25, "cache_r": 1.25},
    "grok-4.20-multi-agent-0309":   {"in": 1.25, "out": 2.50, "cache_w": 1.25, "cache_r": 1.25},
    "grok-build-0.1":      {"in":  1.00, "out":  2.00, "cache_w":  1.00, "cache_r": 1.00},
}


def _normalize_model_name(model: str) -> str:
    """Strip suffixes like '[1m]' and trailing 8-digit Anthropic date stamps.
    Returns the canonical key for PRICING.
    """
    base = model.split("[")[0].lower().strip()
    # Cursor sometimes prefixes vendor: "xai/grok-4.5"
    if "/" in base:
        base = base.rsplit("/", 1)[-1]
    if base.count("-") >= 4:
        parts = base.rsplit("-", 1)
        if parts[1].isdigit() and len(parts[1]) == 8:
            base = parts[0]
    return base


def _price_per_model(model: str) -> dict[str, float]:
    base = _normalize_model_name(model)
    p = PRICING.get(base)
    if p:
        return p
    # Family heuristic fallback — keeps cost reporting alive when a new
    # model name lands before this dict is updated.
    if "grok" in base:
        if "build" in base:
            return PRICING["grok-build-0.1"]
        if "4.5" in base:
            return PRICING["grok-4.5"]
        return PRICING["grok-4.3"]
    if "opus" in base or "fable" in base:
        return PRICING["claude-opus-4-7"]
    if "haiku" in base:
        return PRICING["claude-haiku-4-5"]
    if "sonnet" in base or "claude" in base:
        return PRICING["claude-sonnet-4-6"]
    # Unknown vendor/engine — Sonnet-class placeholder so FinOps never NaNs.
    return PRICING["claude-sonnet-4-6"]


def usage_to_usd(usage: dict, model: str = "claude-sonnet-4-6") -> float:
    """Convert a usage block to USD at list price.

    Args:
      usage: dict with keys input_tokens / output_tokens /
             cache_creation_input_tokens / cache_read_input_tokens.
             Missing keys default to 0. xAI may only populate in/out.
      model: model name string (vendor full name or Cursor slug OK).

    Returns:
      USD figure rounded to cents.
    """
    p = _price_per_model(model)
    cost = (
        int(usage.get("input_tokens", 0) or 0) * p["in"] / 1e6
        + int(usage.get("output_tokens", 0) or 0) * p["out"] / 1e6
        + int(usage.get("cache_creation_input_tokens", 0) or 0) * p["cache_w"] / 1e6
        + int(usage.get("cache_read_input_tokens", 0) or 0) * p["cache_r"] / 1e6
    )
    return round(cost, 4)


def tokens_to_usd_simple(input_tokens: int, output_tokens: int,
                          cache_read: int = 0, cache_write: int = 0,
                          model: str = "claude-sonnet-4-6") -> float:
    """Convenience wrapper for callers that don't have a full usage dict.

    Used by skill-cost-profiler.py which only carries input_total + output.
    """
    return usage_to_usd(
        {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
        },
        model=model,
    )


def format_usd(value: float) -> str:
    """Stable cents-formatted string for digest tables."""
    return f"${value:,.2f}"
