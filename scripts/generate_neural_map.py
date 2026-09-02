#!/usr/bin/env python3
"""
generate_neural_map.py — Octopus Connectome Generator v2.0

Builds a deep neural connectivity map inspired by octopus neurobiology:
- Octopuses have ~500M neurons, 2/3 distributed in arms (not central brain)
- They perform RNA editing — rewriting synaptic connections in real-time
- Each arm thinks independently yet coordinates with the whole

This generator reads the FULL text of every agent and skill, vectorizes with
TF-IDF, and computes cosine similarity across ALL possible pairs:

  Agent↔Skill:  17,658 pairs   (neuron↔synapse)
  Agent↔Agent:  13,041 pairs   (neural pathways)
  Skill↔Skill:   5,886 pairs   (skill clusters/families)
  ─────────────────────────────
  Total:         36,585 pairs   x 7 arms x 4 phases = 1,024,380 action points

Biological principles implemented:
  1. Deep vectorization    — not keywords, full content TF-IDF
  2. Multi-layer synapses  — agent↔skill, agent↔agent, skill↔skill
  3. Hebbian learning      — "neurons that fire together wire together"
  4. Zero broken synapses  — every connection validated at build time
  5. Gap detection         — agents with no skill link, skills with no agent link
  6. Team Assembly Engine  — given a task, find the optimal squad
  7. Arm-distributed intel — each region has its own neural profile

No external dependencies — stdlib only.

Output: ~/.claude/neural_map.json
Auto-regen: called by ai-push after every brain update.
"""

import json
import math
import os
import re
import unicodedata
import sys
from collections import Counter
from datetime import datetime, timezone
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


# ─── Configuration ────────────────────────────────────────────────────────────

BRAIN_DIR = Path.home() / ".claude"
AGENTS_DIR = BRAIN_DIR / "agents"
SKILLS_DIR = BRAIN_DIR / "skills"
REGISTRY_FILE = AGENTS_DIR / "REGISTRY.md"
# Tokenizer contract version. Bump on ANY change to tokenize() that alters the
# terms it produces (folding, regex, stop list).
TOKENIZER_VERSION = "2-accent-folded"

OUTPUT_FILE = BRAIN_DIR / "neural_map.json"
ACTIVITY_LOG = BRAIN_DIR / "neural_activity.json"

# Connection thresholds (tuned for meaningful density)
AGENT_SKILL_THRESHOLD = 0.03     # agent↔skill minimum cosine similarity
AGENT_AGENT_THRESHOLD = 0.08     # agent↔agent minimum (higher = fewer, stronger)
SKILL_SKILL_THRESHOLD = 0.06     # skill↔skill minimum
MAX_SYNAPSES_PER_NEURON = 60     # cap per neuron to prevent noise
EXPLICIT_WEIGHT = 1.0            # REGISTRY.md explicit connections

# Arms = client repos (brain regions)
# Loaded from company/config/arms.json if available, empty by default.
def _load_arms():
    """Load arm definitions from company config, or return empty dict."""
    config_path = BRAIN_DIR / "company" / "config" / "arms.json"
    if config_path.exists():
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}

ARMS = _load_arms()

PHASES = ["Describe", "Delegate", "Diligent", "Disclose"]

AGENT_DIVISIONS = [
    "academic", "design", "engineering", "game-development",
    "marketing", "paid-media", "product", "project-management",
    "sales", "spatial-computing", "specialized", "support", "testing",
]

REFERENCE_DIRS = {"strategy", "examples"}

# Stop words for TF-IDF (English + Spanish + markdown noise).
# MUST stay in sync with query_connectome.py STOP_WORDS — divergence makes
# index-time and query-time tokenize the same prompt differently.
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



# ─── Text Processing & TF-IDF ────────────────────────────────────────────────

def tokenize(text):
    """Extract meaningful tokens from text. Lowercased, accent-folded, no stop words.

    ACCENT FOLDING IS NOT COSMETIC. The word regex below only starts a token at
    [a-z], so a combining accent SPLITS the word and eats its head: "codigo"
    written with its accent yields "digo", "diseno" yields "dise", "espanol"
    yields "espa". Two failures follow. The real word never enters the
    vocabulary, so a search for it cannot match; and the mutilated stem does,
    where it can collide with an unrelated real word ("digo" is Spanish for
    "I say") and weave a synapse between documents that share nothing.

    Snapshot on one machine, 2026-09-02: ~157 distinct accented words over the
    ~415 documents this generator feeds to TF-IDF, folding out ~130 mutilated
    stems and admitting ~97 real words for a net vocabulary change of about -30
    terms. Deliberately approximate: skills/learned/ is gitignored and drifts
    per machine, so an exact count is NOT reproducible by a reader and any
    precise figure here would rot into a lie. The shape is what matters and it
    is stable: a small effect in this corpus, because skills and agents are
    written mostly in English. The same defect was severe in the life-memories
    corpus, where the operator's own city indexed as "laga" and "dia" vanished
    outright.

    Folding the corpus WITHOUT folding STOP_WORDS is worse than not folding at
    all: see _folded_stops above. That half-fix shipped junk terms ("que" at idf
    2.502) that wove 6 false skill-skill edges before it was caught.

    NFKD + drop-combining is idempotent, so folding again downstream is safe.
    """
    text = _fold(text)
    # Remove code blocks (they add noise)
    text = re.sub(r"```[\s\S]*?```", " ", text)
    # Remove URLs
    text = re.sub(r"https?://\S+", " ", text)
    # Remove markdown syntax
    text = re.sub(r"[#*\`\[\](){}|>_~=\-]", " ", text)
    # Extract words (keep alphanumeric + hyphens for compound terms)
    words = re.findall(r"[a-z][a-z0-9]{2,}(?:-[a-z0-9]+)*", text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) >= 3]


