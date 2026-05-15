---
name: llm-system-prompt-engineering
description: Design, debug, and optimize LLM system prompts for production chatbots — especially smaller/medium models (7B-70B) that suffer from attention decay in long prompts. Use when a chatbot ignores rules, repeats itself, fabricates content, or when prompt patches stop working and structural redesign is needed.
metadata:
  short-description: System prompt architecture for production chatbots
  created: 2026-03-23
  origin: production chatbot — 7 iterations debugging Llama 3.3 70B behavior
---

# LLM System Prompt Engineering

Design system prompts that smaller/medium models (7B–70B) actually follow. Born from debugging a production RAG chatbot where 6 iterations of "add more rules" failed until a structural rewrite fixed behavior in one shot.

## When to Use

- Chatbot ignores specific instructions (especially mid-prompt rules)
- Adding more rules makes behavior worse, not better
- Model repeats itself despite explicit anti-repetition rules
- Model fabricates content despite "don't invent" rules
- Switching from a large model (GPT-4, Claude) to a smaller one (Llama, Mistral)
- System prompt exceeds ~2000 tokens and model compliance drops

## Core Problem: Lost-in-the-Middle

Smaller LLMs have a U-shaped attention curve — they attend strongly to the **beginning** (primacy) and **end** (recency) of the system prompt, but attention drops 40-60% for content in the middle. This is well-documented in research ("Lost in the Middle", Liu et al. 2023).

**Implication**: Rules placed in the middle of a long system prompt get ignored. Adding more rules to fix violations pushes existing rules further into the dead zone, creating a vicious cycle.

## Architecture: The Sandwich Pattern

```
┌─────────────────────────────────┐
│  GOLDEN RULES (top)             │  ← Primacy zone: 3-5 override rules
│  Most-violated behaviors here   │
├─────────────────────────────────┤
│  TOPIC SECTIONS (middle)        │  ← Low-attention zone: factual content
│  Projects, pricing, contact     │     Keep lean, use examples not prose
│  These are reference, not rules │
├─────────────────────────────────┤
│  REMEMBER (bottom)              │  ← Recency zone: reinforce golden rules
│  "Rules 1-5 override everything"│
└─────────────────────────────────┘
```

### Golden Rules (Top — Primacy Zone)
- Maximum 5 rules. Numbered. Imperative voice.
- Cover the model's most-violated behaviors, not obvious ones.
- Each rule = one sentence. No explanations, no examples here.
- Format: `1. NEVER [bad behavior]. [What to do instead].`

### Topic Sections (Middle — Low-Attention Zone)
- Factual reference content: projects, pricing, contact info, capabilities.
- Use bullet lists, not paragraphs. Each bullet = one fact with a metric.
- GOOD/BAD examples only for complex behaviors. Keep to 2 lines each.
- This zone is for WHAT to say, not HOW to behave.

### Remember (Bottom — Recency Zone)
- 1-2 sentences reinforcing the golden rules by number.
- "Rules 1-5 at the top are GOLDEN. They override everything."
- This is the last thing the model "reads" before generating — make it count.

## Anti-Patterns (What Fails)

### 1. Rule Stacking
**Problem**: Adding a new section every time the model misbehaves.
**Why it fails**: Each new section pushes older rules into the dead zone. After 5-6 patches, the prompt is 4000+ tokens and the model ignores most of it.
**Fix**: Consolidate. One section per concern. Merge related rules.

### 2. Competing Examples
**Problem**: SECTION A says "list qualifying questions" with a GOOD example showing bullets. SECTION B says "never repeat qualifying questions." The model picks the easier one (listing).
**Fix**: Differentiate by conversation state. First-mention example (with list) vs follow-up example (without list). Put both in the SAME section.

### 3. Verbose Rules
**Problem**: 3-paragraph explanation of why not to fabricate info.
**Why it fails**: The model reads tokens, not intent. More words ≠ more compliance. Long rules dilute attention budget.
**Fix**: `NEVER invent information not in CONTEXT chunks. Period.` (one line)

### 4. Undifferentiated Conversation State
**Problem**: Same rules apply whether user's first message or 5th follow-up. Model defaults to most detailed example (usually the first-message pattern) every time.
**Fix**: Explicit CONVERSATION FLOW section with 3 states:
- **First time a topic comes up** → full answer + details
- **Follow-up on same topic** → short confirmation + something NEW
- **Vague confirmation ("sí", "ok")** → redirect to contact/action

## Token Budget Guidelines

| Model Size | Max System Prompt | Sweet Spot |
|-----------|------------------|------------|
| 7-13B | 800 tokens | 400-600 |
| 30-70B | 2000 tokens | 1000-1500 |
| 100B+ | 4000 tokens | 2000-3000 |

Going above sweet spot = diminishing returns. Compliance drops non-linearly.

## Debugging Checklist

When a chatbot misbehaves despite having rules:

1. **Count tokens** — is the prompt in the sweet spot for the model?
2. **Map violations to prompt position** — are broken rules in the middle?
3. **Check for competing sections** — do two sections give contradictory guidance?
4. **Check conversation state** — does the prompt differentiate first-time vs follow-up?
5. **Check examples** — does the model have a GOOD example for the exact failing scenario?
6. **Strip and test** — remove 50% of the prompt. Does behavior improve? If yes, the prompt is too long, not too short.

## Svelte/Frontend Gotcha

When wiring event handlers to functions with optional parameters:

```svelte
<!-- BAD: MouseEvent passed as first argument -->
<button on:click={handleSend}>Send</button>

<!-- GOOD: Arrow function isolates the call -->
<button on:click={() => handleSend()}>Send</button>
```

If `handleSend(directMessage?: string)`, the bad version passes the MouseEvent object as `directMessage`, which is truthy but not a string. `.trim()` fails silently or the function processes garbage input.

## Lessons Learned

| Date | Pattern | Root Cause | Fix |
|------|---------|-----------|-----|
| 2026-03-23 | LLM ignores anti-repetition rules after 6 prompt patches | Prompt grew to 4000+ tokens (14 sections). Rules in middle ignored by Llama 3.3 70B. | Rewrote prompt: 14→10 sections, 4000→1500 tokens. Golden Rules at top + REMEMBER at bottom. |
| 2026-03-23 | LLM always outputs qualifying bullet list even on follow-ups | ASSESSMENT section had ONE example (with bullets). No follow-up example. Model defaulted to only pattern it had. | Added separate first-mention and follow-up examples in same section. |
| 2026-03-23 | LLM fabricates methodology on vague "sí" | No instruction for vague confirmations. Model filled the void with hallucinated content. | Added explicit vague-confirmation handling: redirect to contact form, don't invent. |
| 2026-03-23 | Send button click didn't work (only Enter key) | `on:click={handleSend}` passed MouseEvent as `directMessage` parameter. | Changed to `on:click={() => handleSend()}`. |
