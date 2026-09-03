#!/usr/bin/env python3
"""
query_connectome.py — Octopus Ventosas (Sucker Neural Interface) v1.0

Each sucker is an independent sensory organ — it can taste, touch, and grip
without waiting for the brain. This tool gives the octopus its suckers:
queryable graph traversal over the full connectome.

Reads neural_map.json and builds a NetworkX graph for:
  - Shortest path between any two nodes (agents, skills)
  - God nodes (highest centrality — the brain's most connected neurons)
  - Community detection (Leiden/Louvain — which neurons cluster together)
  - Task routing (given a description, find optimal agent→skill path)
  - Impact radius (from a node, what's within N hops)
  - HTML visualization (interactive graph in browser)

Usage:
  python3 query_connectome.py gods                    # Top 20 most connected nodes
  python3 query_connectome.py path <nodeA> <nodeB>     # Shortest path
  python3 query_connectome.py query "build a PDF"      # Find best agents+skills for task
  python3 query_connectome.py impact <node> [--hops 2] # Impact radius
  python3 query_connectome.py communities              # Community detection
  python3 query_connectome.py viz [--out graph.html]   # Interactive HTML visualization
  python3 query_connectome.py stats                    # Graph statistics
  python3 query_connectome.py 4d "task description"    # Full 4D pre-flight via graph

Integrates with the 4D paradigm:
  1D Describe  — context from graph neighbors
  2D Delegate  — shortest path task → agent → skills
  3D Diligent  — impact radius from modified nodes
  4D Disclose  — centrality + community analysis

No external API calls. Pure local graph computation.
"""

import json
import math
import os
import re
import sys
import unicodedata
import tempfile
from collections import Counter
from contextlib import contextmanager
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


try:
    import fcntl  # POSIX
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False  # Windows — fall back to no-op lock (atomic write still protects integrity)


@contextmanager
def _file_lock(lock_path):
    """Advisory exclusive lock so concurrent query_connectome.py invocations don't clobber neural_activity.json."""
    if not _HAS_FCNTL:
        yield  # Windows: rely on os.replace atomicity alone
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


def _atomic_write_json(path, data):
    """Write JSON via tempfile + os.replace so a crash mid-write can't corrupt the file."""
    target_dir = path.parent if hasattr(path, "parent") else os.path.dirname(str(path))
    target_dir = str(target_dir) or "."
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

try:
    import networkx as nx
except ImportError:
    print("ERROR: networkx not installed. Run: pip install --user networkx pyvis")
    sys.exit(1)

# ─── Configuration ────────────────────────────────────────────────────────────

BRAIN_DIR = Path.home() / ".claude"
NEURAL_MAP = BRAIN_DIR / "neural_map.json"
NEURAL_ACTIVITY = BRAIN_DIR / "neural_activity.json"
VIZ_OUTPUT = BRAIN_DIR / "connectome.html"

# Stop words — MUST stay in sync with generate_neural_map.py STOP_WORDS.
# Divergence here means index-time and query-time tokenize the same prompt differently,
# silently degrading cosine similarity. Includes Spanish stopwords (the brain has bilingual content).
_STOP_EN = (
    "a an the and or but is are was were be been being have has had do does did "
    "will would could should may might shall can this that these those it its "
    "you your we our they their he she him her them what which who whom how "
    "when where why all each every some any no not only just more most very "
    "also about above after again against between into through during before "
    "after from up down in out on off over under at by for with to of as if "
    "then than too so such both well back get got make made use used using "
    "one two three four five new first last many much long even still way "
    "need want like know think see look find give take come go say said says "
    "keep let put run set try turn move work show help call ask tell seem feel "
    "leave start begin end open close change follow play create add include "
    "provide ensure consider note important however example based "
    "specific different another without within across along since while "
    "because although though whether before here there "
    "where how what when why who which type types level levels number amount "
    "high low key keys based focus value values system systems process "
    "note implement approach best better result results case cases tool tools "
    "check set sets line lines code file files data point points step steps "
    "sure things thing part parts something anything nothing everything section "
    "area areas etc table tables list lists item items option options "
    "markdown heading bold text content format output input"
)
_STOP_ES = (
    "de la el los las un una unos unas en y o pero es son era ser sido fue fueron "
    "está están estaba estaban este esta estos estas ese esa esos esas eso "
    "su sus mi mis tu tus le les lo nos vos por para con sin contra sobre "
    "entre hasta desde según sí no más menos solo sólo mucho muy poco mismo "
    "todo todos todas otro otra otros otras cada varios varias casi ya aún todavía "
    "qué cómo cuándo dónde cuál quién donde cuando como cual quien "
    "hace hizo hay hubo habrá había también ante antes después durante luego "
    "porque pues aunque mientras si bien aquí ahí allí allá esto ello"
)
STOP_WORDS = None  # set below, after _folded_stops is defined

