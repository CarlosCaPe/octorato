#!/usr/bin/env python3
"""
Eye Check Hook — Forces agent-browser usage for web tasks.

Runs on every UserPromptSubmit. Pure local regex — no API calls, 0 cost, <5ms.
Scans the user's prompt for web-related triggers (URLs, keywords in EN/ES/DE).
If triggered, injects additionalContext reminding the agent it has eyes via agent-browser.

This is Layer 1 of the "octopus eyes" system:
  Layer 1: Hook (harness-level, always fires, can't be forgotten)
  Layer 2: CLAUDE.md rule (agent-level, defense-in-depth)
  Layer 3: agent-browser skill (loaded on demand with full workflow)
"""

import json
import re
import sys
import shutil
# Force UTF-8 on stdout/stderr so the ✓ / ✗ / em-dash glyphs in reports
# survive on Windows shells defaulting to cp1252. Without this, a script
# can do its work correctly and still crash with UnicodeEncodeError when
# printing success. Applied repo-wide by _apply-utf8-reconfigure.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ── Trigger patterns ─────────────────────────────────────────────
# URLs
URL_PATTERN = re.compile(
    r'https?://[^\s<>\"]+|'           # explicit URLs
    r'\b\w+\.(com|io|dev|org|net|app|pages\.dev)\b',  # domain mentions
    re.IGNORECASE
)

# Keywords that imply "the agent needs to SEE a web page"
# Organized by language: English, Spanish, German
WEB_KEYWORDS = re.compile(
    r'\b('
    # English
    r'screenshot|dogfood|QA|browse|web\s?site|web\s?page|web\s?app|'
    r'open\s+the\s+site|check\s+the\s+site|look\s+at|visual\s+check|'
    r'link\s+preview|render|how\s+does\s+it\s+look|'
    # Spanish
    r'captura|pantalla|screenshot|sitio\s+web|p[aá]gina\s+web|'
    r'abre\s+el\s+sitio|revisa\s+el\s+sitio|mira\s+el\s+sitio|'
    r'c[oó]mo\s+se\s+ve|verifica\s+el\s+sitio|prueba\s+el\s+sitio|'
    r'verifica\s+que\s+funcione|checa\s+el\s+sitio|dogfoodea|'
    r'como\s+se\s+ve|mira\s+la\s+p[aá]gina|abre\s+la\s+p[aá]gina|'
    r'preview|vista\s+previa|'
    # German
    r'Webseite|Website|Bildschirmfoto|'
    r'schau\s+dir\s+die\s+Seite\s+an|pr[uü]fe\s+die\s+Seite'
    r')\b',
    re.IGNORECASE
)

# Anti-triggers: prompts about code/config that mention URLs but don't need a browser
ANTI_TRIGGERS = re.compile(
    r'\b('
    r'git\s+clone|git\s+remote|npm\s+i|pip\s+install|'
    r'curl\s+-|fetch\(|import\s+from|require\(|'
    r'\.env|wrangler|deploy|middleware|routing'
    r')\b',
    re.IGNORECASE
)


def needs_eyes(prompt: str) -> bool:
    """Determine if the prompt requires visual browser inspection."""
    has_url = bool(URL_PATTERN.search(prompt))
    has_keyword = bool(WEB_KEYWORDS.search(prompt))
    has_anti = bool(ANTI_TRIGGERS.search(prompt))

    # URL + keyword = strong signal (e.g., "revisa example.com")
    if has_url and has_keyword:
        return True

    # Keyword alone with strong visual intent
    if has_keyword and not has_anti:
        return True

    # URL alone without anti-trigger, only if prompt is short (likely "check this site")
    if has_url and not has_anti and len(prompt.split()) < 20:
        return True

    return False


def is_installed() -> bool:
    """Check if agent-browser CLI is available."""
    return shutil.which("agent-browser") is not None


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    prompt = hook_input.get("prompt", "").strip()
    if not prompt or len(prompt) < 5:
        sys.exit(0)

    # Skip slash commands
    if prompt.startswith("/"):
        sys.exit(0)

    if not needs_eyes(prompt):
        sys.exit(0)

    # Build context injection
    installed = is_installed()

    if installed:
        context = (
            "[Eye Check — agent-browser DETECTED]\n"
            "This prompt involves web content. You MUST use agent-browser (not curl, not Playwright) "
            "to inspect, screenshot, or interact with web pages.\n\n"
            "Quick reference:\n"
            "  agent-browser open <url>         # navigate\n"
            "  agent-browser snapshot -i        # see interactive elements\n"
            "  agent-browser screenshot f.png   # capture visual evidence\n"
            "  agent-browser click @eN          # interact (re-snapshot after!)\n\n"
            "Load full skill: read ~/.claude/skills/agent-browser/SKILL.md\n"
            "NEVER use curl to check if a page 'looks right' — curl has no eyes. "
            "NEVER say 'I cannot see the page' — you CAN, via agent-browser."
        )
    else:
        context = (
            "[Eye Check — agent-browser NOT INSTALLED]\n"
            "This prompt involves web content but agent-browser is not installed.\n"
            "Install it: npm i -g agent-browser && agent-browser install\n"
            "Until installed, use Playwright MCP as fallback, but prefer agent-browser."
        )

    output = {"additionalContext": context}
    json.dump(output, sys.stdout)


if __name__ == "__main__":
    main()
