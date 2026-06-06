"""
_pricing.py — shared Anthropic Claude API pricing helpers.

Single source of truth for USD conversion across the FinOps pipeline.
Used by skill-cost-profiler, brain-digest, watchdog cost_spike, and the
budget-check halt hook.

Prices are per 1M tokens (USD), list price as published on
https://www.anthropic.com/pricing — update the dict when Anthropic
changes rates or releases new models. Unknown models fall back to family
heuristics (opus / sonnet / haiku) so callers always get a number.

Critical billing notes (operator-internal):
  - With a Claude Max/Pro subscription, the USD figure is "what this
    would cost at list price" — value extracted, not money owed.
  - cache_creation_input_tokens is 1.25× input price (writing the cache).
  - cache_read_input_tokens is ~10% of input price (reading the cache) —
    high cache-read volume is GOOD news.
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


# Pricing per 1M tokens (USD). Last verified 2026-05-20.
# Source: https://www.anthropic.com/pricing
PRICING: dict[str, dict[str, float]] = {
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
}


def _normalize_model_name(model: str) -> str:
    """Strip suffixes like '[1m]' and the trailing 8-digit date that some
    Anthropic model IDs carry. Returns the canonical key for PRICING.
    """
    base = model.split("[")[0].lower().strip()
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
    if "opus" in base:
        return PRICING["claude-opus-4-7"]
    if "haiku" in base:
        return PRICING["claude-haiku-4-5"]
    return PRICING["claude-sonnet-4-6"]


def usage_to_usd(usage: dict, model: str = "claude-sonnet-4-6") -> float:
    """Convert a Claude usage block to USD at list price.

    Args:
      usage: dict with keys input_tokens / output_tokens /
             cache_creation_input_tokens / cache_read_input_tokens.
             Missing keys default to 0.
      model: model name string (full Anthropic name OK; we normalize).

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
