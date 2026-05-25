# Octorato Wiki — source pages

These 14 pages are the official Octorato wiki, authored by 10 specialist agents
and passed through a document review (accuracy + generic-safety) and a lean
editorial review (voice + de-duplication).

They use GitHub **wiki-link** syntax (`[[Page]]`), which renders on the GitHub
Wiki tab but not in plain `docs/` Markdown. They live here because a GitHub wiki
cannot be pushed to via git until its **first page is created once in the web
UI** (GitHub only provisions `repo.wiki.git` after that).

## Publish to the GitHub Wiki (one-time, ~1 min)

1. Open https://github.com/CarlosCaPe/octorato/wiki and click **"Create the
   first page"** → save anything (e.g. "init"). This provisions `octorato.wiki.git`.
2. Run the publisher (regenerates the indexes from the live brain + pushes all
   pages):
   ```bash
   python3 ~/dataqbs-local-cron/scripts/generate-octorato-wiki.py   # Skills/Agents/Home/Sidebar
   # then push the reviewed prose pages from this dir:
   cd /tmp && rm -rf owiki && \
     git clone "https://x-access-token:$(gh auth token)@github.com/CarlosCaPe/octorato.wiki.git" owiki && \
     cp ~/.claude/docs/wiki/*.md owiki/ && rm -f owiki/README.md && cd owiki && \
     git add -A && git -c user.name="Carlos Carrillo" -c user.email="carlos.carrillo@dataqbs.com" \
       commit -m "wiki: publish Octorato docs" && git push
   ```

Until then, these files ARE the wiki content — version-controlled and reviewable
in the repo.
