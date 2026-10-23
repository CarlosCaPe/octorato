---
name: infinite-monitor
description: "Builds AI dashboards on Infinite Monitor, an open-source Next.js app where you describe the widget in natural language and an agent writes and deploys it on an infinite canvas. Triggers on 'crea un dashboard para'."
---

# Infinite Monitor — AI-Powered Dashboard Builder

Build dashboards by describing widgets in plain English. An AI agent writes the React code, builds it in a secure V8 sandbox, and renders it live in an iframe on an infinite canvas.

**Repo**: https://github.com/homanp/infinite-monitor
**License**: MIT
**Stack**: Next.js 16 + React 19 + SQLite (Drizzle ORM) + Secure Exec (V8 isolates) + Vercel AI SDK

## When to Use This Skill

- User asks to create a monitoring dashboard for any domain
- User says "crea un dashboard para..." (Spanish trigger)
- User needs an AI-powered widget builder
- User wants OSINT, trading, cybersecurity, analytics, or any domain-specific dashboard
- User wants to visualize data from APIs in real-time

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Next.js App                                            │
│  ┌──────────────────────┐  ┌─────────────────────────┐  │
│  │  Infinite Canvas     │  │  Chat Sidebar           │  │
│  │  (pan / zoom / grid) │  │  (AI conversation)      │  │
│  │  ┌──────┐ ┌──────┐   │  │  User describes widget  │  │
│  │  │iframe│ │iframe│   │  │  Agent writes code       │  │
│  │  │  w1  │ │  w2  │   │  │  Agent builds in sandbox │  │
│  │  └──────┘ └──────┘   │  │  Widget renders live     │  │
│  └──────────────────────┘  └─────────────────────────┘  │
└──────────────────┬──────────────────────────────────────┘
     ┌─────────────┼─────────────────┐
     ▼             ▼                 ▼
┌─────────┐  ┌──────────┐  ┌─────────────────┐
│ SQLite  │  │ Secure   │  │ AI Providers    │
│ (state) │  │ Exec V8  │  │ (BYOK)          │
│ widgets │  │ Vite     │  │ 15+ providers   │
│ layouts │  │ sandbox  │  │ 35+ models      │
└─────────┘  └──────────┘  └─────────────────┘
```

### Components
- **Client**: Next.js 16 + React 19, Zustand store, infinite canvas with pan/zoom/minimap
- **Server**: Next.js API routes, Vercel AI SDK, SQLite via Drizzle ORM, CORS proxy
- **Widget Runtime**: Secure Exec sandbox (V8 isolate) — no Docker needed. Agent writes files, Vite builds, served as static HTML in iframes
- **Widget Template**: React 18, Tailwind CSS, Recharts, MapLibre GL, Framer Motion, date-fns, Lucide icons, shadcn/ui

## Prerequisites

- **Node.js 22+** (required for `isolated-vm` native addon used by Secure Exec)
- **npm** (lockfile: `package-lock.json`)
- At least one AI provider API key (Anthropic, OpenAI, Google, xAI, Mistral, DeepSeek, Groq, etc.)

## Setup Workflow

### 1. Clone and Configure

```bash
git clone https://github.com/homanp/infinite-monitor.git
cd infinite-monitor
```

### 2. Create `.env.local`

```bash
# Pick one or more providers (or enter keys in the UI later)
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# GOOGLE_GENERATIVE_AI_API_KEY=...
# XAI_API_KEY=...
# MISTRAL_API_KEY=...
# DEEPSEEK_API_KEY=...
# GROQ_API_KEY=...
# OPENROUTER_API_KEY=...     # Free models available via OpenRouter