def _fold(text):
    """NFKD-fold: drop combining marks. Idempotent."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _folded_stops(words):
    """Every stop word PLUS its folded form.

    Folding the corpus without folding this list is a trap that bites in the
    worst direction: an accented stop word ("que" with its accent) can never be
    matched again, so it stops being filtered, and its folded form walks into
    the vocabulary as a high-frequency term. Measured before this fix: "que"
    entered the index with idf 2.502 and drove every one of the 9 synapses the
    accent fix added. A stop list must be folded in lockstep with the tokenizer,
    and identically in both files, since their equality is what keeps the index
    and the query aligned.
    """
    out = set()
    for w in words:
        out.add(w)
        out.add(_fold(w))
    return frozenset(out)


STOP_WORDS = _folded_stops((_STOP_EN + " " + _STOP_ES).split())



# ─── Graph Builder ────────────────────────────────────────────────────────────

def load_connectome():
    """Load neural_map.json and return raw data."""
    if not NEURAL_MAP.exists():
        print(f"ERROR: {NEURAL_MAP} not found. Run generate_neural_map.py first.")
        sys.exit(1)
    return json.loads(NEURAL_MAP.read_text(encoding="utf-8"))


# ─── Hebbian Learning Module ──────────────────────────────────────────────────

def load_neural_activity():
    """Load co-activation log from neural_activity.json."""
    if not NEURAL_ACTIVITY.exists():
        return {"co_activation_matrix": {}, "total_sessions": 0}
    return json.loads(NEURAL_ACTIVITY.read_text(encoding="utf-8"))


def compute_hebbian_boosters(activity_data, min_coactivations=3):
    """
    Compute Hebbian boosters from session history with time decay + success signals.

    Time decay: each session's contribution decays as e^(-lambda * age_days).
      lambda=0.01 -> half-life ~69 days. Recent sessions dominate; stale ones fade.
    Negative signals: failed sessions (success=false) subtract 0.5 per pair
      instead of adding 1. One failure doesn't kill a strong pattern.
    Cold start: if total < 50 sessions, apply 50% dampening (trust TF-IDF more).
    Fallback: if no sessions array exists, uses raw co_activation_matrix (no decay).
    """
    sessions = activity_data.get("sessions", [])
    stats = activity_data.get("statistics", {})
    total_sessions = stats.get("total_sessions", len(sessions))

    if not sessions:
        return _boosters_from_matrix(activity_data, min_coactivations, total_sessions)

    from datetime import datetime as _dt, timezone as _tz
    from itertools import combinations

    now = _dt.now(_tz.utc)
    decay_lambda = 0.01       # half-life ~69 days
    negative_weight = 0.5     # failed sessions subtract this fraction

    decayed_counts = Counter()

    for session in sessions:
        ts_str = session.get("timestamp", "")
        success = session.get("success", True)
        activated = session.get("activated_nodes", [])

        if len(activated) < 2:
            continue

        # Parse timestamp and compute age in days
        try:
            ts = _dt.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_tz.utc)
            age_days = (now - ts).total_seconds() / 86400
        except (ValueError, TypeError):
            age_days = 0  # unparseable -> treat as fresh

        decay = math.exp(-decay_lambda * max(age_days, 0))
        signal = decay if success else -negative_weight * decay

        for pair in combinations(sorted(activated), 2):
            pair_key = f"{pair[0]}::{pair[1]}"
            decayed_counts[pair_key] += signal

    # Convert decayed counts to boosters
    boosters = {}
    for pair_key, count in decayed_counts.items():
        if count < min_coactivations:
            continue
        boost = min(0.5, (count - min_coactivations) / 100.0)
        if total_sessions < 50:
            boost *= 0.5
        if boost > 0:
            boosters[pair_key] = boost

    return boosters


def _boosters_from_matrix(activity_data, min_coactivations, total_sessions):
    """Fallback: compute boosters from raw co_activation_matrix (no decay)."""
    matrix = activity_data.get("co_activation_matrix", {})
    boosters = {}
    for pair_key, count in matrix.items():
        if pair_key.startswith("_"):
            continue
        count = int(count)
        if count < min_coactivations:
            continue
        boost = min(0.5, (count - min_coactivations) / 100.0)
        if total_sessions < 50:
            boost *= 0.5
        if boost > 0:
            boosters[pair_key] = boost
    return boosters


def apply_hebbian_weights(G, boosters):
    """Apply Hebbian boosters to graph edges."""
    for u, v, d in G.edges(data=True):
        pair_key = f"{u}::{v}"
        boost = boosters.get(pair_key, 0)
        if boost > 0:
            original_weight = d.get("weight", 0.1)
            new_weight = original_weight * (1 + boost)
            d["weight"] = min(1.0, new_weight)  # Cap at 1.0
            d["hebbian_boost"] = boost


def log_session(activated_nodes, command, success=True):
    """Record co-activations from this session to neural_activity.json (atomic + locked)."""
    if not activated_nodes or len(activated_nodes) < 2:
        return  # No logging for trivial sessions

    from itertools import combinations
    pairs = list(combinations(sorted(activated_nodes), 2))
    timestamp = _dt.now(_tz.utc).isoformat()
    lock_path = NEURAL_ACTIVITY.with_suffix(".lock")

    with _file_lock(lock_path):
        # Load current activity (under lock — prevents read-modify-write races)
        if NEURAL_ACTIVITY.exists():
            activity = json.loads(NEURAL_ACTIVITY.read_text(encoding="utf-8"))
        else:
            activity = {
                "metadata": {"description": "Hebbian Learning log", "version": "1.0"},
                "sessions": [],
                "co_activation_matrix": {},
                "statistics": {"total_sessions": 0, "total_co_activations": 0, "unique_pairs": 0}
            }

        activity["sessions"].append({
            "timestamp": timestamp,
            "command": command,
            "activated_nodes": activated_nodes,
            "pair_count": len(pairs),
            "success": success
        })

        for pair in pairs:
            pair_key = f"{pair[0]}::{pair[1]}"
            activity["co_activation_matrix"][pair_key] = activity["co_activation_matrix"].get(pair_key, 0) + 1

        activity["statistics"]["total_sessions"] += 1
        activity["statistics"]["total_co_activations"] += len(pairs)
        activity["statistics"]["unique_pairs"] = len(activity["co_activation_matrix"])

        if activity["co_activation_matrix"]:
            strongest = max(activity["co_activation_matrix"].items(), key=lambda x: x[1])
            activity["statistics"]["strongest_pair"] = f"{strongest[0]} (count={strongest[1]})"

        # Rotating log: cap at 1000 sessions to bound file size.
        # NOTE: This is a known data-loss surface (see HEBBIAN_LEARNING.md). The plan is to migrate
        # to an append-only NDJSON log under data/bronze/sessions-YYYY-MM.ndjson and treat
        # co_activation_matrix as a derived view regenerated by generate_neural_map.py.
        if len(activity["sessions"]) > 1000:
            activity["sessions"] = activity["sessions"][-1000:]

        _atomic_write_json(NEURAL_ACTIVITY, activity)


def mark_session_outcome(timestamp_iso, success):
    """Update the success flag on the most recent session matching the given timestamp.

    Closes the 3D Diligent → Hebbian reward loop: gate-check writes back PASS/FAIL
    so the negative-weight machinery in generate_neural_map.py actually receives signal.
    Returns True if a session was updated.
    """
    if not NEURAL_ACTIVITY.exists():
        return False
    lock_path = NEURAL_ACTIVITY.with_suffix(".lock")
    with _file_lock(lock_path):
        activity = json.loads(NEURAL_ACTIVITY.read_text(encoding="utf-8"))
        for sess in reversed(activity.get("sessions", [])):
            if sess.get("timestamp") == timestamp_iso:
                sess["success"] = bool(success)
                _atomic_write_json(NEURAL_ACTIVITY, activity)
                return True
        return False


def build_graph(data, use_hebbian=True):
    """Build a weighted NetworkX graph from the connectome data."""
    G = nx.Graph()

    # Add neuron nodes (agents)
    for neuron in data.get("neurons", []):
        G.add_node(neuron["id"], **{
            "type": "agent",
            "name": neuron.get("name", ""),
            "emoji": neuron.get("emoji", ""),
            "division": neuron.get("division", ""),
            "triggers": neuron.get("triggers", []),
            "synapse_count": neuron.get("stats", {}).get("synapse_count", 0),
        })

        # Agent → Skill edges
        for skill_id, weight in neuron.get("synapses", {}).items():
            G.add_edge(neuron["id"], skill_id, weight=weight, edge_type="agent_skill")

        # Agent → Agent edges
        for neighbor_id, weight in neuron.get("neighbors", {}).items():
            if not G.has_edge(neuron["id"], neighbor_id):
                G.add_edge(neuron["id"], neighbor_id, weight=weight, edge_type="agent_agent")

    # Add synapse nodes (skills)
    for synapse in data.get("synapses", []):
        if not G.has_node(synapse["id"]):
            G.add_node(synapse["id"], **{
                "type": "skill",
                "name": synapse.get("name", ""),
                "description": synapse.get("description", ""),
            })
        else:
            # Update attributes if node already exists from edge addition
            G.nodes[synapse["id"]].update({
                "type": "skill",
                "name": synapse.get("name", ""),
                "description": synapse.get("description", ""),
            })

        # Skill → Skill edges
        for cluster_nb, weight in synapse.get("cluster_neighbors", {}).items():
            if not G.has_edge(synapse["id"], cluster_nb):
                G.add_edge(synapse["id"], cluster_nb, weight=weight, edge_type="skill_skill")

    # Apply Hebbian boosters if requested
    if use_hebbian:
        activity_data = load_neural_activity()
        boosters = compute_hebbian_boosters(activity_data)
        if boosters:
            apply_hebbian_weights(G, boosters)

    return G


# ─── Tokenizer (lightweight, matches generator) ──────────────────────────────

def tokenize_query(text):
    """Tokenize a query string for matching against node content.

    MUST fold accents exactly like the generator. Both sides tokenize
    independently, and a query that produces "sesi" can never match an index
    that stores "sesion". Measured while fixing the generator: folding the build
    side ALONE turned a working Spanish query into zero hits, because the two
    sides stopped agreeing. Consistently wrong beat inconsistently right.

    TWO tokenizers must agree, and only two: this one and
    generate_neural_map.tokenize. They are the pair that writes and reads
    neural_map.json, so a divergence between them is a silent zero-hit recall.
    connectome-heartbeat.py imports this function, so it folds transitively.

    Other tokenizers in the brain (delegate-check, brain-memory-recall.py,
    gap-capture.py, goal-anchor.py) tokenize their own text on BOTH sides and
    never read neural_map.json, so they cannot desynchronize from it.
    brain-memory-recall.py in particular does not mutilate: its regex already
    admits accented characters. The duplication is still a standing hazard and
    wants a shared module; that is a separate change.
    """
    text = _fold(text)
    text = re.sub(r"[#*\`\[\](){}|>_~=\-]", " ", text.lower())
    words = re.findall(r"[a-z][a-z0-9]{2,}(?:-[a-z0-9]+)*", text)
    return [w for w in words if w not in STOP_WORDS and len(w) >= 3]


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_stats(G, data):
    """Print graph statistics."""
    cap = data.get("capacity", {})
    print("=" * 60)
    print("OCTOPUS CONNECTOME — GRAPH STATISTICS")
    print("=" * 60)

    agents = [n for n, d in G.nodes(data=True) if d.get("type") == "agent"]
    skills = [n for n, d in G.nodes(data=True) if d.get("type") == "skill"]

    print(f"\n  Nodes:        {G.number_of_nodes():>6}")
    print(f"    Agents:     {len(agents):>6}")
    print(f"    Skills:     {len(skills):>6}")
    print(f"  Edges:        {G.number_of_edges():>6}")
    print(f"  Density:      {nx.density(G):>9.4f}")
    print(f"  Connected:    {'YES' if nx.is_connected(G) else 'NO'}")

    if nx.is_connected(G):
        print(f"  Diameter:     {nx.diameter(G):>6}")
        print(f"  Avg path len: {nx.average_shortest_path_length(G):>8.2f}")
    else:
        components = list(nx.connected_components(G))
        print(f"  Components:   {len(components):>6}")
        largest = max(components, key=len)
        print(f"  Largest comp: {len(largest):>6} nodes")

    print(f"\n  Vocabulary:   {cap.get('vocabulary_size', '?'):>6} TF-IDF terms")
    print(f"  Hebbian:      {cap.get('hebbian_patterns', 0):>6} co-activation patterns")


def cmd_gods(G, top_n=20):
    """Find god nodes — highest betweenness centrality."""
    print("=" * 60)
    print(f"GOD NODES — Top {top_n} by Betweenness Centrality")
    print("=" * 60)
    print("  (Nodes that sit on the most shortest paths — the brain's highways)\n")

    # Betweenness centrality (which nodes are bridges)
    bc = nx.betweenness_centrality(G, weight="weight")

    # Degree centrality (raw connection count)
    dc = nx.degree_centrality(G)

    # Combine into ranked list
    combined = {}
    for node in G.nodes():
        combined[node] = {
            "betweenness": bc.get(node, 0),
            "degree": dc.get(node, 0),
            "connections": G.degree(node),
            "type": G.nodes[node].get("type", "?"),
            "name": G.nodes[node].get("name", node),
            "emoji": G.nodes[node].get("emoji", ""),
        }

    ranked = sorted(combined.items(), key=lambda x: x[1]["betweenness"], reverse=True)

    print(f"  {'#':<4} {'Type':<7} {'Node':<45} {'Between.':<10} {'Conns':<6}")
    print(f"  {'─'*4} {'─'*7} {'─'*45} {'─'*10} {'─'*6}")

    for i, (node_id, info) in enumerate(ranked[:top_n], 1):
        emoji = info["emoji"] + " " if info["emoji"] else ""
        t = "AGENT" if info["type"] == "agent" else "SKILL"
        name = f"{emoji}{info['name']}"[:44]
        print(f"  {i:<4} {t:<7} {name:<45} {info['betweenness']:.6f}  {info['connections']:<6}")

    # Summary
    agent_gods = [n for n, i in ranked[:top_n] if i["type"] == "agent"]
    skill_gods = [n for n, i in ranked[:top_n] if i["type"] == "skill"]
    print(f"\n  God agents: {len(agent_gods)} | God skills: {len(skill_gods)}")


def cmd_dead(G):
    """Dead cells — orphan/leaf nodes the graph no longer connects (prune candidates).

    The inverse of cmd_gods: instead of the highest-betweenness highways, surface
    the nodes with (near-)zero degree — skills/agents nothing routes to and that
    route to nothing. degree-0 = dead (isolated tissue); degree-1 = a dying leaf
    (one thread left). Read-only: it SUGGESTS the prune, never runs it — the
    operator approves the cut (fail-closed, same stance as merges). A brand-new,
    not-yet-linked node also shows degree-0, so an orphan is a *candidate*, not a
    verdict: an unlit neuron gets an edge, dead tissue gets removed.
    """
    print("=" * 60)
    print("DEAD CELLS — orphan/leaf nodes (prune candidates)")
    print("=" * 60)
    print("  (Inverse of `gods`: degree-0 = dead/isolated, degree-1 = dying leaf)")
    print("  Read-only — SUGGESTS prune, never runs it. Operator approves.\n")

    dead, dying = [], []
    for node in G.nodes():
        deg = G.degree(node)
        if deg == 0:
            dead.append(node)
        elif deg == 1:
            dying.append(node)

    def _info(node):
        t = G.nodes[node].get("type", "?")
        name = G.nodes[node].get("name", node) or node
        if t == "agent":
            # Agents are nested by division (agents/<division>/<id>.md); the node
            # id is just the stem. Glob for the real path so the "file gone" check
            # and the suggested prune target are TRUE, not a flat no-op guess.
            guess = next(BRAIN_DIR.glob(f"agents/**/{node}.md"),
                         BRAIN_DIR / "agents" / f"{node}.md")
        else:
            guess = BRAIN_DIR / "skills" / node / "SKILL.md"
        return t, name, guess

    for label, bucket in (("DEAD (degree 0)", dead), ("DYING (degree 1)", dying)):
        print(f"  {label}: {len(bucket)}")
        for node in sorted(bucket):
            t, name, guess = _info(node)
            missing = "" if guess.exists() else "  ⚠ file already gone"
            rel = guess.relative_to(BRAIN_DIR) if str(guess).startswith(str(BRAIN_DIR)) else guess
            print(f"    • {t:<5} {str(name)[:38]:<38} {rel}{missing}")
        print()

    # Machine RECEIPT — quote verbatim in the Provenance `Graph:` field.
    line = (f"DEAD-SCAN connectome dead={len(dead)} dying={len(dying)} "
            f"→ {'suggest-prune (operator approves)' if (dead or dying) else 'clean'}")
    print(f"📋 RECEIPT:\n  {line}")

    if dead:
        print("\n  ☠ Suggested prune (review first, NEVER auto-run):")
        for node in sorted(dead):
            t, _, guess = _info(node)
            target = guess.parent if t == "skill" else guess
            print(f"    rm -rf {target}")
        print("    python3 scripts/generate_neural_map.py   # rebuild the graph after")


def cmd_path(G, node_a, node_b):
    """Find shortest path between two nodes."""
    # Fuzzy match node IDs
    a = _fuzzy_match(G, node_a)
    b = _fuzzy_match(G, node_b)

    if not a or not b:
        return

    print(f"\n  Shortest path: {a} → {b}")
    print("  " + "─" * 50)

    try:
        path = nx.shortest_path(G, a, b, weight=_inverse_weight)
        total_weight = 0
        for i in range(len(path) - 1):
            w = G[path[i]][path[i+1]].get("weight", 0)
            et = G[path[i]][path[i+1]].get("edge_type", "?")
            nt = G.nodes[path[i]].get("type", "?")
            emoji = G.nodes[path[i]].get("emoji", "")
            name = G.nodes[path[i]].get("name", path[i])
            print(f"  {emoji} [{nt}] {name}")
            print(f"     ──({et}: {w:.4f})──▶")
            total_weight += w

        # Last node
        last = path[-1]
        emoji = G.nodes[last].get("emoji", "")
        name = G.nodes[last].get("name", last)
        nt = G.nodes[last].get("type", "?")
        print(f"  {emoji} [{nt}] {name}")
        print(f"\n  Hops: {len(path)-1} | Total weight: {total_weight:.4f}")
        
        # Return path for Hebbian logging
        return path

    except nx.NetworkXNoPath:
        print(f"  NO PATH between {a} and {b} (different components)")
        return None
    except nx.NodeNotFound as e:
        print(f"  ERROR: {e}")
        return None


def _cosine_sim(vec_a, vec_b):
    """Cosine similarity between two sparse dicts."""
    if not vec_a or not vec_b:
        return 0.0
    shared = set(vec_a) & set(vec_b)
    if not shared:
        return 0.0
    dot = sum(vec_a[k] * vec_b[k] for k in shared)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values()))
    mag_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def cmd_query(G, data, query_text, top_n=10):
    """Find best agents + skills for a task description using TF-IDF cosine similarity."""
    print(f"\n  Query: \"{query_text}\"")
    print("  " + "─" * 50)

    tokens = tokenize_query(query_text)
    if not tokens:
        print("  No meaningful tokens found in query.")
        return

    print(f"  Tokens: {', '.join(tokens)}")

    # Build query TF-IDF vector using stored IDF
    tfidf_index = data.get("tfidf_index", {})
    stored_idf = tfidf_index.get("idf", {})
    stored_vectors = tfidf_index.get("vectors", {})

    if stored_idf and stored_vectors:
        # TF-IDF cosine similarity mode
        print("  Method: TF-IDF cosine similarity")
        from collections import Counter
        # Build bigrams from query tokens (matching generator's vocabulary)
        bigrams = []
        for i in range(len(tokens) - 1):
            if tokens[i] != tokens[i + 1]:
                bigrams.append(f"{tokens[i]}_{tokens[i+1]}")
        all_terms = tokens + bigrams
        tf = Counter(all_terms)
        total = len(all_terms) if all_terms else 1
        query_vec = {}
        for term, count in tf.items():
            if term in stored_idf:
                query_vec[term] = (count / total) * stored_idf[term]

        scores = {}
        for doc_id, doc_vec in stored_vectors.items():
            sim = _cosine_sim(query_vec, doc_vec)
            if sim > 0.001:
                # Map doc_id (agent:xxx or skill:xxx) to node_id (xxx)
                node_id = doc_id.split(":", 1)[1] if ":" in doc_id else doc_id
                if G.has_node(node_id):
                    scores[node_id] = sim
    else:
        # Fallback: keyword matching (no TF-IDF index available)
        print("  Method: keyword matching (no TF-IDF index — regenerate connectome)")
        scores = {}
        for node_id, attrs in G.nodes(data=True):
            score = 0
            node_text = " ".join([
                attrs.get("name", ""),
                " ".join(attrs.get("triggers", [])),
                attrs.get("description", ""),
                node_id.replace("-", " "),
            ])
            # Fold the HAYSTACK too. The tokens were folded, so a raw haystack
            # loses every accented match: folded "canonico" does not appear in
            # a description that spells it with the accent.
            node_text = _fold(node_text).lower()

            for token in tokens:
                if token in node_text:
                    score += 1
                for word in node_text.split():
                    if token in word and token != word:
                        score += 0.3

            if score > 0:
                scores[node_id] = score

    if not scores:
        print("  No matching nodes found.")
        return

    ranked = sorted(scores.items(), key=lambda x: -x[1])

    # Show results grouped by type
    agents = [(n, s) for n, s in ranked if G.nodes[n].get("type") == "agent"]
    skills = [(n, s) for n, s in ranked if G.nodes[n].get("type") == "skill"]

    if agents:
        print(f"\n  AGENTS (best match → least match):")
        for node_id, score in agents[:top_n]:
            emoji = G.nodes[node_id].get("emoji", "")
            name = G.nodes[node_id].get("name", node_id)
            div = G.nodes[node_id].get("division", "")
            conns = G.degree(node_id)
            print(f"    {emoji} {name} ({div}) — score: {score:.1f}, connections: {conns}")

            # Show top connected skills for this agent
            skill_neighbors = [
                (nb, G[node_id][nb].get("weight", 0))
                for nb in G.neighbors(node_id)
                if G.nodes.get(nb, {}).get("type") == "skill"
            ]
            skill_neighbors.sort(key=lambda x: -x[1])
            if skill_neighbors[:3]:
                skills_str = ", ".join(f"{s[0]}({s[1]:.2f})" for s in skill_neighbors[:3])
                print(f"      └─ top skills: {skills_str}")

    if skills:
        print(f"\n  SKILLS (best match → least match):")
        for node_id, score in skills[:top_n]:
            name = G.nodes[node_id].get("name", node_id)
            conns = G.degree(node_id)
            print(f"    {name} — score: {score:.1f}, connections: {conns}")

    # Return ONLY the top-K activated nodes for Hebbian logging.
    # Returning the full scored set (often 50–100 nodes) produced ~4,800 co-activation
    # pairs per query and collapsed the Hebbian signal to "everything connects to everything".
    # Cap at 5 to keep the learning signal sharp; combine top agents + top skills.
    HEBBIAN_TOP_K = 5
    top_pairs = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:HEBBIAN_TOP_K]
    return [node_id for node_id, _ in top_pairs]


def cmd_impact(G, node_id, max_hops=2):
    """Show impact radius from a node — what's within N hops."""
    node = _fuzzy_match(G, node_id)
    if not node:
        return

    print(f"\n  Impact radius from: {node} (max {max_hops} hops)")
    print("  " + "─" * 50)

    # BFS by hop level
    visited = {node: 0}
    queue = [node]

    while queue:
        current = queue.pop(0)
        current_hop = visited[current]
        if current_hop >= max_hops:
            continue
        for neighbor in G.neighbors(current):
            if neighbor not in visited:
                visited[neighbor] = current_hop + 1
                queue.append(neighbor)

    # Group by hop
    by_hop = {}
    for n, hop in visited.items():
        if n == node:
            continue
        by_hop.setdefault(hop, []).append(n)

    total = 0
    for hop in sorted(by_hop.keys()):
        nodes_at_hop = by_hop[hop]
        agents = [n for n in nodes_at_hop if G.nodes.get(n, {}).get("type") == "agent"]
        skills = [n for n in nodes_at_hop if G.nodes.get(n, {}).get("type") == "skill"]
        total += len(nodes_at_hop)
        print(f"\n  Hop {hop}: {len(nodes_at_hop)} nodes ({len(agents)} agents, {len(skills)} skills)")
        for n in sorted(nodes_at_hop)[:15]:
            emoji = G.nodes[n].get("emoji", "")
            name = G.nodes[n].get("name", n)
            ntype = G.nodes[n].get("type", "?")
            w = G[node].get(n, {}).get("weight", "") if hop == 1 else ""
            w_str = f" (w={w:.4f})" if w else ""
            print(f"    {emoji} [{ntype}] {name}{w_str}")
        if len(nodes_at_hop) > 15:
            print(f"    ... and {len(nodes_at_hop) - 15} more")

    print(f"\n  Total impact: {total} nodes within {max_hops} hops")


