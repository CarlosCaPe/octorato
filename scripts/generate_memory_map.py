#!/usr/bin/env python3
"""
Memory Map Generator — TF-IDF + cosine index over the brain's life-memories.

WHY THIS EXISTS
    The connectome (`neural_map.json`) circulates skills and agents. The brain's
    own life-memories were never nodes in it, so "do I already know this?" fell
    back to raw token overlap: a memory phrased with different vocabulary stayed
    invisible, and common words scored the same as rare ones. That is the
    grep-instead-of-seek failure applied to the brain's own past.

WHY A SEPARATE FILE, NOT `neural_map.json`
    Two reasons, both load-bearing.
    1. PRIVACY. Memories carry CURP, IBAN, rates, family and immigration files.
       neural_map.json is gitignored today, but it is the PUBLIC brain's index
       and one wrong .gitignore edit would leak 200+ personal facts in a single
       commit. A separate, separately-ignored file keeps the blast radius small
       and the boundary legible.
    2. PRECISION. Adding N unrelated documents to the skill/agent corpus dilutes
       the IDF weights that make skill recall sharp. Same argument as
       skills/harmonization-over-accretion: more nodes is not more intelligence.

    The TF-IDF machinery itself is IMPORTED from generate_neural_map.py, never
    copied. One tokenizer, one vocabulary builder, one cosine. A second copy
    would drift and the two indexes would disagree about what a word is worth.

OUTPUT
    <brain>/memory_map.json  (gitignored — see .gitignore)

USAGE
    python3 ~/.claude/scripts/generate_memory_map.py
    python3 ~/.claude/scripts/generate_memory_map.py --quiet
"""

import json
import math
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

BRAIN_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRAIN_DIR / "scripts"))

# One tokenizer, one vocabulary, one cosine — imported, never reimplemented.
from generate_neural_map import (  # noqa: E402
    tokenize,
    build_vocabulary,
    cosine_similarity,
)

# The index is MACHINE STATE, not repo content: it belongs next to
# neural_map.json in the real brain, never in a dimension worktree. projects/ is
# gitignored, so it exists only in ~/.claude and a worktree would find nothing.
LIVE_BRAIN = Path.home() / ".claude"
if not (LIVE_BRAIN / "projects").exists():
    LIVE_BRAIN = BRAIN_DIR
LEXICON_FILE = Path(__file__).resolve().parent / "memory_lexicon_es_en.json"
OUTPUT_FILE = LIVE_BRAIN / "memory_map.json"
PROJECTS_DIR = LIVE_BRAIN / "projects"

# Each stored vector keeps only its heaviest terms. The full norm is stored
# alongside, so cosine against the truncated vector stays close to the true
# value while the file stays small enough to load on every prompt.
TOP_TERMS = 80

# Nearest neighbours per memory. Enough to answer "does this already exist?"
# without turning the file into a dense N^2 matrix.
TOP_NEIGHBOURS = 6

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def strip_accents(text):
    """Fold accents before tokenizing.

    The shared tokenizer keeps only [a-z][a-z0-9]{2,}, so an accent SPLITS the
    word and eats its head: 'Malaga' with its accent tokenizes as 'laga', and
    'dia' disappears entirely. Every Spanish memory was therefore indexed under
    mutilated stems. Folding first is what makes 'sesion', 'revision' and
    'cotizacion' real terms instead of 'sesi', 'revisi', 'cotizaci'.

    Applied on BOTH sides (build and query) so the two always agree.
    """
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def mem_tokenize(text):
    """The shared tokenizer, accent-folded. One definition, both sides."""
    return tokenize(strip_accents(text))


_LEXICON_CACHE = None


def load_lexicon():
    """ES<->EN groups as {term: set(all terms in its group)}. Empty on failure.

    Cached: score_prompt is called once per prompt by the hook but in a loop by
    any batch tool, and re-reading the JSON each time turned a 600-call probe
    into a timeout.
    """
    global _LEXICON_CACHE
    if _LEXICON_CACHE is not None:
        return _LEXICON_CACHE
    try:
        data = json.loads(LEXICON_FILE.read_text(encoding="utf-8"))
    except Exception:
        _LEXICON_CACHE = {}
        return _LEXICON_CACHE
    out = {}
    for group in data.get("groups", []):
        members = {strip_accents(t).lower() for t in group}
        for t in members:
            out.setdefault(t, set()).update(members)
    _LEXICON_CACHE = out
    return out