def extract_bigrams(tokens):
    """Extract meaningful bigrams (pairs of adjacent words)."""
    bigrams = []
    for i in range(len(tokens) - 1):
        a, b = tokens[i], tokens[i + 1]
        if a != b:
            bigrams.append(f"{a}_{b}")
    return bigrams


def build_vocabulary(documents):
    """
    Build TF-IDF vectors for all documents.
    Returns: (tfidf_vectors, idf_scores)
    """
    N = len(documents)
    if N == 0:
        return {}, {}

    # Step 1: Tokenize all documents (unigrams + bigrams)
    doc_tokens = {}
    for doc_id, text in documents.items():
        unigrams = tokenize(text)
        bigrams = extract_bigrams(unigrams)
        doc_tokens[doc_id] = unigrams + bigrams

    # Step 2: Compute document frequency (DF)
    df = Counter()
    for tokens in doc_tokens.values():
        unique_terms = set(tokens)
        for term in unique_terms:
            df[term] += 1

    # Step 3: Compute IDF (inverse document frequency)
    # Filter: term must appear in at least 2 docs but no more than 80%
    idf = {}
    for term, count in df.items():
        if 2 <= count <= N * 0.8:
            idf[term] = math.log(N / count)

    # Step 4: Compute TF-IDF vectors
    tfidf_vectors = {}
    for doc_id, tokens in doc_tokens.items():
        tf = Counter(tokens)
        total = len(tokens) if tokens else 1
        vector = {}
        for term, count in tf.items():
            if term in idf:
                tfidf = (count / total) * idf[term]
                if tfidf > 0.001:
                    vector[term] = round(tfidf, 6)
        tfidf_vectors[doc_id] = vector

    return tfidf_vectors, idf


def cosine_similarity(vec_a, vec_b):
    """Compute cosine similarity between two sparse TF-IDF vectors."""
    if not vec_a or not vec_b:
        return 0.0

    shared_keys = set(vec_a.keys()) & set(vec_b.keys())
    if not shared_keys:
        return 0.0

    dot = sum(vec_a[k] * vec_b[k] for k in shared_keys)

    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot / (norm_a * norm_b)


# ─── Document Readers ─────────────────────────────────────────────────────────

def read_agent(filepath):
    """Read full content of an agent .md file."""
    text = filepath.read_text(encoding="utf-8", errors="replace")
    meta = {
        "id": filepath.stem,
        "file": str(filepath.relative_to(BRAIN_DIR)),
        "name": filepath.stem.replace("-", " ").title(),
        "emoji": "",
        "description": "",
        "text": text,
    }

    # Determine division
    rel = filepath.relative_to(AGENTS_DIR)
    parts = list(rel.parts)
    meta["division"] = parts[0] if parts else "unknown"

    # Parse YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        for line in fm_text.split("\n"):
            if line.startswith("name:"):
                meta["name"] = line.split(":", 1)[1].strip().strip("\"'")
            elif line.startswith("emoji:"):
                meta["emoji"] = line.split(":", 1)[1].strip().strip("\"'")
            elif line.startswith("description:"):
                meta["description"] = line.split(":", 1)[1].strip().strip("\"'")

    return meta


def read_skill(skill_dir):
    """Read full content of a SKILL.md file."""
    skill_file = skill_dir / "SKILL.md"
    meta = {
        "id": skill_dir.name,
        "name": skill_dir.name.replace("-", " ").title(),
        "description": "",
        "text": "",
    }
    if skill_file.exists():
        text = skill_file.read_text(encoding="utf-8", errors="replace")
        meta["text"] = text

        h1 = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if h1:
            meta["name"] = h1.group(1).strip()

        # Walk paragraphs after the H1 and pick the first one that is real prose:
        # not another heading (## …), not a code fence, not a quote/admonition,
        # and at least 40 chars. Avoids "## Quick Reference" being captured as the description.
        body = text.split("\n", 1)[1] if "\n" in text else ""
        body = body.split("\n", 1)[1] if body.startswith("#") else body  # skip H1 if still there
        for para in re.split(r"\n\s*\n", body):
            para = para.strip()
            if not para or para.startswith(("#", "```", ">", "|", "<!--")):
                continue
            if len(para) < 40:
                continue
            meta["description"] = re.sub(r"\s+", " ", para)[:300]
            break

    return meta


def parse_registry_crossrefs(registry_path):
    """Parse REGISTRY.md agent-skill cross-references."""
    if not registry_path.exists():
        return {}

    text = registry_path.read_text(encoding="utf-8", errors="replace")
    crossrefs = {}

    xref_match = re.search(
        r"## Cross-Reference: Agents.*?Skills.*?\n\n\|.*?\n\|.*?\n((?:\|.*\n)*)",
        text, re.IGNORECASE,
    )
    if not xref_match:
        return {}

    for line in xref_match.group(1).strip().split("\n"):
        cols = [c.strip() for c in line.split("|")]
        if len(cols) >= 3:
            agent_cell = cols[1]
            skills_cell = cols[2]
            agent_name = re.sub(r"[^\w\s]", "", agent_cell).strip().lower()
            agent_name = re.sub(r"\s+", "-", agent_name)
            skills = re.findall(r"`([^`]+)`", skills_cell)
            if skills:
                crossrefs[agent_name] = skills

    return crossrefs


