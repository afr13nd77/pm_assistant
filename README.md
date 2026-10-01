[![CI](https://github.com/afr13nd77/pm_assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/afr13nd77/pm_assistant/actions/workflows/ci.yml)
[![GitHub release](https://img.shields.io/github/release/afr13nd77/pm_assistant.svg)](https://github.com/afr13nd77/pm_assistant/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[Русская версия](readme_ru.md)

# PM Assistant

## What it is

PM Assistant is a software implementation of a product-knowledge management methodology for a product manager at an OTA company. It automates the full lifecycle of an idea: from a raw thought in Telegram to a finished epic in Jira.

The foundation is a **file-based knowledge vault** (Markdown files) managed through **Obsidian**, organized according to Andrej Karpathy's model: **raw -> compile -> wiki**. The vault is synced to **Yandex.Disk**, providing backup, multi-device access, and manual editing via Obsidian.

The backend is 4 microservices deployed in **Docker** on a local server. Natural language processing uses a **hybrid LLM architecture**: local **Ollama** for routine tasks with automatic fallback to **Claude API** for complex operations (synthesis, pipeline, enrichment), plus **OpenRouter** for meeting transcriptions. Voice messages are transcribed locally via **faster-whisper**.

Regular analytical tasks (morning digest, daily dev status, weekly report, competitor analysis) run through **Claude Desktop Cowork** scheduled tasks against the vault. Nightly raw-queue processing runs via headless Claude Code.

---

## Architecture

| Layer | Component | Role |
|---|---|---|
| Knowledge vault | Obsidian vault (raw -> wiki) | Single source of truth, synced to Yandex.Disk |
| Backend | **pm-bot** | Telegram bot, Vault API (FastAPI), Web UI server |
| Backend | **knowledge-engine** | Enrichment, synthesis, Jira sync, linter, indexer, News Moderator |
| Backend | **idea-pipeline** | AI agent chain: Analyst -> PM -> Decomposer |
| Backend | **ke-cron** | Scheduled jobs (synthesis, Jira sync, lint, vault health) |
| Observability | **langfuse** | Self-hosted LLM tracing (:3100) |
| LLM layer | Ollama (local) / Claude API / OpenRouter | Hybrid routing with automatic fallback |

All services share one Obsidian vault mounted as a Docker volume. See `index.md` for the full data model (idea lifecycle, Jira task classes, domain structure) and vault architecture details.

---

## Web UI

SPA dashboard on Vue 3 + vanilla JS, data served via the Vault API. Dual theme (MATRIX dark / LIGHT), server-side stored.

| Page | Purpose |
|---|---|
| today.html | Start-of-day: morning digest, focus, CalDAV meetings, TODO, news/signals |
| overview.html | Command center: system status, idea funnel, KPIs, activity feed |
| ideas.html | Idea kanban by status, domain filter, drag-n-drop, readiness % |
| board.html | Task kanban by type (BACKEND/FRONTEND/TESTING/RESEARCH/DESIGN) |
| dashboard.html | Domains, artifact stats, Jira sync status |
| roadmap.html | Epics with progress across Backlog/Todo/In Progress/Done |
| timeline.html | Feature timeline |
| report.html | Weekly report viewer |
| settings.html | LLM provider, transcription provider, prompts, Jira sync |
| decay.html | Decay dashboard: tier distribution, projection, forgotten gems |
| about.html | Component versions, changelog |

---

## Quick Start

### Docker (recommended)

```bash
# Start
docker compose up --build

# Background mode
docker compose up -d

# Logs
docker compose logs -f pm-bot

# Rebuild
docker compose down && docker compose build --no-cache && docker compose up -d
```

### Local development

```bash
cd pm-bot
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # fill in the variables
python -m app.main
```

---

## Environment Variables

Required variables only — see `index.md` for the full list.

| Variable | Service | Description |
|---|---|---|
| BOT_TOKEN | pm-bot | Telegram bot token |
| CLAUDE_API_KEY | pm-bot, KE, pipeline | Claude API key |
| VAULT_PATH | all | Path to the Obsidian vault |
| TRANSCRIPTS_INBOX | pm-bot | Folder for incoming transcripts |
| ALLOWED_CHAT_ID | pm-bot | Owner chat ID (empty = first-run mode) |
| PIPELINE_API_URL | pm-bot | idea-pipeline API URL |
| JIRA_URL | KE | Jira server URL |
| JIRA_TOKEN | KE | Personal Access Token |

---

## Tech Stack

| Dependency | Version | Service |
|---|---|---|
| Python | 3.12 | all |
| python-telegram-bot | 21.5 | pm-bot |
| anthropic | >=0.40.0 | pm-bot, knowledge-engine, idea-pipeline |
| FastAPI / uvicorn | >=0.111.0 / >=0.30.0 | pm-bot, idea-pipeline |
| faster-whisper | >=1.0.0 | pm-bot |
| Vue.js / marked.js | 3.x / 15.x (CDN) | web-ui |
| Docker Compose | v3.9 | infrastructure |
| Langfuse SDK | >=2.0.0,<3.0.0 | pm-bot, knowledge-engine, idea-pipeline |
| Claude model | claude-sonnet-4-6 | pm-bot, knowledge-engine, idea-pipeline |

---

## Project Stats

Development ongoing since 07.05.2026. **219 ideas captured**, **115 features shipped**, **36 bugs fixed**.

Current versions: pm-bot 1.30.0 · knowledge-engine 1.25.0 · idea-pipeline 1.3.0 · web-ui 1.33.0 · shared 0.7.5.

---

For vault health scoring, file naming conventions, pipeline metrics, data flows, prompt catalogue, and scheduled Cowork tasks — see `index.md`.