def cmd_communities(G, top_n=10):
    """Detect communities using Louvain algorithm."""
    print("=" * 60)
    print("COMMUNITY DETECTION — Louvain Algorithm")
    print("=" * 60)

    communities = nx.community.louvain_communities(G, seed=42, resolution=1.0)

    print(f"\n  Communities found: {len(communities)}")
    print(f"  Modularity: {nx.community.modularity(G, communities):.4f}")

    # Sort by size
    sorted_comms = sorted(enumerate(communities), key=lambda x: -len(x[1]))

    for i, (comm_id, members) in enumerate(sorted_comms[:top_n]):
        agents = [m for m in members if G.nodes.get(m, {}).get("type") == "agent"]
        skills = [m for m in members if G.nodes.get(m, {}).get("type") == "skill"]

        print(f"\n  Community {i+1} ({len(members)} nodes: {len(agents)} agents, {len(skills)} skills)")

        # Find the "hub" of this community (highest degree within community)
        subG = G.subgraph(members)
        if subG.nodes():
            hub = max(subG.degree(), key=lambda x: x[1])
            hub_name = G.nodes[hub[0]].get("name", hub[0])
            hub_emoji = G.nodes[hub[0]].get("emoji", "")
            print(f"    Hub: {hub_emoji} {hub_name} ({hub[1]} intra-community connections)")

        # Show sample members
        sample_agents = sorted(agents, key=lambda a: subG.degree(a), reverse=True)[:5]
        sample_skills = sorted(skills, key=lambda s: subG.degree(s), reverse=True)[:5]

        if sample_agents:
            agent_names = [f"{G.nodes[a].get('emoji','')} {G.nodes[a].get('name', a)}" for a in sample_agents]
            print(f"    Agents: {', '.join(agent_names)}")
        if sample_skills:
            skill_names = [G.nodes[s].get("name", s) for s in sample_skills]
            print(f"    Skills: {', '.join(skill_names)}")

    # Cohesion summary
    total_intra = sum(
        1 for comm in communities
        for u, v in G.subgraph(comm).edges()
    )
    total_edges = G.number_of_edges()
    print(f"\n  Intra-community edges: {total_intra}/{total_edges} ({total_intra/max(total_edges,1)*100:.1f}%)")


