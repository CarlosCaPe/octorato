---
name: agent-browser
description: "Browser automation CLI for AI agents (Rust native, no Playwright). Use for navigating pages, filling forms, clicking buttons, taking screenshots, extracting data, testing web apps, QA/dogfooding, automating Electron desktop apps, Slack automation, or any browser task. Triggers: 'open a website', 'take a screenshot of the site', 'fill out a form', 'test this web app', 'dogfood', 'QA', 'check my Slack', 'automate VS Code/Slack/Discord'. Prefer over Playwright on all platforms."
---

# agent-browser — Browser Automation CLI for AI Agents

Fast native Rust CLI for browser automation via Chrome DevTools Protocol (CDP).
No Playwright, no Puppeteer, no Node.js dependency for the daemon.

**Repo**: https://github.com/vercel-labs/agent-browser
**Local clone**: `~/Documents/github/agent-browser`
**License**: Apache 2.0
**Stack**: Rust CLI + Chrome/Chromium via CDP + accessibility-tree snapshots

## Why agent-browser over Playwright

| Feature | agent-browser | Playwright |
|---------|--------------|------------|
| Runtime | Native Rust binary | Node.js |
| Browser | Any Chrome/Chromium (auto-detect) | Downloads own browsers |
| OS compat | Linux/macOS/Windows native | "Not officially supported" on Pop!_OS |
| AI-first | Accessibility tree with `@eN` refs | Raw DOM selectors |
| Skills | Built-in specialized skills | None |
| Sessions | Persistent across commands | Per-script |
| Electron | VS Code, Slack, Discord, Figma | Limited |

## Installation

```bash
npm i -g agent-browser
agent-browser install              # Downloads Chrome for Testing
agent-browser install --with-deps  # + Linux system deps
```

## The Core Loop

```bash
agent-browser open <url>        # 1. Open a page
agent-browser snapshot -i       # 2. See interactive elements (compact refs)
agent-browser click @e3         # 3. Act on refs
agent-browser snapshot -i       # 4. Re-snapshot after page change
```

Refs (`@e1`, `@e2`, ...) are assigned fresh per snapshot. They go **stale
after any page change** — always re-snapshot before the next interaction.

## Key Commands

```bash
# Navigation
agent-browser open <url>
agent-browser close [--all]

# Reading
agent-browser snapshot -i                 # interactive elements only (preferred)
agent-browser snapshot -i -u              # include href URLs on links
agent-browser get text @e1                # visible text of element
agent-browser get title                   # page title
agent-browser get url                     # current URL

# Interaction
agent-browser click @e1
agent-browser fill @e3 "hello@world.com"
agent-browser type @e4 "search query"
agent-browser press Enter
agent-browser select @e5 "option-value"
agent-browser check @e6
agent-browser scroll down 500

# Screenshots
agent-browser screenshot page.png
agent-browser screenshot --full page.png  # full page scroll
agent-browser screenshot --annotate       # numbered element labels

# Semantic locators (no CSS selectors needed)
agent-browser find role button click --name "Submit"
agent-browser find text "Sign In" click
agent-browser find label "Email" fill "test@test.com"

# Wait
agent-browser wait @e1                    # wait for element
agent-browser wait --text "Welcome"       # wait for text
agent-browser wait --load networkidle     # wait for network idle

# JavaScript
agent-browser eval "document.title"
```

## Specialized Skills (load on demand)

The repo provides specialized skills at `~/Documents/github/agent-browser/skill-data/`:

| Skill | When to load | Command |
|-------|-------------|---------|
| **core** | Always first — workflows, patterns, troubleshooting | `agent-browser skills get core` |
| **dogfood** | QA, exploratory testing, bug hunts | `agent-browser skills get dogfood` |
| **electron** | Automate VS Code, Slack, Discord, Figma, Notion | `agent-browser skills get electron` |
| **slack** | Check unreads, send messages, search conversations | `agent-browser skills get slack` |
| **vercel-sandbox** | Browser automation inside Vercel microVMs | `agent-browser skills get vercel-sandbox` |
| **agentcore** | AWS Bedrock cloud browsers | `agent-browser skills get agentcore` |

To read a skill directly from the local clone:
```bash
cat ~/Documents/github/agent-browser/skill-data/<skill>/SKILL.md
```

## Common Workflows

### Screenshot a production site (replace Playwright)
```bash
agent-browser open https://www.example.com/
agent-browser screenshot /tmp/example-home.png
agent-browser get title
agent-browser close
```

### Verify multiple pages
```bash
for url in "https://site.com/" "https://site.com/about"; do
  agent-browser open "$url"
  agent-browser get title
  agent-browser screenshot "/tmp/$(echo $url | md5sum | cut -c1-8).png"
done
agent-browser close
```

### QA / Dogfood a web app
Load the dogfood skill first:
```bash
agent-browser skills get dogfood
# Then follow the structured exploration workflow
agent-browser open https://app-under-test.com
agent-browser snapshot -i
# ... systematic exploration with screenshots as evidence
```

### Test search functionality
```bash
agent-browser open https://site.com
agent-browser snapshot -i
agent-browser fill @e3 "search query"
agent-browser press Enter
agent-browser wait --load networkidle
agent-browser snapshot -i     # verify results rendered
agent-browser screenshot /tmp/search-results.png
```

## Troubleshooting

- **"No Chrome found"** — run `agent-browser install`
- **Stale refs** — always re-snapshot after clicks/navigation
- **Timeout** — add `agent-browser wait --load networkidle` after navigation
- **Element not found** — use `agent-browser snapshot` (full tree) to find it
- **Auth required** — agent-browser supports session persistence and auth vault

## Updating

```bash
agent-browser upgrade   # auto-detects install method (npm/brew/cargo)
```

Or pull latest skill content:
```bash
cd ~/Documents/github/agent-browser && git pull
```