# MEMORY.md is the index over the memories, not one of them. README.md is
# scaffolding copied into every project dir by the memory template: 8 identical
# copies that carry no fact and would collide on slug.
SKIP_FILES = {"MEMORY.md", "README.md"}


def find_memory_dirs():
    """Every projects/<id>/memory/ directory that actually holds memories."""
    if not PROJECTS_DIR.exists():
        return []
    return sorted(
        d for d in PROJECTS_DIR.glob("*/memory") if d.is_dir() and any(d.glob("*.md"))
    )


def parse_frontmatter(text):
    """Return (meta dict, body). Absent or malformed frontmatter yields ({}, text)."""
    m = FM_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    key = None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if km and not line.startswith((" ", "\t")):
            key = km.group(1)
            val = km.group(2).strip().strip('"').strip("'")
            if val:
                meta[key] = val
        elif key and line.startswith((" ", "\t")):
            # nested metadata block (metadata:\n  type: feedback)
            nm = re.match(r"^\s+([A-Za-z_][\w-]*):\s*(.*)$", line)
            if nm and nm.group(2).strip():
                meta[nm.group(1)] = nm.group(2).strip().strip('"').strip("'")
    return meta, text[m.end():]


def read_memory(project, path):
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, body = parse_frontmatter(text)
    name = meta.get("name") or path.stem
    return {
        # Keyed by project too: the same slug can legitimately exist in two
        # project memory dirs, and a bare-slug key silently dropped one of them.
        "key": f"{project}/{path.stem}",
        "project": project,
        "id": path.stem,
        "name": name,
        "title": name.replace("_", " ").replace("-", " "),
        "description": meta.get("description", "")[:400],
        "type": meta.get("type", "unknown"),
        "path": str(path),
        # The body carries the substance; the description alone is too thin to
        # separate two memories that share a topic but differ in the lesson.
        # Accent-folded at the source: build_vocabulary tokenizes internally, so
        # folding here is what reaches the vectors.
        "text": strip_accents(f"{name} {meta.get('description', '')} {body}"),
    }


def truncate_vector(vec):
    """Keep the heaviest TOP_TERMS terms, but remember the TRUE norm.

    Cosine computed against a truncated vector with the full norm is a slight
    UNDER-estimate, never an over-estimate: dropped terms can only add to the
    dot product. Under-estimating is the safe direction for a recall floor.
    """
    import math

    norm = math.sqrt(sum(v * v for v in vec.values()))
    top = dict(sorted(vec.items(), key=lambda kv: -kv[1])[:TOP_TERMS])
    return top, norm


# ── Query side ────────────────────────────────────────────────────────────────
# Lives here, next to the builder, so the SEEK uses the exact weights the BUILD
# produced. Two consumers import these (query_connectome.py `memory` verb and
# brain-memory-recall.py); a second implementation would drift from the index.


def load_index(path=None):
    """Load memory_map.json. Returns None when absent or unreadable (fail-open).

    Recall must never break a prompt: every caller treats None as "fall back",
    never as an error.
    """
    p = Path(path) if path else OUTPUT_FILE
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# The harness names projects/<slug> by folding EVERY non-alphanumeric character
# to "-", then truncating very long names. Folding only the separators one
# happens to notice (/, ., _) matches the common paths and quietly misses the
# rest: a path with a space, +, @, ( or : computes a slug that names no project.
# That is silent under-recall — the arm's own memories vanish from its own seek
# while the scope line still claims to include them.
_SLUG_RE = re.compile(r"[^a-zA-Z0-9]")
_SLUG_MAX = 200


def project_slug(path, projects_root=None):
    """Slugify a path the way the harness names projects/<slug>.

    Verified against every project dir on this machine, and against the cases
    the naive fold missed ("My Project", "repo+v2", "cli@ent", "a(b)").

    Long paths: the harness truncates past ~200 chars and appends a hash whose
    exact construction is NOT verified here. Rather than guess it and be
    confidently wrong, this resolves such a path by PREFIX against the real
    directory listing when one is available, and otherwise returns the
    untruncated slug, which simply matches nothing. Guessing a hash would
    produce a slug that looks right and points at another project.
    """
    s = _SLUG_RE.sub("-", str(Path(path).resolve()))
    if len(s) <= _SLUG_MAX:
        return s
    root = Path(projects_root) if projects_root else (LIVE_BRAIN / "projects")
    try:
        head = s[:_SLUG_MAX]
        matches = sorted(d.name for d in root.iterdir()
                         if d.is_dir() and d.name.startswith(head))
        if len(matches) == 1:
            return matches[0]
    except Exception:
        pass
    return s