def cmd_4d(G, data, task_text):
    """Full 4D pre-flight analysis via graph traversal."""
    print("=" * 60)
    print("4D PRE-FLIGHT — Graph-Powered Nervous System")
    print("=" * 60)
    print(f"  Task: {task_text}\n")

    tokens = tokenize_query(task_text)

    # ── 1D DESCRIBE: Context from graph ──
    print("  1D DESCRIBE — Graph Context")
    print("  " + "─" * 40)

    # Find matching nodes
    scores = {}
    for node_id, attrs in G.nodes(data=True):
        node_text = " ".join([
            attrs.get("name", ""),
            " ".join(attrs.get("triggers", [])),
            attrs.get("description", ""),
            node_id.replace("-", " "),
        ])
        node_text = _fold(node_text).lower()  # folded tokens need a folded haystack
        score = sum(1 for t in tokens if t in node_text)
        if score > 0:
            scores[node_id] = score

    _opinion_re_4d = re.compile(
        r"\b("
        r"qu[eé]\s+opinas|tu\s+opini[oó]n|qu[eé]\s+crees|t[uú]\s+qu[eé]"
        r"|recomiendas|recomi[eé]ndame|qu[eé]\s+recomiendas|sugieres"
        r"|qu[eé]\s+prefieres"
        r"|what\s+do\s+you\s+think|your\s+opinion|your\s+take"
        r"|do\s+you\s+recommend|would\s+you\s+recommend"
        r"|should\s+i|what\s+would\s+you|thoughts\?|your\s+call"
        r")\b",
        re.IGNORECASE,
    )
    _is_opinion = bool(_opinion_re_4d.search(task_text))

    if not scores:
        print("    No matching nodes. Task is outside the connectome's knowledge.")
        # Emit a Decision even on no-match so the output is consistent with the non-empty path.
        if _is_opinion:
            print("\n    Decision: SELF")
        else:
            print("\n    Decision: LOAD")
        return

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top_agents = [(n, s) for n, s in ranked if G.nodes[n].get("type") == "agent"][:5]
    top_skills = [(n, s) for n, s in ranked if G.nodes[n].get("type") == "skill"][:5]

    print(f"    Tokens: {', '.join(tokens)}")
    print(f"    Matching nodes: {len(scores)} ({len(top_agents)} agents, {len(top_skills)} skills)")

    # ── 2D DELEGATE: Shortest path routing ──
    print("\n  2D DELEGATE — Graph Routing")
    print("  " + "─" * 40)

    if top_agents:
        best_agent = top_agents[0][0]
        agent_info = G.nodes[best_agent]
        print(f"    Best agent: {agent_info.get('emoji','')} {agent_info.get('name', best_agent)}")
        print(f"    Division:   {agent_info.get('division', '?')}")
        print(f"    Score:      {top_agents[0][1]}")

        # Find skills reachable from best agent
        agent_skills = [
            (nb, G[best_agent][nb].get("weight", 0))
            for nb in G.neighbors(best_agent)
            if G.nodes.get(nb, {}).get("type") == "skill"
        ]
        agent_skills.sort(key=lambda x: -x[1])

        if agent_skills:
            print(f"    Skills to load ({len(agent_skills)} connected):")
            for skill_id, w in agent_skills[:5]:
                sname = G.nodes[skill_id].get("name", skill_id)
                marker = " ← DIRECT MATCH" if skill_id in dict(top_skills) else ""
                print(f"      {sname} (w={w:.4f}){marker}")

        # If best skill is NOT connected to best agent, show the path
        if top_skills:
            best_skill = top_skills[0][0]
            if not G.has_edge(best_agent, best_skill):
                try:
                    path = nx.shortest_path(G, best_agent, best_skill, weight=_inverse_weight)
                    print(f"\n    Path to best skill ({best_skill}):")
                    print(f"      {' → '.join(path)} ({len(path)-1} hops)")
                except nx.NetworkXNoPath:
                    print(f"\n    WARNING: No path from {best_agent} to {best_skill}")

    # SELF only on explicit opinion request with no graph signal; else default to LOAD (connector bias)
    if _is_opinion and not top_agents and not top_skills:
        decision = "SELF"
    elif top_agents and top_agents[0][1] >= 2:
        decision = "ACTIVATE"
    elif top_agents or top_skills:
        decision = "LOAD"
    else:
        decision = "LOAD"  # no graph match → still LOAD, not SELF
    print(f"\n    Decision: {decision}")

    # ── 3D DILIGENT: Impact preview ──
    print("\n  3D DILIGENT — Impact Preview")
    print("  " + "─" * 40)

    if top_agents:
        best = top_agents[0][0]
        hop1 = list(G.neighbors(best))
        hop2 = set()
        for h1 in hop1:
            for h2 in G.neighbors(h1):
                if h2 != best and h2 not in hop1:
                    hop2.add(h2)
        print(f"    From {best}:")
        print(f"      Hop 1: {len(hop1)} direct connections")
        print(f"      Hop 2: {len(hop2)} indirect connections")
        print(f"      Total blast radius: {len(hop1) + len(hop2)} nodes")

    # ── 4D DISCLOSE: Centrality context ──
    print("\n  4D DISCLOSE — Centrality Context")
    print("  " + "─" * 40)

    if top_agents:
        best = top_agents[0][0]
        bc = nx.betweenness_centrality(G, weight="weight")
        dc = nx.degree_centrality(G)

        rank_bc = sorted(bc.items(), key=lambda x: -x[1])
        rank_pos = next((i for i, (n, _) in enumerate(rank_bc) if n == best), -1)

        print(f"    {best}:")
        print(f"      Betweenness centrality: {bc.get(best, 0):.6f} (rank #{rank_pos+1}/{len(bc)})")
        print(f"      Degree centrality:      {dc.get(best, 0):.6f}")
        print(f"      Is hub: {'YES' if rank_pos < 20 else 'no'}")

        # Community membership
        communities = nx.community.louvain_communities(G, seed=42)
        for i, comm in enumerate(communities):
            if best in comm:
                comm_agents = [m for m in comm if G.nodes.get(m, {}).get("type") == "agent"]
                comm_skills = [m for m in comm if G.nodes.get(m, {}).get("type") == "skill"]
                print(f"      Community: #{i+1} ({len(comm)} nodes: {len(comm_agents)} agents, {len(comm_skills)} skills)")
    
    # Collect all activated nodes for Hebbian logging
    activated_nodes = [n for n, _ in ranked[:10]]
    return activated_nodes if activated_nodes else None


