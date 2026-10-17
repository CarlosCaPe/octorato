# Token-Efficient Prompting

> Reduce LLM output token usage by 50-75% without signal loss through structured CLAUDE.md rules and domain-specific profiles.
> Source: [drona23/claude-token-efficient](https://github.com/drona23/claude-token-efficient) (benchmarked: ~63% avg reduction)

## Purpose

Minimize output tokens in LLM interactions — especially agent pipelines, automation, and repeated tasks — by eliminating sycophancy, filler, preamble, unsolicited suggestions, and formatting noise. Net savings only positive when output volume offsets the persistent input cost of rules.

## Triggers

- Building CLAUDE.md files for new projects
- Configuring agent pipelines that need terse, parseable output
- Optimizing token costs in automation workflows (resume bots, code gen loops)
- When Claude output is verbose, sycophantic, or includes unsolicited suggestions
- Setting up multi-agent systems with strict output budgets
- Task: "reduce tokens", "make output concise", "stop verbose", "token budget"

## When NOT to Use

- Single short queries (input overhead > output savings)
- Exploratory or architectural work where debate is the point
- When guaranteed parseable output is needed (use structured outputs / JSON mode instead)
- Casual one-off use at low volume

## Universal Rules (Drop-In CLAUDE.md)

The minimal set that produces ~63% reduction:

```markdown
## Approach
- Think before acting. Read existing files before writing code.
- Be concise in output but thorough in reasoning.
- Prefer editing over rewriting whole files.
- Do not re-read files you have already read unless the file may have changed.
- Test your code before declaring done.
- No sycophantic openers or closing fluff.
- Keep solutions simple and direct.
- User instructions always override this file.
```

## Core Formatting Rules

```markdown
Short sentences only (8-10 words max).
No filler, no preamble, no pleasantries.
Tool first. Result first. No explain unless asked.
Code stays normal. English gets compressed.
No em-dashes or replacement hyphens.
Avoid parenthetical clauses entirely.
```

## Domain Profiles

### Coding Profile
Best for: dev projects, code review, debugging, refactoring.

- Return code first. Explanation after, only if non-obvious.
- Simplest working solution. No over-engineering.
- No abstractions for single-use operations.
- No speculative features or "you might also want..."
- Read the file before modifying it. Never edit blind.
- No docstrings or type annotations on code not being changed.
- Three similar lines is better than a premature abstraction.
- Review: State the bug. Show the fix. Stop.
- Debug: Never speculate without reading code first. State finding + fix. One pass.

### Agents / Pipeline Profile
Best for: automation pipelines, multi-agent systems, bots, scheduled tasks.

- Structured output only: JSON, bullets, tables. No prose.
- Every output must be parseable without post-processing.
- Execute the task. Do not narrate what you are doing.
- No status updates like "Now I will..." or "I have completed..."
- No asking for confirmation on clearly defined tasks.
- If a step fails: state what failed, why, and what was attempted. Stop.
- No decorative Unicode: no smart quotes, em dashes, or ellipsis characters.
- All strings must be safe for JSON serialization.
- Never invent file paths, API endpoints, function names, or field names.
- If a value is unknown: return null or "UNKNOWN". Never guess.
- Return the minimum viable output that satisfies the task spec.

### Analysis / Research Profile
Best for: data analysis, research, financial analysis, reporting.

- Lead with the finding. Context and methodology after.
- Tables and bullets over prose paragraphs.
- Numbers must include units. Never ambiguous values.
- Never state a number without a source or derivation.
- If data is missing: say so. Do not estimate silently.
- Distinguish clearly between what the data shows and what is inferred.
- Summary first (3 bullets max), supporting data second, caveats last.

## Tool Budget Pattern (Progressive Minimalism)

Evolution from verbose to minimal (learned from v5 → v6 → v8):

| Version | Budget | Key Change |
|---------|--------|------------|
| v5 (50 calls) | Read all → Plan → Write → Test → Fix → Verify | Full 6-step |
| v6 (30 calls) | Read ALL including tests → Write complete in one pass → Test once → Fix once max | Eliminated iteration |
| v8 (20 calls) | Read ALL → Write COMPLETE in single write → Test once → If fail, fix once → Stop | Maximum compression |

**Key insight:** Read the test file BEFORE writing code. The test defines success. Write the complete solution in one pass, not incrementally. Never iterate more than once on the same error.

## Anti-Patterns Eliminated

| Anti-Pattern | Token Cost | Fix |
|-------------|-----------|-----|
| "Sure! I'd be happy to..." opener | ~10 tokens/response | Rule: no sycophantic openers |
| "I hope this helps!" closer | ~8 tokens/response | Rule: no closing fluff |
| Restating the question | ~20 tokens/response | Rule: result first |
| "You might also want..." suggestions | ~30 tokens/response | Rule: no unsolicited extras |
| "As an AI, I should note..." | ~15 tokens/response | Rule: no AI self-reference |
| Em dashes, smart quotes, ellipsis | ~2-5 tokens/response | Rule: plain ASCII only |
| Agreeing before correcting ("You're absolutely right that...") | ~10 tokens | Rule: direct correction |

## Benchmark Evidence

5-prompt benchmark (Drona Gangarapu, 2026-03-30):

| Test | Category | Reduction |
|------|----------|-----------|
| T1 | Verbose/Preamble/Closing | 64% |
| T2 | Sycophancy/Scope creep | 75% |
| T3 | ASCII/Framing/Disclaimer | 50% |
| T4 | Prompt triple format | N/A (format) |
| T5 | Hallucination correction | 64% |

**Average: ~63% output token reduction. Zero signal loss. All tests passed.**

Caveat: 5-prompt sample, no variance controls. Independent replication found shorter 7-12 line configs outperform longer rule sets on total tokens for coding tasks.

## Trade-Off Decision Matrix

| Scenario | Use Rules? | Reason |
|----------|-----------|--------|
| Agent pipeline (100+ calls) | YES | Compound savings dominate |
| Code generation loop | YES | Output volume high |
| Single question | NO | Input overhead > savings |
| Casual chat | NO | Not worth the rigidity |
| Team project (many devs) | YES | Consistency + savings |
| Exploratory architecture | NO | Need debate, not compression |

## Integration with Existing Skills

- **llm-system-prompt-engineering** — Complements: that skill designs system prompts for chatbots (sandwich pattern, attention decay). This skill handles output efficiency rules for dev workflows.
- **deep-grep-code-review** — Coding profile rules apply when reviewing code found via deep grep.
- **document-code-review** — Analysis profile applies when generating review reports.

## Lessons Learned

1. **Shorter configs win** — Independent testing showed 7-12 line CLAUDE.md files outperform longer rule sets on total tokens (input + output combined).
2. **CLAUDE.md > in-prompt rules** — File-based rules cost ~30% less than pasting rules in chat (caching).
3. **Pipeline multiplier** — In agent loops, every token saved per call multiplies across hundreds of runs.
4. **Net negative at low volume** — The CLAUDE.md file loads as input tokens on every message. Short sessions lose money.
5. **Structured outputs > prompt rules** — For guaranteed parseable output at scale, use API-level JSON mode / tool schemas, not prompt-based formatting rules.