def brain_project_slug():
    """The central brain's own project dir name.

    A session started in $HOME is a brain session, and its dir holds the CENTRAL
    memories: generic lessons and operator identity, meant to reach every
    session. Every other dir is cwd-scoped, and for an arm that means
    arm-scoped.
    """
    return project_slug(Path.home())


def score_prompt(index, text, top_n=5, min_score=0.04, projects=None):
    """Rank memories against free text by cosine over the stored IDF weights.

    `projects` is an ALLOWLIST of projects/<id> dir names, and it FILTERS.
    It used to be a single dir that merely biased the score, and that was an
    Arm Isolation violation: CLAUDE.md Core Principle #1 says an arm never knows
    another exists, and a biasing seek happily surfaced one arm's memories into
    another arm's session (measured: a DRAGON session was shown a HANNON memory).
    A cross-arm leak is not a recall improvement, it is the one thing the
    octopus architecture forbids.

    The caller passes the session's own project dir plus the central brain dir
    (see brain_project_slug); passing None means no filter and is for
    operator-driven tools that are already global, never for a hook.
    """
    if not index:
        return []
    idf = index.get("idf") or {}
    nodes = index.get("nodes") or {}
    toks = mem_tokenize(text)
    if not toks:
        return []

    tf = {}
    for t in toks:
        tf[t] = tf.get(t, 0) + 1

    # Bridge the language gap. The operator writes Spanish; many memories are in
    # English, and a lexical index scores ZERO across that gap ('cobro/hora' vs
    # 'rate/hourly'). Counterparts enter at reduced weight so a real hit still
    # outranks a bridged one.
    lex = load_lexicon()
    if lex:
        for t in list(tf):
            for alt in lex.get(t, ()):
                if alt not in tf:
                    tf[alt] = 0.5
    qvec = {t: (1 + math.log(c)) * idf[t] for t, c in tf.items() if t in idf}
    if not qvec:
        return []
    qnorm = math.sqrt(sum(v * v for v in qvec.values()))

    # `is not None`, not truthiness: an EMPTY allowlist means "nothing is
    # allowed", and treating it as "no filter" inverts the intent in exactly the
    # direction that leaks.
    allow = set(projects) if projects is not None else None
    out = []
    for key, node in nodes.items():
        if allow is not None and node.get("project") not in allow:
            continue
        vec = node.get("vector") or {}
        shared = qvec.keys() & vec.keys()
        if not shared:
            continue
        dot = sum(qvec[k] * vec[k] for k in shared)
        denom = qnorm * (node.get("norm") or 1.0)
        score = dot / denom if denom else 0.0
        if score >= min_score:
            out.append((round(score, 4), key, node))
    out.sort(key=lambda r: -r[0])
    return out[:top_n]