def cmd_viz(G, output_path=None):
    """Generate interactive HTML visualization."""
    try:
        from pyvis.network import Network
    except ImportError:
        print("ERROR: pyvis not installed. Run: pip install --user pyvis")
        return

    output = Path(output_path) if output_path else VIZ_OUTPUT
    print(f"  Generating interactive visualization → {output}")

    # Color scheme
    COLORS = {
        "agent": {
            "engineering": "#4CAF50",
            "design": "#E91E63",
            "marketing": "#FF9800",
            "sales": "#2196F3",
            "product": "#9C27B0",
            "testing": "#F44336",
            "support": "#607D8B",
            "specialized": "#795548",
            "academic": "#3F51B5",
            "game-development": "#00BCD4",
            "spatial-computing": "#009688",
            "project-management": "#FF5722",
            "paid-media": "#FFC107",
        },
        "skill": "#37474F",
    }

    net = Network(
        height="900px",
        width="100%",
        bgcolor="#1a1a2e",
        font_color="#e0e0e0",
        directed=False,
        select_menu=True,
        filter_menu=True,
    )

    net.set_options("""{
        "physics": {
            "forceAtlas2Based": {
                "gravitationalConstant": -80,
                "centralGravity": 0.01,
                "springLength": 150,
                "springConstant": 0.02,
                "damping": 0.5
            },
            "solver": "forceAtlas2Based",
            "stabilization": {"iterations": 200}
        },
        "nodes": {
            "font": {"size": 12, "face": "monospace"},
            "borderWidth": 2
        },
        "edges": {
            "color": {"inherit": "both"},
            "smooth": {"type": "continuous"}
        },
        "interaction": {
            "hover": true,
            "tooltipDelay": 100
        }
    }""")

    # Compute centrality for sizing
    bc = nx.betweenness_centrality(G, weight="weight")
    max_bc = max(bc.values()) if bc else 1

    # Add nodes
    for node_id, attrs in G.nodes(data=True):
        ntype = attrs.get("type", "?")
        name = attrs.get("name", node_id)
        emoji = attrs.get("emoji", "")
        division = attrs.get("division", "")

        # Size based on centrality
        centrality = bc.get(node_id, 0)
        size = 8 + (centrality / max(max_bc, 0.001)) * 40

        if ntype == "agent":
            color = COLORS["agent"].get(division, "#546E7A")
            title = f"AGENT: {emoji} {name}\nDivision: {division}\nConnections: {G.degree(node_id)}\nCentrality: {centrality:.4f}"
            shape = "dot"
        else:
            color = COLORS["skill"]
            title = f"SKILL: {name}\nConnections: {G.degree(node_id)}\nCentrality: {centrality:.4f}"
            shape = "diamond"
            size = max(size * 0.7, 5)  # Skills slightly smaller

        label = f"{emoji} {name}" if emoji else name
        if len(label) > 30:
            label = label[:27] + "..."

        net.add_node(node_id, label=label, color=color, size=size,
                     title=title, shape=shape, group=division or "skill")

    # Add edges (sample if too many)
    edges = list(G.edges(data=True))
    if len(edges) > 3000:
        # Keep only edges with weight >= median
        weights = sorted([d.get("weight", 0) for _, _, d in edges], reverse=True)
        threshold = weights[min(3000, len(weights)-1)]
        edges = [(u, v, d) for u, v, d in edges if d.get("weight", 0) >= threshold]

    for u, v, d in edges:
        weight = d.get("weight", 0.1)
        edge_type = d.get("edge_type", "?")

        # Edge color by type
        if edge_type == "agent_skill":
            color = "rgba(100, 181, 246, 0.3)"
        elif edge_type == "agent_agent":
            color = "rgba(255, 183, 77, 0.3)"
        else:
            color = "rgba(129, 199, 132, 0.3)"

        width = max(0.5, weight * 3)
        net.add_edge(u, v, color=color, width=width,
                     title=f"{edge_type}: {weight:.4f}")

    net.save_graph(str(output))
    size_kb = output.stat().st_size / 1024
    print(f"  Written: {output} ({size_kb:.0f} KB)")
    print(f"  Open in browser: file://{output}")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _inverse_weight(u, v, d):
    """Invert weight for shortest path (higher weight = shorter distance)."""
    w = d.get("weight", 0.01)
    return 1.0 / max(w, 0.001)


