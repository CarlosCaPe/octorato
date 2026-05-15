---
name: lii5
description: >
  Bridge technical knowledge gaps using adult language — not childish, not jargon-heavy.
  Produce clear, accessible explanations of any document, concept, policy, architecture,
  or codebase. Uses analogies and plain adult vocabulary to make unfamiliar domains
  immediately understandable. Trigger when user says "lii5", "li5", "LI5",
  "explain like i'm 5", "explícame como si tuviera 5 años", "ELI5", "hazlo simple",
  "dumb it down", or "en cristiano".
---

# LII5 — Bridge the Technical Gap

## Purpose
Close the knowledge gap between "I've never seen this domain" and "I understand
what matters here" — using **adult vocabulary**, not baby talk. The reader is
intelligent but lacks context in this specific area. Give them the mental model
fast, with real words, so they can participate in conversations about it immediately.

**This is NOT dumbing down. This is accelerated onboarding.**

## Triggers
- `lii5`, `li5`, `LI5`, `ELI5`
- "explain like I'm 5", "explícame como si tuviera 5 años"
- "hazlo simple", "en cristiano", "dumb it down"
- "what does this mean in plain English?"

## Workflow

1. **Identify the target** — what document/concept/section needs bridging
2. **Read the source** — load the full content (don't summarize from memory)
3. **Extract key rules** — identify the 5-10 most important takeaways
4. **Bridge** — rewrite each using a relatable analogy + adult-level plain language
5. **Format** — use a table: `| Concept | What it means |` for scannable output
6. **One-liner** — end with a single sentence that captures the entire thing

## Format Template

```markdown
## LI5 — [Document/Concept Name]

**[One-sentence framing that anchors the analogy — written for an adult]**

| Concept | What it means |
|---------|---------------|
| **[Topic]** | [Plain-language explanation — adult vocabulary, zero jargon] |
| ... | ... |

**En una frase:** "[Single sentence summary]"
```

## Principles

- **Adult language** — write for a smart person who just hasn't seen this domain before.
  Don't say "it's like when mommy gives you cookies." Say "think of it as a warehouse
  inventory — every item has a tag, an owner, and a shelf location."
- **Analogies as bridges, not crutches** — use an analogy to build the mental model,
  then connect it back to the real term so they learn the vocabulary too
- **Consistent metaphor** — pick ONE analogy per document and extend it:
  - Policies → "company rulebook for equipment and behavior"
  - Architecture → "factory floor with stations and conveyor belts"
  - Database → "filing system with cabinets, drawers, and labels"
  - API → "front desk that takes requests and routes them to the right department"
  - Security → "building access: badges, cameras, locked doors"
  - Infrastructure → "utilities: plumbing (network), electricity (compute), water tank (storage)"
- **Language match** — respond in the language the user writes in
- **Brevity** — max 10 rows per table. If more, split into sections
- **One-liner mandatory** — always end with "En una frase:" / "In one sentence:"
- **Connect back** — after the analogy, name the real technical term so the reader
  can use it in meetings: "This is what engineers call _role-based access control (RBAC)_."

## Anti-Patterns

- **Don't be patronizing** — no "imagine you're a little kid" framing
- Don't just make sentences shorter — actually bridge the knowledge gap
- Don't use "basically" or "essentially" — those are filler, not clarification
- Don't add caveats or edge cases in the LI5 — save nuance for follow-up
- Don't strip all technical terms — introduce them gently after the analogy

## Examples

### Input: "lii5 RBAC"
> **Think of your office building: everyone gets a badge, but each badge opens different doors.**
>
> | Concept | What it means |
> |---------|---------------|
> | **Roles** | Job titles that determine access — developer, manager, admin. Each one maps to a set of permissions. |
> | **Permissions** | Which doors (resources) each badge (role) can open. A developer can deploy code; only an admin can delete the database. |
> | **Assignment** | When someone joins, they get the badge for their role. Change role → badge changes automatically. |
>
> This is what engineers call _role-based access control (RBAC)_ — you define what each role can do once, then assign people to roles.
>
> **En una frase:** "Your job title decides what you can access — not your name."

### Input: "ELI5 this Terraform config"
> **Terraform is an infrastructure order form. You describe what you need; it figures out what to provision, modify, or tear down.**
>
> | Concept | What it means |
> |---------|---------------|
> | **Resources** | Each block declares something you need — a server, a database, a network rule. |
> | **State file** | Terraform's inventory of what already exists. It compares your order form against this to know what changed. |
> | **Plan** | A preview: "here's what I'd change if you approve." Read-only, safe to run anytime. |
> | **Apply** | Executes the plan. Creates, updates, or destroys resources to match your order form. |
>
> Engineers call this _infrastructure as code (IaC)_ — instead of clicking buttons in a cloud console, you write a file that describes the end state.
>
> **In one sentence:** "You declare what you want, Terraform reconciles reality to match."