# Optional: share/publish
# DURABLE_STREAM_BASE_URL=   # defaults to https://stream.tonbo.dev
# SHARE_ID_SECRET=           # secret for deriving stable share IDs
```

Full env vars: see `.env.example` in the repo.

### 3. Install and Run

```bash
npm install
npm run dev
# Open http://localhost:3000
```

### 4. Production Build

```bash
npm run build
npm start
```

### 5. Deploy to Railway (optional)

Configure GitHub Actions secrets:
- `RAILWAY_TOKEN` — project token from Project > Settings > Tokens
- `RAILWAY_SERVICE_ID` — service ID from Railway dashboard

The deploy workflow at `.github/workflows/deploy.yml` runs `railway up`.

## How to Build a Dashboard

### Step-by-step

1. Open http://localhost:3000
2. Click **Add Widget**
3. In the chat sidebar, describe what you want in plain English:
   - "Show a live Bitcoin price chart with 24h history"
   - "Create a weather widget for Guadalajara with temperature and humidity"
   - "Build a table showing my top GitHub repos by stars"
4. The AI agent writes React code, installs dependencies, and builds in sandbox
5. Widget renders live in an iframe on the canvas
6. **Iterate**: chat to refine — the agent rewrites and rebuilds in seconds
7. Drag, resize, and organize widgets on the infinite canvas

### Dashboard-Aware Agents

Each widget's AI agent can see what other widgets exist on the same dashboard and read their source code. This means it builds complementary components — not duplicates.

### Example Prompts by Domain

| Domain | Widget Prompt |
|--------|--------------|
| **Trading** | "Show a candlestick chart for BTC/USDT with RSI indicator and volume bars" |
| **Cybersecurity** | "Display a threat map showing recent CVEs from NVD API colored by severity" |
| **OSINT** | "Create a Shodan search widget that queries for open ports on a given IP range" |
| **Analytics** | "Build a GA4-style metrics card showing users, sessions, and bounce rate" |
| **DevOps** | "Show server health dashboard with CPU, memory, and disk usage gauges" |
| **Crypto** | "Display a multi-exchange arbitrage table comparing BTC prices across exchanges" |
| **Weather** | "Build a 5-day forecast widget with temperature charts and weather icons" |
| **Social** | "Create a Twitter/X sentiment tracker for a given hashtag" |
| **Finance** | "Show a portfolio tracker with stock prices, daily change %, and a sparkline" |
| **Real Estate** | "Display property listings from a JSON API with price, photos, and location map" |

### Multiple Dashboards

Create separate dashboards for different domains. Switch between them instantly from the sidebar.

### Dashboard Templates

Start from pre-built templates for common domains, or build from scratch.

## Key Features

- **BYOK (Bring Your Own Key)** — 15 AI providers, 35+ models. Keys stored in browser localStorage only
- **Dashboard-aware agents** — agents see sibling widgets and avoid duplication
- **Infinite canvas** — pan, zoom, drag, resize, grid-snap
- **Live web search** — agent searches the web for API docs and patterns while building
- **SQLite persistence** — auto-created at `./data/widgets.db` (or `DATABASE_PATH` env)
- **Security**: Brin threat scanning on external URLs (score < 30 = blocked)

## Useful Commands

| Action | Command |
|--------|---------|
| Install deps | `npm install` |
| Dev server | `npm run dev` (port 3000) |
| Lint | `npm run lint` |
| Tests | `npm test` (vitest) |
| Production build | `npm run build` |
| Makefile shortcuts | `make setup`, `make dev`, `make lint`, `make test` |

## Non-Obvious Notes

- Secure Exec sandboxes: no Docker daemon needed. Each widget gets its own V8 isolate with filesystem, networking, and child process capabilities.
- SQLite DB auto-created at `./data/widgets.db`. No migrations command needed; schema applied automatically.
- If you change `.env.local` while dev server is running, you MUST restart the dev server.
- Husky pre-commit hook runs `lint-staged` (ESLint + TypeScript type-check on `src/**/*.{ts,tsx}`).
- Widget template includes ALL shadcn/ui components, Recharts, MapLibre GL, Framer Motion out of the box.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `isolated-vm` build fails | Ensure Node.js 22+ is installed. Run `npm rebuild` |
| No AI response | Check that at least one API key is set in `.env.local` or entered in the UI |
| Widget build fails in sandbox | Check Secure Exec logs. The agent will auto-retry with error context |
| Port 3000 in use | Set `PORT=3001` in `.env.local` or kill the existing process |

## Lessons Learned

- OpenRouter provides free model access — good for testing without paid API keys
- Dashboard-aware agents work best when you name your widgets clearly
- Complex widgets (maps, charts) may need 2-3 iterations to get right
- The agent responds better to specific data sources ("use CoinGecko API") than vague requests ("show crypto data")