def _fuzzy_match(G, query):
    """Fuzzy match a node ID."""
    query_lower = query.lower().strip()

    # Exact match
    if query_lower in G:
        return query_lower

    # Partial match
    candidates = [n for n in G.nodes() if query_lower in n.lower()]
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        # Fail-closed: never silently pick candidates[0]. Surface the ambiguity and
        # rank by string-similarity so the user sees the best hits first.
        import difflib
        ranked = sorted(
            candidates,
            key=lambda n: difflib.SequenceMatcher(None, query_lower, n.lower()).ratio(),
            reverse=True,
        )
        print(f"  ERROR: Ambiguous match for '{query}'. Disambiguate (top by similarity):")
        for c in ranked[:10]:
            name = G.nodes[c].get("name", c)
            print(f"    - {c} ({name})")
        return None
    else:
        # Try matching against name attribute
        for n, attrs in G.nodes(data=True):
            if query_lower in attrs.get("name", "").lower():
                return n

        print(f"  ERROR: No node matching '{query}'")
        return None


def brain_slug_or_none():
    try:
        from generate_memory_map import brain_project_slug
        return brain_project_slug()
    except Exception:
        return None


def cmd_memory(query_text, top_n=8, all_projects=False):
    """SEEK the brain's life-memories (memory_map.json), not skills/agents.

    Two graphs, two questions. `query` answers "which skill or agent knows this?"
    `memory` answers "have I already lived this / written this lesson down?" —
    the question that used to need a grep over 200+ files, which is a table scan
    with a stochastic hit rate and ~100x the tokens of a seek.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from generate_memory_map import load_index, score_prompt
    except Exception as e:
        print(f"  ERROR: memory index module unavailable ({e})")
        return None
    index = load_index()
    if not index:
        print("  No memory_map.json. Build it: python3 ~/.claude/scripts/generate_memory_map.py")
        return None

    # ARM ISOLATION applies to this verb too, and that is not obvious: CLAUDE.md
    # tells the agent to run it for recall, and the agent runs it from inside an
    # arm checkout. Unscoped, it happily printed another arm's memories into an
    # arm session — the one flow the octopus architecture forbids outright.
    #
    # Scope by CWD, the same way the harness names a project dir, plus the
    # central brain. `--all` is the operator's explicit override and says so out
    # loud; an agent must not reach for it to widen its own view.
    projects = None
    arm_slug = None
    if not all_projects:
        try:
            from generate_memory_map import brain_project_slug, project_slug
            central = brain_project_slug()
            # Walk UP to the nearest ancestor that really is a project dir. A
            # seek run from ARM/subdir/ would otherwise compute a slug that
            # matches nothing and silently drop the arm's own memories while the
            # scope line still claimed to include them.
            projects_root = Path(index.get("meta", {}).get("projects_root") or
                                 (Path.home() / ".claude" / "projects"))
            here = Path.cwd().resolve()
            for cand in [here, *here.parents]:
                slug = project_slug(cand)
                if (projects_root / slug).is_dir():
                    arm_slug = slug
                    break
                if cand == Path.home():
                    break
            projects = {central} | ({arm_slug} if arm_slug else set())
        except Exception:
            projects = None

    meta = index.get("meta", {})
    hits = score_prompt(index, query_text, top_n=top_n, min_score=0.04,
                        projects=projects)
    print(f"\n🧠 MEMORY SEEK — '{query_text}'")
    if all_projects:
        scope = "ALL projects (operator override)"
    elif arm_slug and arm_slug != brain_slug_or_none():
        scope = f"{arm_slug} + central brain"
    else:
        # Say what is TRUE. Claiming "this arm" when no project dir was found is
        # a quiet lie that reads as full coverage.
        scope = "central brain only (no project dir for this working directory)"
    print(f"   {meta.get('memories', '?')} memories indexed · generated "
          f"{meta.get('generated', '?')[:19]} · scope: {scope}")
    if not hits:
        print("   No memory above the floor. That is a real answer: the lesson")
        print("   may not exist yet, and writing it is the next step.")
        return None
    print()
    for score, key, node in hits:
        print(f"  {score:.3f}  [{node.get('type', '?')}] {node.get('title', key)}")
        desc = (node.get("description") or "").strip()
        if desc:
            print(f"          {desc[:150]}")
        print(f"          {node.get('path', '')}")
    # Neighbours of the top hit: the duplicate-detector. Before writing a NEW
    # memory, these are the ones it might be restating.
    top = hits[0][2]
    nb = top.get("neighbours") or []
    if nb:
        nodes = index.get("nodes", {})
        # Filter the NEIGHBOURS by the same allowlist. They are stored on the
        # node without regard to project, so printing them unfiltered reopened
        # the exact leak the hit list had just closed: an arm session was shown
        # another arm's memory through the back door. A scoped list with an
        # unscoped appendix is not scoped.
        rows = []
        for v in nb:
            n2 = nodes.get(v["key"], {})
            if projects is not None and n2.get("project") not in projects:
                continue
            rows.append((v["score"], n2.get("title", v["key"])))
            if len(rows) == 5:
                break
        if rows:
            print(f"\n  Vecinas de la primera ({top.get('title')}):")
            for score, title in rows:
                print(f"    {score:.3f}  {title}")
    return None


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    # No args or an explicit help flag: print usage + the full command list and
    # exit 0, without touching the connectome (help must work even if
    # neural_map.json is missing). delegate-check already supports -h/--help.
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        print("Commands: stats, gods, dead, path, query, memory, impact, communities, viz, 4d")
        return 0

    cmd = sys.argv[1].lower()

    # `memory` reads its OWN index, not neural_map.json. Dispatched before the
    # connectome loads so a missing/stale neural map never blocks a memory seek.
    if cmd == "memory":
        args = sys.argv[2:]
        all_projects = "--all" in args
        args = [a for a in args if a != "--all"]
        if not args:
            print('Usage: query_connectome.py memory "what am I trying to recall" [--all]')
            print('  Default scope: this working directory\'s arm + the central brain.')
            print('  --all lifts the arm filter. Operator use only; it crosses arms.')
            return 1
        cmd_memory(" ".join(args), all_projects=all_projects)
        return 0

    data = load_connectome()
    G = build_graph(data)
    activated_nodes = None

    if cmd == "stats":
        cmd_stats(G, data)

    elif cmd == "gods":
        top_n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        cmd_gods(G, top_n)

    elif cmd == "dead":
        cmd_dead(G)

    elif cmd == "path":
        if len(sys.argv) < 4:
            print("Usage: query_connectome.py path <nodeA> <nodeB>")
            return 1
        activated_nodes = cmd_path(G, sys.argv[2], sys.argv[3])

    elif cmd == "query":
        if len(sys.argv) < 3:
            print("Usage: query_connectome.py query \"task description\"")
            return 1
        activated_nodes = cmd_query(G, data, " ".join(sys.argv[2:]))

    elif cmd == "impact":
        if len(sys.argv) < 3:
            print("Usage: query_connectome.py impact <node> [--hops N]")
            return 1
        hops = 2
        if "--hops" in sys.argv:
            idx = sys.argv.index("--hops")
            if idx + 1 < len(sys.argv):
                hops = int(sys.argv[idx + 1])
        cmd_impact(G, sys.argv[2], hops)

    elif cmd == "communities":
        cmd_communities(G)

    elif cmd == "viz":
        out = None
        if "--out" in sys.argv:
            idx = sys.argv.index("--out")
            if idx + 1 < len(sys.argv):
                out = sys.argv[idx + 1]
        cmd_viz(G, out)

    elif cmd == "4d":
        if len(sys.argv) < 3:
            print("Usage: query_connectome.py 4d \"task description\"")
            return 1
        activated_nodes = cmd_4d(G, data, " ".join(sys.argv[2:]))

    else:
        print(f"Unknown command: {cmd}")
        print("Commands: stats, gods, dead, path, query, memory, impact, communities, viz, 4d")
        return 1

    # Log session for Hebbian learning (only for graph-traversal commands)
    if activated_nodes and cmd in ["path", "query", "4d"]:
        log_session(activated_nodes=activated_nodes, command=cmd, success=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
