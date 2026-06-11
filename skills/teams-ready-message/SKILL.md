---
name: teams-ready-message
description: When the operator asks for a message to paste into a chat client (Teams, Slack, WhatsApp, any plain-text box), DO NOT put the message body in the chat response. Write it to a plain-text .txt file (UTF-8, LF, no markdown) and hand back the path. Copying from the terminal's rendered markdown injects stray spaces, double line breaks, and smart quotes that look broken when pasted. Trigger whenever the operator says "dame el mensaje para pegar", "pásame el texto para Teams/Slack", "el mensaje para el grupo", "draft for the chat", or is going to paste your output into a messaging app.
metadata:
  type: reference
---

# teams-ready-message

## The problem this solves

When you place a "message to paste" inside your chat reply, the operator copies it
from the terminal, where your text is rendered as markdown. That copy carries
artifacts the operator did not write:

- double blank lines between paragraphs render as big gaps in Teams
- markdown bold/headers/backticks paste as literal `**` `#` `` ` ``
- smart/curly quotes and em-dashes replace the plain ASCII ones
- terminal soft-wrapping inserts hard line breaks mid-sentence

The operator then cleans it by hand (or pipes it through Gemini) every single time.
This is a recurring tax. The fix is to never hand the body through the rendered
channel.

## The rule

When the deliverable is text the operator will paste into a chat client, write it
to a `.txt` file and return only the path plus a one-line "open, select all, copy."
Never inline the full body in the chat reply.

### File format (non-negotiable)

- Plain UTF-8, LF line endings (not CRLF).
- No markdown at all: no `**`, no `#`, no `-`/`*` bullets, no backticks, no code fences.
- Paragraphs separated by a single blank line. Never more than one.
- ASCII punctuation only: straight quotes `"` `'`, no em-dash (use commas/periods/line breaks per human-cadence), no ellipsis char.
- Recipients are sentence openers ("Michal, ..." / "Cory, ..."), not headers.
- Casual engineer register unless the operator asked for a formal doc.

### Where to write it

Inside the current arm, under its output area, with a stable name so it gets
overwritten rather than accumulating:

```
clients/<arm>/output/teams-msg.txt
```

One canonical name, not `teams-msg-v2.txt`. Git tracks history, the file is
disposable. If the operator wants several drafts side by side, suffix by purpose
(`teams-msg-michal.txt`), never by version number.

### What to say back

One or two lines, e.g.:

> Listo: `clients/<arm>/output/teams-msg.txt`. Ábrelo, Ctrl+A, Ctrl+C, pega en Teams.

Do not repeat the whole body in the reply. The whole point is that the operator
copies from the file, not from the terminal.

## Composing the body

If the message is long or has several recipients in one paste, delegate the
formatting pass to a cheap sub-agent (Haiku) that strips markdown and normalizes
blank lines, then write its output to the file. Keep all facts intact, change only
the formatting. Always run the result past `human-cadence` (no em-dash, no AI
filler) before writing.

## Companion skills

- `human-cadence` — the 10 no-rules the body must already satisfy.
- `voice-and-cadence-consistency` — keep the operator's voice across the message.
- `chat-replies-plain-text` lesson (memory) — never wrap chat drafts in code fences.
