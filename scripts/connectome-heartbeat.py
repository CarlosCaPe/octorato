#!/usr/bin/env python3
"""connectome-heartbeat.py — the Delegate-phase heartbeat (UserPromptSubmit hook).

> "Like the octopus — when its heart beats, blood circulates through its entire
>  being and returns. That's how I always imagined the graph."

One light beat per prompt: circulate the whole connectome, surface the agents and
skills the brain ALREADY HAS for THIS prompt, plus the 1-hop impact radius of the
strongest match, and inject that awareness as context. This is the autonomic version
of the 2D-Gate Q1 (`query_connectome.py query`) the model used to run by hand — now
it beats on its own, every prompt, in the Delegate phase.

Augments, does not replace: the model still runs Q2 (API?) + Q3 (delegate-check) and
owns the ACTIVATE / LOAD / SELF verdict. The beat just makes Q1 involuntary.

Budget: the systemic heart must not seize mid-stroke. Full map load is ~0.085s and
scoring ~0.05s, so the beat lands well under 1s; a hard signal.alarm self-timeout caps
it and FAILS OPEN — a skipped beat is survivable, a hung prompt is not.

Emits the UserPromptSubmit contract:
  {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BRAIN = Path(__file__).resolve().parent.parent
MAP = BRAIN / "neural_map.json"
BUDGET_S = 3  # hard self-timeout, well under the 5s harness ceiling


def emit(context: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit", "additionalContext": context}}))


def read_prompt() -> str:
    try:
        return (json.load(sys.stdin) or {}).get("prompt", "") or ""
    except Exception:
        return ""


def score(prompt: str, data: dict, qc):
    """Replicate query_connectome.cmd_query scoring exactly (TF-IDF cosine + bigrams)."""
    from collections import Counter
    tokens = qc.tokenize_query(prompt)
    if not tokens:
        return []
    ti = data.get("tfidf_index", {})
    idf, vectors = ti.get("idf", {}), ti.get("vectors", {})
    if not (idf and vectors):
        return []
    bigrams = [f"{tokens[i]}_{tokens[i+1]}" for i in range(len(tokens) - 1)
               if tokens[i] != tokens[i + 1]]
    terms = tokens + bigrams
    tf = Counter(terms)
    total = len(terms) or 1
    qv = {t: (c / total) * idf[t] for t, c in tf.items() if t in idf}
    scored = []
    for doc_id, dv in vectors.items():
        sim = qc._cosine_sim(qv, dv)
        if sim > 0.001:
            nid = doc_id.split(":", 1)[1] if ":" in doc_id else doc_id
            kind = "agent" if doc_id.startswith("agent:") else "skill"
            scored.append((nid, kind, sim))
    scored.sort(key=lambda x: -x[2])
    return scored


def beat(prompt: str) -> str:
    sys.path.insert(0, str(BRAIN / "scripts"))
    import query_connectome as qc  # lazy networkx — top-level import is cheap

    data = json.loads(MAP.read_text(encoding="utf-8"))
    names = {}
    impact = {}
    for n in data.get("neurons", []):
        names[n["id"]] = n.get("name", n["id"])
        impact[n["id"]] = list(n.get("synapses", {})) + list(n.get("neighbors", {}))
    for s in data.get("synapses", []):
        names.setdefault(s["id"], s.get("name", s["id"]))
        impact.setdefault(s["id"], list(s.get("connected_neurons", {})) +
                          list(s.get("cluster_neighbors", {})))
    gods = {b["id"] if isinstance(b, dict) else b
            for b in data.get("diagnostics", {}).get("busiest_neurons", [])}

    reflex = ("  ¿y el grafo? Before grep'ing the brain for where a concept lives, SEEK it: "
              "impact-radius.py --file <path> (seek > scan, ~100x cheaper, deterministic). "
              "grep+write without a seek receipt = FAILURE.")

    scored = score(prompt, data, qc)
    if not scored:
        return ("♥ connectome heartbeat: no strong match for this prompt — "
                "2D leans SELF; confirm with delegate-check before deciding.\n" + reflex)

    agents = [(i, s) for i, k, s in scored if k == "agent"][:3]
    skills = [(i, s) for i, k, s in scored if k == "skill"][:5]
    lines = ["♥ CONNECTOME HEARTBEAT (Delegate / Q1, autonomic) — what the brain already has:"]
    if agents:
        lines.append("  Agents: " + ", ".join(
            f"{names.get(i, i)}({s:.2f}{'·god' if i in gods else ''})" for i, s in agents))
    if skills:
        lines.append("  Skills: " + ", ".join(f"{names.get(i, i)}({s:.2f})" for i, s in skills))
    top_id = scored[0][0]
    hop = [h for h in impact.get(top_id, []) if h in names][:6]
    if hop:
        lines.append(f"  Impact radius of '{names.get(top_id, top_id)}' (1 hop): "
                     + ", ".join(names[h] for h in hop))
    lean = ("ACTIVATE" if agents and agents[0][1] >= 0.15
            else "LOAD" if skills else "SELF")
    lines.append(f"  Heartbeat lean: {lean}. Still run Q2 (API?) + Q3 (delegate-check) "
                 "and state the verdict.")
    lines.append(reflex)
    return "\n".join(lines)


def main() -> int:
    prompt = read_prompt()
    # Skip slash-commands and trivially short prompts — no circulation needed.
    if not prompt or len(prompt.strip()) < 5 or prompt.lstrip().startswith("/"):
        return 0
    if not MAP.exists():
        return 0

    # Hard self-timeout where supported (POSIX). Windows has no SIGALRM — rely on the
    # harness 5s ceiling there; the beat is sub-second anyway.
    try:
        import signal

        def _bail(*_):
            raise TimeoutError()

        signal.signal(signal.SIGALRM, _bail)
        signal.alarm(BUDGET_S)
    except Exception:
        signal = None  # type: ignore

    try:
        emit(beat(prompt))
    except TimeoutError:
        emit("♥ heartbeat skipped (over budget this turn) — run "
             "query_connectome.py query manually if the task is non-trivial.")
    except Exception as exc:
        emit(f"♥ heartbeat unavailable ({type(exc).__name__}) — run "
             "query_connectome.py query manually for the 2D gate.")
    finally:
        if signal is not None:
            try:
                signal.alarm(0)
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