def main():
    quiet = "--quiet" in sys.argv
    t0 = datetime.now(timezone.utc)

    def say(*a):
        if not quiet:
            print(*a)

    dirs = find_memory_dirs()
    if not dirs:
        say("No memory directories under projects/. Nothing to index.")
        return 0

    memories = []
    for d in dirs:
        for f in sorted(d.glob("*.md")):
            if f.name in SKIP_FILES:
                continue  # MEMORY.md is the index; README.md is template scaffolding
            memories.append(read_memory(d.parent.name, f))

    if not memories:
        say("No memory files found. Nothing to index.")
        return 0

    say(f"Reading {len(memories)} memories from {len(dirs)} directory(ies)...")

    docs = {m["key"]: m["text"] for m in memories}
    vectors, idf = build_vocabulary(docs)
    say(f"   Vocabulary: {len(idf):,} terms · {len(vectors)} vectorized")

    # Nearest neighbours — this is what answers "do I already have this lesson?"
    neighbours = {}
    ids = list(vectors.keys())
    for i, a in enumerate(ids):
        sims = []
        for b in ids:
            if a == b:
                continue
            s = cosine_similarity(vectors[a], vectors[b])
            if s > 0.05:
                sims.append((round(s, 4), b))
        sims.sort(reverse=True)
        neighbours[a] = [{"key": b, "score": s} for s, b in sims[:TOP_NEIGHBOURS]]

    nodes = {}
    for m in memories:
        vec = vectors.get(m["key"], {})
        top, norm = truncate_vector(vec)
        nodes[m["key"]] = {
            "id": m["id"],
            "project": m["project"],
            "name": m["name"],
            "title": m["title"],
            "description": m["description"],
            "type": m["type"],
            "path": m["path"],
            "vector": top,
            "norm": round(norm, 6),
            "neighbours": neighbours.get(m["key"], []),
        }

    # A silent shrink between "read" and "indexed" is exactly the truncation
    # class this index exists to kill. Refuse to write a lossy map.
    # Assert on what can ACTUALLY go wrong. len(nodes) == len(memories) always
    # holds, since both are keyed by the same unique project/stem, so the old
    # check could never fire: it was decoration, not a guard. What does happen is
    # a document that vectorizes to nothing (binary, empty, all stop words) and
    # is then unreachable by any seek while still occupying a node.
    # Two different failures, two different responses.
    #
    # A memory the vectorizer never saw is LOSSY: something dropped it between
    # read and build, and writing the map would hide that. Hard fail.
    #
    # A memory that vectorizes to NOTHING (all stop words, two-line placeholder,
    # binary) is not lossy, it is unindexable. Refusing the whole map for one
    # such file was all-or-nothing in the worst place: ai_sync runs the
    # generator with its return code ignored, so the refusal was SILENT and the
    # stale index just persisted. Skip it, name it, keep the map, and record it
    # in diagnostics so it stays visible instead of becoming folklore.
    missing = [m["key"] for m in memories if m["key"] not in vectors]
    if missing:
        print(
            f"FAIL: {len(missing)} memories were read but never vectorized. "
            "That is data loss between read and build; not writing the map.",
            file=sys.stderr,
        )
        for k in missing[:10]:
            print(f"  - {k}", file=sys.stderr)
        return 1

    unindexable = sorted(k for k, n in nodes.items() if not n["vector"] or not n["norm"])
    for k in unindexable:
        del nodes[k]
        neighbours.pop(k, None)
    if unindexable:
        # stderr unconditionally, NOT say(). ai_sync invokes this generator with
        # --quiet, so routing the warning through say() muted the only visible
        # signal and the skip became invisible outside diagnostics.
        print(f"! {len(unindexable)} of {len(memories)} memory(ies) carry no "
              "indexable term; excluded from the map and listed in "
              "diagnostics.unindexable:", file=sys.stderr)
        for k in unindexable[:10]:
            print(f"    - {k}", file=sys.stderr)
        if len(unindexable) == len(memories):
            # Not corruption. TF-IDF drops terms that appear in only one
            # document, so a corpus of a handful of memories that share no
            # vocabulary yields an empty index by construction. Say so, or a
            # fresh brain reads this as data loss.
            print("  ALL of them: the corpus is too small for TF-IDF, which "
                  "drops any term appearing in a single document. This is the "
                  "shape of a nearly-empty brain, not corrupted memories.",
                  file=sys.stderr)

    linked = sum(1 for n in nodes.values() if n["neighbours"])
    out = {
        "meta": {
            "generated": t0.isoformat(),
            "generator": "generate_memory_map.py",
            "memories": len(nodes),
            "vocabulary": len(idf),
            "top_terms_per_vector": TOP_TERMS,
            "private": True,
            "note": (
                "Life-memories index. NEVER commit: gitignored alongside "
                "neural_map.json, and pinned by a [paths] rule in "
                ".githooks/push-policy.txt so a wrong .gitignore edit still "
                "blocks at push time. Bodies stay on disk, but the vectors hold "
                "TERMS VERBATIM, and memory terms include identity-shaped "
                "strings (tax ids, account numbers). Treat this file as "
                "sensitive as the memories themselves, not as anonymous weights."
            ),
        },
        "idf": {k: round(v, 6) for k, v in idf.items()},
        "nodes": nodes,
        "diagnostics": {
            "isolated": [i for i, n in nodes.items() if not n["neighbours"]],
            "linked": linked,
            # Read but unreachable by any seek: no term survived tokenizing.
            # Not an error, but never silent either.
            "unindexable": unindexable,
        },
    }

    OUTPUT_FILE.write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    size_kb = OUTPUT_FILE.stat().st_size / 1024
    say(f"   {len(nodes)} memory nodes · {linked} with neighbours · {size_kb:.0f} KB")
    say(f"   -> {OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