def parse_registry_triggers(registry_path):
    """Parse REGISTRY.md triggers per agent."""
    if not registry_path.exists():
        return {}

    text = registry_path.read_text(encoding="utf-8", errors="replace")
    triggers_map = {}

    for match in re.finditer(
        r"\|\s*([^\|]+?)\s*\|\s*\[.*?\]\(([^\)]+)\)\s*\|\s*([^\|]+?)\s*\|",
        text,
    ):
        file_path = match.group(2).strip()
        triggers_cell = match.group(3).strip()
        agent_id = Path(file_path).stem
        triggers = [t.strip().lower() for t in triggers_cell.split(",") if t.strip()]
        if triggers:
            triggers_map[agent_id] = triggers

    return triggers_map


# ─── Hebbian Learning ─────────────────────────────────────────────────────────

def load_hebbian_weights(log_path):
    """
    Load activity log and compute Hebbian weight adjustments with time decay + success signals.
    "Neurons that fire together wire together — but stale patterns fade."

    Time decay: each session's contribution decays as e^(-lambda * age_days).
      lambda=0.01 -> half-life ~69 days.
    Negative signals: failed sessions (success=false) subtract 0.5 per pair.
    Fallback: if no sessions array exists, uses raw co_activation_matrix (no decay).
    """
    hebbian = {}

    if not log_path.exists():
        return hebbian

    try:
        activity = json.loads(log_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return hebbian

    sessions = activity.get("sessions", [])
    decayed_counts = Counter()

    if sessions:
        # Time-decayed computation from session history
        now = datetime.now(timezone.utc)
        decay_lambda = 0.01       # half-life ~69 days
        negative_weight = 0.5     # failed sessions subtract this fraction

        for session in sessions:
            ts_str = session.get("timestamp", "")
            success = session.get("success", True)
            activated = session.get("activated_nodes", [])

            if len(activated) < 2:
                continue

            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_days = (now - ts).total_seconds() / 86400
            except (ValueError, TypeError):
                age_days = 0

            decay = math.exp(-decay_lambda * max(age_days, 0))
            signal = decay if success else -negative_weight * decay

            from itertools import combinations
            for pair in combinations(sorted(activated), 2):
                decayed_counts[tuple(sorted(pair))] += signal
    else:
        # Fallback: raw co_activation_matrix (no decay, backward compat)
        matrix = activity.get("co_activation_matrix", {})
        for pair_key, count in matrix.items():
            if pair_key.startswith("_"):
                continue
            parts = pair_key.split("::")
            if len(parts) == 2:
                pair = tuple(sorted(parts))
                decayed_counts[pair] += int(count)

    # Convert to weight boosts (logarithmic, capped at 0.5)
    for pair, count in decayed_counts.items():
        if count <= 0:
            continue  # Negative or zero = no boost
        boost = min(0.5, math.log1p(count) * 0.1)
        hebbian[pair] = round(boost, 4)

    return hebbian


# ─── Core Engine ──────────────────────────────────────────────────────────────

def generate_connectome():
    """Generate the full deep connectome."""
    t0 = datetime.now(timezone.utc)
    print("  Octopus Connectome Generator v2.0 — Deep Neural Map")
    print("=" * 60)
    print("   Inspired by octopus neurobiology:")
    print("   500M neurons, 2/3 in arms, RNA editing")
    print("   Full content TF-IDF + cosine similarity")
    print("   Multi-layer synapses + Hebbian learning")
    print()

    # ── Step 1: Discover & read ALL neurons ──
    print("Step 1: Reading neurons (agents/) — full content...")
    neurons = []
    agent_docs = {}

    for agent_dir_name in AGENT_DIVISIONS:
        dir_path = AGENTS_DIR / agent_dir_name
        if not dir_path.exists():
            continue
        for md_file in sorted(dir_path.rglob("*.md")):
            if md_file.name == "README.md":
                continue
            meta = read_agent(md_file)
            neurons.append(meta)
            agent_docs[meta["id"]] = meta["text"]

    print(f"   {len(neurons)} neurons, {sum(len(t) for t in agent_docs.values()):,} chars of content")

    # ── Step 2: Discover & read ALL synapses ──
    print("Step 2: Reading synapses (skills/) — full content...")
    synapses = []
    skill_docs = {}

    # Walk the WHOLE skills tree, not just depth 1.
    #
    # The harness's resident skill listing only sees skills/<slug>/SKILL.md, so
    # anything nested deeper is invisible to the model. That is exactly what makes
    # a cold tier possible: move a skill down a level and it leaves the always-on
    # index. But it only stays REACHABLE if the graph still indexes it — otherwise
    # a cooled skill is not dormant, it is dead: unreachable by listing AND by seek.
    # So the graph deliberately walks deeper than the listing does.
    #
    # A dir with no direct SKILL.md is a container, not a skill (e.g. the learned/
    # draft pen). Containers are never indexed themselves — that would mint a
    # contentless degree-0 orphan that `query_connectome.py dead` flags forever —
    # but their children are.
    #
    # Ids stay the directory slug, so the SAME slug can appear at two depths (a
    # promoted skill at depth 1 plus its leftover draft in learned/). Shallowest
    # wins: the promoted copy is canonical, the draft is skipped.
    seen_ids = {}
    for skill_file in sorted(SKILLS_DIR.rglob("SKILL.md")):
        skill_dir = skill_file.parent
        rel = skill_dir.relative_to(SKILLS_DIR)
        if any(part.startswith(".") for part in rel.parts):
            continue
        depth = len(rel.parts)
        meta = read_skill(skill_dir)
        prev = seen_ids.get(meta["id"])
        if prev is not None:
            if depth >= prev["depth"]:
                continue  # deeper duplicate — the shallower copy is canonical
            synapses.remove(prev)
        meta["depth"] = depth
        seen_ids[meta["id"]] = meta
        synapses.append(meta)
        skill_docs[meta["id"]] = meta["text"]

    nested = sum(1 for s in synapses if s.get("depth", 1) > 1)
    print(f"   {len(synapses)} synapses, {sum(len(t) for t in skill_docs.values()):,} chars of content")
    if nested:
        print(f"   ({nested} from nested/cold subtrees — indexed here, absent from the resident listing)")

    # ── Step 3: Build unified TF-IDF corpus ──
    print("Step 3: Building TF-IDF vectors from full corpus...")
    all_docs = {}
    for doc_id, text in agent_docs.items():
        all_docs[f"agent:{doc_id}"] = text
    for doc_id, text in skill_docs.items():
        all_docs[f"skill:{doc_id}"] = text

    tfidf_vectors, idf_scores = build_vocabulary(all_docs)
    vocab_size = len(idf_scores)
    print(f"   Vocabulary: {vocab_size:,} terms (after stop-word removal + DF filtering)")
    print(f"   Documents:  {len(tfidf_vectors)} vectorized")

    # ── Step 4: Parse REGISTRY.md for explicit connections ──
    print("Step 4: Parsing REGISTRY.md for explicit bonds...")
    crossrefs = parse_registry_crossrefs(REGISTRY_FILE)
    triggers_map = parse_registry_triggers(REGISTRY_FILE)
    print(f"   {len(crossrefs)} explicit agent-skill mappings")
    print(f"   {len(triggers_map)} agents with trigger keywords")

    # Enrich neurons with triggers
    for neuron in neurons:
        if neuron["id"] in triggers_map:
            neuron["triggers"] = triggers_map[neuron["id"]]

    # ── Step 5: Load Hebbian weights ──
    print("Step 5: Loading Hebbian activity log...")
    hebbian = load_hebbian_weights(ACTIVITY_LOG)
    print(f"   {len(hebbian)} co-activation patterns loaded")

    # ── Step 6: Compute Agent-Skill connections (neuron-synapse) ──
    print("Step 6: Computing Agent-Skill connections (cosine similarity)...")

    # Build explicit connection lookup for merging
    explicit_lookup = {}
    for xref_key, xref_skills in crossrefs.items():
        for neuron in neurons:
            name_norm = re.sub(
                r"^(engineering|design|marketing|testing|support|sales|product|"
                r"specialized|academic|paid-media|project-management|"
                r"spatial-computing|game-development)-", "", neuron["id"]
            )
            if name_norm in xref_key or xref_key in name_norm or xref_key in neuron["id"]:
                for skill_id in xref_skills:
                    explicit_lookup[(neuron["id"], skill_id)] = True

    agent_skill_edges = []
    explicit_count = 0
    inferred_count = 0

    for neuron in neurons:
        a_key = f"agent:{neuron['id']}"
        a_vec = tfidf_vectors.get(a_key, {})
        connections = {}

        for synapse in synapses:
            s_key = f"skill:{synapse['id']}"
            s_vec = tfidf_vectors.get(s_key, {})

            is_explicit = (neuron["id"], synapse["id"]) in explicit_lookup
            sim = cosine_similarity(a_vec, s_vec)

            pair = tuple(sorted([neuron["id"], synapse["id"]]))
            hebb_boost = hebbian.get(pair, 0)
            sim_boosted = min(sim + hebb_boost, 0.99)

            if is_explicit:
                connections[synapse["id"]] = EXPLICIT_WEIGHT
                explicit_count += 1
            elif sim_boosted >= AGENT_SKILL_THRESHOLD:
                connections[synapse["id"]] = round(sim_boosted, 4)
                inferred_count += 1

        # Cap connections per neuron (keep strongest)
        if len(connections) > MAX_SYNAPSES_PER_NEURON:
            sorted_conns = sorted(connections.items(), key=lambda x: -x[1])
            connections = dict(sorted_conns[:MAX_SYNAPSES_PER_NEURON])

        neuron["_skill_connections"] = connections
        for skill_id, weight in connections.items():
            agent_skill_edges.append((neuron["id"], skill_id, weight))

    total_a2s = explicit_count + inferred_count
    print(f"   Explicit: {explicit_count} | Inferred: {inferred_count} | Total: {total_a2s}")

    # ── Step 7: Compute Agent-Agent connections (neural pathways) ──
    print("Step 7: Computing Agent-Agent pathways (who collaborates)...")

    agent_agent_edges = []
    for i in range(len(neurons)):
        a_key = f"agent:{neurons[i]['id']}"
        a_vec = tfidf_vectors.get(a_key, {})
        for j in range(i + 1, len(neurons)):
            b_key = f"agent:{neurons[j]['id']}"
            b_vec = tfidf_vectors.get(b_key, {})

            sim = cosine_similarity(a_vec, b_vec)

            # Same-division bonus (colleagues collaborate more)
            if neurons[i]["division"] == neurons[j]["division"]:
                sim *= 1.15

            # Hebbian boost
            pair = tuple(sorted([neurons[i]["id"], neurons[j]["id"]]))
            hebb_boost = hebbian.get(pair, 0)
            sim = min(sim + hebb_boost, 0.99)

            if sim >= AGENT_AGENT_THRESHOLD:
                agent_agent_edges.append((neurons[i]["id"], neurons[j]["id"], round(sim, 4)))

    print(f"   Neural pathways: {len(agent_agent_edges)}")

    # ── Step 8: Compute Skill-Skill connections (skill clusters) ──
    print("Step 8: Computing Skill-Skill clusters (skill families)...")

    skill_skill_edges = []
    for i in range(len(synapses)):
        a_key = f"skill:{synapses[i]['id']}"
        a_vec = tfidf_vectors.get(a_key, {})
        for j in range(i + 1, len(synapses)):
            b_key = f"skill:{synapses[j]['id']}"
            b_vec = tfidf_vectors.get(b_key, {})

            sim = cosine_similarity(a_vec, b_vec)

            pair = tuple(sorted([synapses[i]["id"], synapses[j]["id"]]))
            hebb_boost = hebbian.get(pair, 0)
            sim = min(sim + hebb_boost, 0.99)

            if sim >= SKILL_SKILL_THRESHOLD:
                skill_skill_edges.append((synapses[i]["id"], synapses[j]["id"], round(sim, 4)))

    print(f"   Skill clusters: {len(skill_skill_edges)}")

    # ── Step 9: Compute arm relevance using TF-IDF ──
    print("Step 9: Computing arm relevance...")

    arm_vectors = {}
    for arm_id, arm_config in ARMS.items():
        arm_text = " ".join(arm_config["stack_keywords"]) * 5
        arm_tokens = tokenize(arm_text)
        tf = Counter(arm_tokens)
        total = len(arm_tokens) if arm_tokens else 1
        vec = {}
        for term, count in tf.items():
            if term in idf_scores:
                tfidf_val = (count / total) * idf_scores[term]
                if tfidf_val > 0.001:
                    vec[term] = round(tfidf_val, 6)
        arm_vectors[arm_id] = vec

    neuron_arms = {}
    for neuron in neurons:
        a_key = f"agent:{neuron['id']}"
        a_vec = tfidf_vectors.get(a_key, {})
        arm_scores = {}
        for arm_id, arm_vec in arm_vectors.items():
            sim = cosine_similarity(a_vec, arm_vec)
            if sim >= 0.02:
                arm_scores[arm_id] = round(sim, 4)
        neuron["_arm_scores"] = arm_scores
        neuron_arms[neuron["id"]] = arm_scores

    synapse_arms = {}
    for synapse in synapses:
        s_key = f"skill:{synapse['id']}"
        s_vec = tfidf_vectors.get(s_key, {})
        arm_scores = {}
        for arm_id, arm_vec in arm_vectors.items():
            sim = cosine_similarity(s_vec, arm_vec)
            if sim >= 0.02:
                arm_scores[arm_id] = round(sim, 4)
        synapse["_arm_scores"] = arm_scores
        synapse_arms[synapse["id"]] = arm_scores

    total_arm_links = sum(len(v) for v in neuron_arms.values()) + sum(len(v) for v in synapse_arms.values())
    print(f"   Arm connections: {total_arm_links} (neurons + synapses)")

    # ── Step 10: Validate zero broken synapses ──
    print("Step 10: Validating zero broken synapses...")

    neuron_ids = {n["id"] for n in neurons}
    synapse_ids = {s["id"] for s in synapses}
    broken = 0

    valid_a2s = []
    for a, s, w in agent_skill_edges:
        if a in neuron_ids and s in synapse_ids:
            valid_a2s.append((a, s, w))
        else:
            broken += 1

    valid_a2a = []
    for a, b, w in agent_agent_edges:
        if a in neuron_ids and b in neuron_ids:
            valid_a2a.append((a, b, w))
        else:
            broken += 1

    valid_s2s = []
    for a, b, w in skill_skill_edges:
        if a in synapse_ids and b in synapse_ids:
            valid_s2s.append((a, b, w))
        else:
            broken += 1

    if broken > 0:
        print(f"   WARNING: Removed {broken} broken synapses")
    else:
        print("   PASS: Zero broken synapses — all connections validated")

    # ── Step 11: Build reverse maps + diagnostics ──
    print("Step 11: Computing diagnostics...")

    skill_to_agents = {s["id"]: {} for s in synapses}
    for a, s, w in valid_a2s:
        skill_to_agents[s][a] = w

    arm_to_neurons = {arm_id: {} for arm_id in ARMS}
    for n in neurons:
        for arm_id, score in n.get("_arm_scores", {}).items():
            arm_to_neurons[arm_id][n["id"]] = score

    arm_to_synapses = {arm_id: {} for arm_id in ARMS}
    for s in synapses:
        for arm_id, score in s.get("_arm_scores", {}).items():
            arm_to_synapses[arm_id][s["id"]] = score

    agent_neighbors = {n["id"]: {} for n in neurons}
    for a, b, w in valid_a2a:
        agent_neighbors[a][b] = w
        agent_neighbors[b][a] = w

    # Diagnostics
    # NOTE: these two are CROSS-LAYER coverage gaps, not dead cells. An entry here
    # still has skill<->skill (or agent<->agent) edges and is reachable by recall;
    # it merely has no link across the agent/skill boundary above the threshold.
    # Prune candidates are degree-0/degree-1 nodes: see `query_connectome.py dead`.
    agents_without_skills = [n["id"] for n in neurons if not n.get("_skill_connections")]
    skills_without_agents = [s_id for s_id, conns in skill_to_agents.items() if not conns]

    busiest_neurons = sorted(neurons, key=lambda n: len(n.get("_skill_connections", {})), reverse=True)[:15]
    most_connected_agents = sorted(neurons, key=lambda n: len(agent_neighbors.get(n["id"], {})), reverse=True)[:15]
    hub_synapses = sorted(skill_to_agents.items(), key=lambda x: len(x[1]), reverse=True)[:15]

    # Skill clusters: group skills that form cliques
    skill_clusters = {}
    for a, b, w in valid_s2s:
        if a not in skill_clusters:
            skill_clusters[a] = set()
        if b not in skill_clusters:
            skill_clusters[b] = set()
        skill_clusters[a].add(b)
        skill_clusters[b].add(a)

    division_stats = {}
    for n in neurons:
        div = n["division"]
        if div not in division_stats:
            division_stats[div] = {"count": 0, "total_skill_conns": 0, "total_agent_conns": 0, "total_arm_conns": 0}
        division_stats[div]["count"] += 1
        division_stats[div]["total_skill_conns"] += len(n.get("_skill_connections", {}))
        division_stats[div]["total_agent_conns"] += len(agent_neighbors.get(n["id"], {}))
        division_stats[div]["total_arm_conns"] += len(n.get("_arm_scores", {}))

    # ── Step 12: Assemble mega-connectome ──
    print("Step 12: Assembling connectome...")

    n_neurons = len(neurons)
    n_synapses = len(synapses)
    n_regions = len(ARMS)
    n_phases = len(PHASES)
    total_theoretical = n_neurons * n_synapses * n_regions * n_phases
    total_connections = len(valid_a2s) + len(valid_a2a) + len(valid_s2s)

    possible_edges = max(
        (n_neurons * n_synapses) +
        (n_neurons * (n_neurons - 1) // 2) +
        (n_synapses * (n_synapses - 1) // 2),
        1,
    )
    connectivity_density = round(total_connections / possible_edges * 100, 2)

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()

    connectome = {
        "meta": {
            "generated": t0.isoformat(),
            "version": "2.0",
            # Bumped whenever tokenization changes. A map built by a different
            # tokenizer than the one asking the question is STALE even when its
            # mtime is newer than every source file: a sibling machine that
            # pulls new scripts keeps an old-tokenizer index and silently
            # answers zero. Freshness checks compare this, not just mtimes.
            "tokenizer": TOKENIZER_VERSION,
            "generator": "generate_neural_map.py",
            "model": "Octopus Deep Connectome",
            "generation_time_sec": round(elapsed, 2),
            "biology": {
                "inspiration": "Octopus vulgaris — 500M neurons, 2/3 in arms, RNA editing",
                "principle": "Deep content vectorization + cosine similarity + Hebbian learning",
                "neurons": "Agents — WHO does the work (processing units)",
                "synapses": "Skills — HOW the work is done (functional connections)",
                "pathways": "Agent-Agent channels — WHO collaborates with WHO",
                "clusters": "Skill families — related capabilities group together",
                "regions": "Arms — WHERE the work happens (client-specific areas)",
                "temporal": "4D Phases — WHEN signals fire (Describe Delegate Diligent Disclose)",
            },
        },
        "dimensions": {
            "D1_WHO": {"label": "Neurons (Agents)", "count": n_neurons},
            "D2_HOW": {"label": "Synapses (Skills)", "count": n_synapses},
            "D3_WHERE": {"label": "Regions (Arms)", "count": n_regions},
            "D4_WHEN": {"label": "Temporal (4D Phases)", "count": n_phases, "values": PHASES},
        },
        "capacity": {
            "theoretical_action_points": total_theoretical,
            "total_connections": total_connections,
            "agent_skill_connections": len(valid_a2s),
            "agent_agent_pathways": len(valid_a2a),
            "skill_skill_clusters": len(valid_s2s),
            "arm_connections": total_arm_links,
            "connectivity_density_pct": connectivity_density,
            "max_simultaneous_clones": n_neurons * n_regions,
            "formula": f"{n_neurons} x {n_synapses} x {n_regions} x {n_phases} = {total_theoretical:,}",
            "hebbian_patterns": len(hebbian),
            "broken_synapses": 0,
            "vocabulary_size": vocab_size,
        },
        "neurons": [
            {
                "id": n["id"],
                "name": n["name"],
                "emoji": n.get("emoji", ""),
                "division": n["division"],
                "triggers": n.get("triggers", []),
                "synapses": n.get("_skill_connections", {}),
                "neighbors": agent_neighbors.get(n["id"], {}),
                "regions": n.get("_arm_scores", {}),
                "stats": {
                    "synapse_count": len(n.get("_skill_connections", {})),
                    "neighbor_count": len(agent_neighbors.get(n["id"], {})),
                    "region_count": len(n.get("_arm_scores", {})),
                    "total_connectivity": (
                        len(n.get("_skill_connections", {}))
                        + len(agent_neighbors.get(n["id"], {}))
                        + len(n.get("_arm_scores", {}))
                    ),
                    "strongest_synapse": (
                        max(n["_skill_connections"].items(), key=lambda x: x[1])[0]
                        if n.get("_skill_connections")
                        else None
                    ),
                    "primary_region": (
                        max(n["_arm_scores"].items(), key=lambda x: x[1])[0]
                        if n.get("_arm_scores")
                        else None
                    ),
                },
            }
            for n in neurons
        ],
        "synapses": [
            {
                "id": s["id"],
                "name": s["name"],
                "description": s.get("description", "")[:200],
                # Tree depth under skills/. 1 = visible in the harness's resident
                # listing; >1 = cold subtree, reachable by seek only.
                "depth": s.get("depth", 1),
                "connected_neurons": skill_to_agents.get(s["id"], {}),
                "cluster_neighbors": {
                    nb: round(next(
                        (ww for aa, bb, ww in valid_s2s
                         if (aa == s["id"] and bb == nb) or (bb == s["id"] and aa == nb)),
                        0,
                    ), 4)
                    for nb in skill_clusters.get(s["id"], set())
                },
                "regions": synapse_arms.get(s["id"], {}),
                "stats": {
                    "neuron_count": len(skill_to_agents.get(s["id"], {})),
                    "cluster_size": len(skill_clusters.get(s["id"], set())),
                    "region_count": len(synapse_arms.get(s["id"], {})),
                    "is_hub": len(skill_to_agents.get(s["id"], {})) >= 10,
                },
            }
            for s in synapses
        ],
        "pathways": {
            "description": "Agent-Agent collaboration channels, weighted by content similarity",
            "total": len(valid_a2a),
            "edges": [
                {"from": a, "to": b, "weight": w}
                for a, b, w in sorted(valid_a2a, key=lambda x: -x[2])
            ],
        },
        "skill_clusters": {
            "description": "Skill-Skill families, weighted by content similarity",
            "total": len(valid_s2s),
            "edges": [
                {"from": a, "to": b, "weight": w}
                for a, b, w in sorted(valid_s2s, key=lambda x: -x[2])
            ],
        },
        "regions": [
            {
                "id": arm_id,
                "name": arm_config["name"],
                "stack_keywords": arm_config["stack_keywords"],
                "relevant_neurons": arm_to_neurons.get(arm_id, {}),
                "relevant_synapses": arm_to_synapses.get(arm_id, {}),
                "stats": {
                    "neuron_count": len(arm_to_neurons.get(arm_id, {})),
                    "synapse_count": len(arm_to_synapses.get(arm_id, {})),
                    "total_relevance": len(arm_to_neurons.get(arm_id, {})) + len(arm_to_synapses.get(arm_id, {})),
                },
            }
            for arm_id, arm_config in ARMS.items()
        ],
        "tfidf_index": {
            "description": "Stored TF-IDF vectors and IDF dictionary for query-time cosine similarity.",
            "idf": {k: round(v, 4) for k, v in idf_scores.items()},
            "vectors": {
                doc_id: {k: v for k, v in sorted(vec.items(), key=lambda x: -x[1])[:200]}
                for doc_id, vec in tfidf_vectors.items()
                if vec
            },
        },
        "team_assembly": {
            "description": (
                "Query this section to find the optimal squad for any task. "
                "Algorithm: tokenize query, compute TF-IDF vector using stored IDF, "
                "rank neurons by cosine similarity, load their strongest synapses, "
                "suggest team of top-N agents with their skill loadouts."
            ),
            "instructions": (
                "Use tfidf_index.vectors and tfidf_index.idf to compute cosine "
                "similarity at query time. See query_connectome.py cmd_query()."
            ),
        },
        "diagnostics": {
            "agents_without_skills": agents_without_skills,
            "skills_without_agents": skills_without_agents,
            "busiest_neurons": [
                {"id": n["id"], "skill_connections": len(n.get("_skill_connections", {})),
                 "agent_connections": len(agent_neighbors.get(n["id"], {})),
                 "total": len(n.get("_skill_connections", {})) + len(agent_neighbors.get(n["id"], {}))}
                for n in busiest_neurons
            ],
            "most_collaborative_agents": [
                {"id": n["id"], "neighbors": len(agent_neighbors.get(n["id"], {}))}
                for n in most_connected_agents
            ],
            "hub_synapses": [
                {"id": s_id, "connected_neurons": len(conns)}
                for s_id, conns in hub_synapses
            ],
            "division_stats": division_stats,
        },
    }

    return connectome


def print_summary(connectome):
    """Print a human-readable summary."""
    dims = connectome["dimensions"]
    cap = connectome["capacity"]
    diag = connectome["diagnostics"]
    meta = connectome["meta"]

    print("\n" + "=" * 60)
    print("OCTOPUS DEEP CONNECTOME v2.0 — NEURAL MAP SUMMARY")
    print("=" * 60)

    print(f"\nTesseract Dimensions:")
    print(f"   D1 (WHO):   {dims['D1_WHO']['count']:>4} neurons  (agents)")
    print(f"   D2 (HOW):   {dims['D2_HOW']['count']:>4} synapses (skills)")
    print(f"   D3 (WHERE): {dims['D3_WHERE']['count']:>4} regions  (arms)")
    print(f"   D4 (WHEN):  {dims['D4_WHEN']['count']:>4} phases   (4D paradigm)")

    print(f"\nConnections:")
    print(f"   Agent-Skill (neuron-synapse):    {cap['agent_skill_connections']:>8,}")
    print(f"   Agent-Agent (neural pathways):   {cap['agent_agent_pathways']:>8,}")
    print(f"   Skill-Skill (skill clusters):    {cap['skill_skill_clusters']:>8,}")
    print(f"   Arm relevance links:             {cap['arm_connections']:>8,}")
    print(f"   -----------------------------------------")
    print(f"   TOTAL CONNECTIONS:               {cap['total_connections']:>8,}")
    print(f"   Connectivity density:            {cap['connectivity_density_pct']:>7}%")
    print(f"   Broken synapses:                 {cap['broken_synapses']:>8}")
    print(f"   TF-IDF vocabulary:               {cap['vocabulary_size']:>8,} terms")
    print(f"   Hebbian patterns:                {cap['hebbian_patterns']:>8}")

    print(f"\nCapacity:")
    print(f"   Theoretical action points: {cap['theoretical_action_points']:>10,}")
    print(f"   Max simultaneous clones:   {cap['max_simultaneous_clones']:>10,}")
    print(f"   Formula: {cap['formula']}")

    print(f"\nDiagnostics:")
    print(f"   Agents with no skill link:      {len(diag['agents_without_skills'])}")
    print(f"   Skills with no agent link:      {len(diag['skills_without_agents'])}")

    print(f"\nBusiest Neurons (total connections):")
    for item in diag["busiest_neurons"][:8]:
        print(f"   {item['id']:.<45} {item['total']:>4} (skills:{item['skill_connections']}, agents:{item['agent_connections']})")

    print(f"\nMost Collaborative (agent-agent pathways):")
    for item in diag["most_collaborative_agents"][:8]:
        print(f"   {item['id']:.<45} {item['neighbors']:>4} neighbors")

    print(f"\nHub Synapses (most neuron connections):")
    for item in diag["hub_synapses"][:8]:
        print(f"   {item['id']:.<45} {item['connected_neurons']:>4} neurons")

    print(f"\nDivision Connectivity:")
    for div, stats in sorted(diag["division_stats"].items()):
        c = stats["count"]
        avg_s = stats["total_skill_conns"] / max(c, 1)
        avg_a = stats["total_agent_conns"] / max(c, 1)
        avg_r = stats["total_arm_conns"] / max(c, 1)
        print(f"   {div:.<28} {c:>3} neurons | avg skills:{avg_s:>5.1f} agents:{avg_a:>5.1f} arms:{avg_r:>4.1f}")

    if diag["agents_without_skills"] or diag["skills_without_agents"]:
        print("\nCross-layer coverage gaps (NOT prune candidates):")
        print("   These nodes keep their same-layer edges and stay reachable by recall.")
        print("   For real dead cells (degree 0 or 1) run: query_connectome.py dead")

    if diag["agents_without_skills"]:
        print(f"\nAgents With No Skill Link ({len(diag['agents_without_skills'])} total):")
        for n in diag["agents_without_skills"][:5]:
            print(f"   - {n}")
        if len(diag["agents_without_skills"]) > 5:
            print(f"   ... and {len(diag['agents_without_skills']) - 5} more")

    if diag["skills_without_agents"]:
        print(f"\nSkills With No Agent Link ({len(diag['skills_without_agents'])} total):")
        for s in diag["skills_without_agents"][:5]:
            print(f"   - {s}")
        if len(diag["skills_without_agents"]) > 5:
            print(f"   ... and {len(diag['skills_without_agents']) - 5} more")

    print(f"\nGeneration time: {meta['generation_time_sec']}s")


# Refuse to silently replace the connectome with a much smaller one: a partial
# skills/agents checkout (broken glob, interrupted sync) would otherwise shrink
# the graph that THIS machine's heartbeat and query_connectome.py read, looking
# like a successful regeneration. neural_map.json is gitignored, so the damage
# is local-only, but silent. Only D1/D2 are guarded: D3 arm counts come from
# the gitignored company config and legitimately differ per machine. Deliberate
# prunes stay under the tolerance; bigger cuts need --allow-shrink.
SHRINK_TOLERANCE = 0.10


def shrink_guard(connectome, allow_shrink=False):
    """Exit non-zero if the new graph lost >SHRINK_TOLERANCE of nodes."""
    if allow_shrink or not OUTPUT_FILE.exists():
        return
    try:
        prev = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        prev_counts = {
            dim: prev["dimensions"][dim]["count"] for dim in ("D1_WHO", "D2_HOW")
        }
    except (OSError, ValueError, KeyError, TypeError):
        return  # previous map unreadable: nothing trustworthy to compare against
    for dim, prev_count in prev_counts.items():
        new_count = connectome["dimensions"][dim]["count"]
        floor = int(prev_count * (1 - SHRINK_TOLERANCE))
        if new_count < floor:
            label = connectome["dimensions"][dim]["label"]
            sys.exit(
                f"SHRINK-GUARD: {label} would drop {prev_count} -> {new_count} "
                f"(floor {floor}, tolerance {SHRINK_TOLERANCE:.0%}). Refusing to "
                f"overwrite {OUTPUT_FILE.name}. If the shrink is deliberate, "
                f"re-run with --allow-shrink."
            )


def main():
    connectome = generate_connectome()
    print_summary(connectome)

    shrink_guard(connectome, allow_shrink="--allow-shrink" in sys.argv[1:])
    OUTPUT_FILE.write_text(
        json.dumps(connectome, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    size_kb = OUTPUT_FILE.stat().st_size / 1024
    print(f"\nConnectome written to: {OUTPUT_FILE}")
    print(f"   Size: {size_kb:.1f} KB")

    return 0


if __name__ == "__main__":
    sys.exit(main())
