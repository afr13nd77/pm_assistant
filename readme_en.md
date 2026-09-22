[![CI](https://github.com/afr13nd77/pm_assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/afr13nd77/pm_assistant/actions/workflows/ci.yml)
[![GitHub release](https://img.shields.io/github/release/afr13nd77/pm_assistant.svg)](https://github.com/afr13nd77/pm_assistant/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

[Русская версия](README.md)

# PM Assistant

## What it is

PM Assistant is a software implementation of a product-knowledge management methodology for a product manager at an OTA company.

The project automates the full lifecycle of an idea: from a raw thought in Telegram to a finished epic in Jira. It's not just a bot — it's a working system of 4 microservices that implements the rules described in the Knowledge Base Agent configuration (CLAUDE.md of the project's knowledge vault).

The foundation of the system is a **file-based knowledge vault** (Markdown files) managed through **Obsidian**. The vault is connected to **Yandex.Disk** and automatically syncs to the cloud, providing backup, access from multiple devices, and collaborative work.

The backend consists of 4 microservices (**pm-bot**, **knowledge-engine**, **idea-pipeline**, **ke-cron**) deployed in a **Docker container** on a local server.

Natural language processing uses a **hybrid LLM architecture**: local **Ollama** (QWEN 3.5 model) for routine tasks with automatic fallback to **Claude API** for complex operations (synthesis, pipeline, enrichment). For transcriptions, **OpenRouter** is available (QWEN3-32B and other models) with a fallback chain OpenRouter → Ollama → Claude API. Voice messages are transcribed locally via **faster-whisper** (small model, CPU).

Regular analytical tasks (morning digest, daily development status, weekly report, market and competitor analysis) are performed through **Claude Desktop Cowork** — scheduled tasks configured to work with the Obsidian vault. Nightly processing of the raw-file queue is done via headless Claude Code.

---

## Vault architecture: the Karpathy model

The vault is designed according to Andrej Karpathy's model: **raw -> compile -> wiki**.

### Three layers

1. **raw/** — immutable originals (append-only). Everything captured (an idea from Telegram, a meeting transcript, a Jira ticket, a web clipping) is stored here as-is. Files are never edited. The wiki can be recompiled from the raw material at any time.

   Subfolders: `inbound/ideas/`, `inbound/meeting-notes/`, `inbound/daily-logs/`, `inbound/tasks/`, `inbound/clippings/`, `inbound/misc/`, `competitors/`, `metrics/`.

2. **wiki/** — compiled knowledge. A living encyclopedia organized by product domains. Structured notes with YAML frontmatter, cross-references, and indexes.

   Top level: `wiki/domains/`, `wiki/meetings/`, `wiki/daily-logs/`, `wiki/reports/`, `wiki/concepts/`, `wiki/teams/`, `wiki/projects/`, `wiki/INDEX.md`, `wiki/LOG.md`.

3. **templates/** — artifact templates (idea, epic, userstory, task, bug, ADR), editable without code and visible in Obsidian.

### Philosophy: vault-as-database

The Obsidian vault with Markdown files replaces a classic database:

- Frontmatter = metadata (id, status, domain, tags, created, jira_key, etc.)
- File body = content
- File system = index
- Full history available through git
- Files are simultaneously human-readable (in Obsidian) and machine-readable (via API)

### Domain grouping

Each domain is an autonomous unit with its own structure:

```
wiki/domains/{domain}/
├── ideas/       # ideas with 9 fields and readiness %
├── epics/       # epics with horizons and progress
├── tasks/       # tasks (Jira and internal)
├── bugs/        # bugs
├── knowledge/   # knowledge files (clippings, references)
├── index.md     # auto-generated table of contents
├── log.md       # change log
├── decisions.md # architecture decisions (ADR)
└── glossary.md  # domain terminology
```

Current domains: `static-metadata`, `suggester` (predlagator), `search-engine`, `partner-search-engine`, `general` (cross-domain tasks).

### Ingest: raw -> wiki

The process of processing files from raw/ and turning them into structured notes in wiki/. Each type of incoming file has its own algorithm:

- `raw/inbound/ideas/` — determine domain — `wiki/domains/{domain}/ideas/{slug}.md`
- `raw/inbound/meeting-notes/` — extract action items — tasks, decisions — decisions.md
- `raw/inbound/misc/` — classify — concepts/ or teams/ or projects/ or domains/
- `raw/inbound/clippings/` — determine domain — `wiki/domains/{domain}/knowledge/{slug}.md`
- `raw/competitors/` — only a LOG.md entry, report to the team

Domain detection is automatic based on keywords (domain_detection rules in CLAUDE.md). On conflict — ask the user. If no match is found — default domain + warning in LOG.md.

---

## System architecture

The system consists of 4 layers, each solving its own task.

### 1. Knowledge vault

The foundation of the entire system is an **Obsidian vault** with Markdown files organized according to the Karpathy model (raw -> compile -> wiki). The vault is the single source of truth: all artifacts (ideas, tasks, epics, meeting minutes, reports) are stored as structured Markdown files with YAML frontmatter.

The vault is connected to **Yandex.Disk** and automatically syncs to the cloud. This provides:
- Backup of all data
- Access to the vault from any device (work computer, laptop, phone)
- The ability to manually edit notes via Obsidian on any device with automatic synchronization of changes

### 2. Backend (Docker)

4 microservices deployed in a Docker container on a local server:

- **pm-bot** — Telegram bot, Vault API (FastAPI), and Web UI server. Entry point for all user interactions with the system
- **knowledge-engine** — knowledge enrichment and synthesis service, watchdog for incoming files, Jira integration, linter, indexer
- **idea-pipeline** — orchestrator that processes ideas through a chain of AI agents (Analyst -> PM -> Decomposer)
- **ke-cron** — cron container for periodic tasks (synthesis, Jira sync, rebuild index, lint, vault health, cowork-context)
- **langfuse** — self-hosted LLM observability (prompt traces, tokens, cost). Available at http://<server-ip>:3100

All services work with the same Obsidian vault, mounted as a Docker volume.

### 3. LLM layer

Hybrid architecture with two providers:

| Provider | Model | Purpose | When used |
|---|---|---|---|
| **Ollama** (local) | QWEN 3.5 | Routine tasks: classification, keyword extraction, simple structuring | Default for tasks not requiring deep analysis |
| **Claude API** (cloud) | claude-sonnet-4-6 | Complex tasks: synthesis, enrichment, pipeline (analysis + PRD + decomposition), weekly reports | For tasks requiring deep context understanding |
| **OpenRouter** (cloud) | QWEN3-32B (and 5 others) | Transcriptions: processing meeting minutes | Configurable in Settings as Transcription Provider |

Selection strategy:
- In **Hybrid** mode (default) — the system automatically selects a provider depending on the task type. If Ollama is unavailable or returns a low-quality result — automatic fallback to Claude API
- In **Claude** mode — all requests go through Claude API
- In **Ollama** mode — all requests go through local Ollama
- In **Transcription Provider** settings — you can choose OpenRouter for processing meeting transcriptions (fallback: Ollama → Claude API)

Mode switching — via Web UI (Settings) or environment variables.

### 3.1. Speech-to-Text

Voice messages from Telegram are transcribed locally via **faster-whisper** (`small` model, CPU, int8). Automatic language detection, lazy model loading on the first voice message. Controlled by the `STT_ENABLED` variable (enabled by default).

### 4. Regular tasks (Claude Desktop Cowork)

Analytical and reporting tasks are executed on a schedule via **Claude Desktop Cowork** — scheduled tasks in which Claude Desktop is configured to work with the Obsidian vault as its working context.

| Task | Schedule | Executor |
|---|---|---|
| Morning digest (morning-digest) | Mon-Fri 08:31 MSK | Cowork scheduled task |
| Daily development status (daily-dev-status-report) | Daily 18:00 MSK | Cowork scheduled task |
| Weekly report (weekly-pm-report) | Friday | Cowork scheduled task |
| Market and competitor analysis (competitor-analysis) | Every 2 weeks | Cowork scheduled task |
| Nightly raw queue processing (vault-ingest-queue) | Daily 02:00 MSK | Headless Claude Code (Windows Task Scheduler) |

Cowork tasks work directly with the vault files via Obsidian, generating reports and digests based on the current state of the vault. Headless Claude Code is used for nightly batch processing, where control over the model matters (pinned to `claude-sonnet-4-6` via the `--model` flag).

---

## Idea lifecycle

An idea goes through 4 statuses: **New -> Hypothesis Validation -> Ready for Production -> Discarded** (Новая -> Проверка гипотезы -> Готова к производству -> Отсев).

### 9 mandatory fields

**Block 1: Idea Passport** (filling this out = 44% readiness, transition to "Hypothesis Validation"):

1. Problem / Pain — whose and what pain we're solving
2. Solution — what exactly we're proposing
3. Value (USP) — how it differs from the current state
4. Metric — what will change numerically. No metric = Discarded.

**Block 2: Boarding Pass** (filling this out = 100% readiness, transition to "Ready for Production"):

5. Segment (Who) — a specific group of users
6. Job Story — "When [situation], I want [motivation], so that [outcome]"
7. In scope — functionality of the first version
8. Out of scope — what we deliberately won't do
9. Constraints — technical, business, regulatory

### Readiness %

`Readiness = (filled fields / 9) * 100%`

- 0-43% — status "New" (Новая)
- 44-99% — status "Hypothesis Validation" (Проверка гипотезы)
- 100% + validation artifact — status "Ready for Production" (Готова к производству)

### Feedback loop

When an epic is created, `epic_ref: EPIC-XXX` is added to the idea's frontmatter. When the epic is closed, a "Result" section is appended to the end of the idea (metric grew / didn't grow / no data). This way the idea becomes a complete case: hypothesis -> what was done -> what was achieved.

---

## Three classes of tasks

Three classes of tasks coexist in the knowledge base:

| | Jira task | Internal task | Personal TODO |
|---|---|---|---|
| Marker | `jira_key: GO-114` | `task_id: TASK-01` | `TODO-NNN` |
| Source | jira-sync (automatic) | idea decomposition pipeline | manual creation |
| File | one file per task | one file per task | one `todo.md` |
| Statuses | 25+ values from Jira as-is | todo / in-progress / done / cancelled | todo / in-progress / done / cancelled |

Jira statuses are not normalized — Jira is the source of truth. Internal tasks have dependencies (`depends_on`): a task cannot move to `in-progress` until its dependencies are `done`.

---

## Components

### pm-bot (v1.30.0)

Telegram bot + Vault API + Web UI server. Entry point for all interactions.

Functions:

- Telegram handlers: /idea, /jira, /daily, /synthesize, /jira_sync, /jira_import, /jira_create, /pipeline, /domain, /lint, /status, /test_enrichment, /fetch_meetings, text, voice
- Claude API / Ollama / Hybrid — hybrid LLM architecture with fallback (Ollama: Qwen 3.5)
- OpenRouter API for transcriptions (6 models, fallback chain)
- Speech-to-Text (faster-whisper)
- transcript_watcher: puts local `.txt` files into the file queue `raw/meeting-queue/pending/` (no local LLM; processing is done by the KE worker) — BL-145
- Vault API (FastAPI, port 8000) with an in-memory TTL cache (30s), 23 APIRouter modules (app/routers/) instead of a monolithic vault_api.py
- Web UI static server (port 8080)
- APScheduler: enrichment reminders (daily), daily alert (Mon-Fri 18:00)
- SQLite: deduplication of enrichment reminders (24h cooldown)

### knowledge-engine (v1.25.0)

Knowledge enrichment and synthesis service.

Functions:

- Enrichment: enriching ideas with links from the vault
- Synthesis: idea clustering + summary
- Jira sync (cron every 3h): fetch JQL -> diff state -> write wiki/ + raw/ -> notify
- Jira import: import a single ticket by key
- Jira create: create tickets from the vault
- **Meeting Processing Queue (BL-145)**: three-phase minutes processing through a file queue `raw/meeting-queue/{pending,processing,done,failed}/`:
  - *Fetch* (`fetcher.py`): IMAP fetch -> puts raw transcripts into `pending/` (no LLM, fast); dedup `is_enqueued OR is_processed`
  - *Process* (`processor.py`): the worker takes one unit at a time -> LLM via fallback chain (`call_detailed`, max_attempts=5) -> `validate_protocol` (frontmatter type/date + H1 + length) -> classify -> write to `wiki/meetings/` -> jira sync -> enrich -> `done/`; on failure, retry with another provider or `failed/`
  - *Queue* (`queue.py`): atomic transitions (claim via `os.rename`), `reclaim_stuck`, `status_counts`
  - watchdog daemon `queue_watcher.py` (PollingObserver, near-realtime) + cron `process-queue` every 10 min (safety net)
- Meeting protocol enrichment: source_file in frontmatter + wikilink to the raw file in the footer (BL-133)
- Jira key sync for all protocol types (BL-134)
- Vault index: scanning, in-memory index, keyword + tag matching
- Linter: checking frontmatter, structure, broken links, idea status validation
- Status migrator: migrating legacy statuses to the canonical dictionary (4 statuses)
- Pipeline metrics: ingest ratio, avg lag raw→wiki, raw counts by type
- Domain manager: scaffold, index, activity log
- Watchdog: auto-enrichment when files appear in raw/inbound/
- **News Moderator (BL-189)**: an agentic chain for news analysis — relevance scoring → in-depth analysis (AgentLoop + QualityGate) → dispatch idea/report → idea extraction → persistent SQLite memory → weekly trend detection
- **Agent Observability (BL-190)**: monitoring and analytics for the agentic chain — Langfuse e2e trace, persistence of agent decisions (iterations_history, gate_results), 3 diagnostic HTTP endpoints (signals/runs, signals/stats), CLI `signal-status`
- **News Digest Converter (BL-191)**: converter from daily-news markdown → JSON digest for the moderate-news pipeline, CLI `convert-news-digest`, cron 07:55 Mon-Fri
- **Signal-First Pipeline (BL-203)**: a rework of News Moderator — the LLM creates a Signal (not an IDEA), and the PM decides via HITL triage. New functions: `generate_analysis_report()`, `extract_signals()`, `dispatch_signal()`. A Signal is stored in `raw/inbound/signals/` (JSON) + `wiki/reports/signals/` (MD). Triage via today.html: approve → dispatch_idea(), dismiss → rejection. Configurable threshold via settings.html

#### Force-running News Moderator
```
docker exec knowledge-engine python -m app moderate-news --notify
```

### idea-pipeline (v1.3.0)

Orchestrator that processes ideas through a chain of AI agents.

Chain: **Analyst -> PM -> Decomposer**

- Analyst: idea + vault context -> analysis
- PM: analysis -> PRD
- Decomposer: PRD -> Epic + Tasks (JSON)

The result is written to the vault: `Pipeline/<date>-<slug>/` (analysis.md, PRD.md, epic.md, tasks/*.md).

Configurable models per agent via pipeline.yaml. API key authentication.

### ke-cron

Cron container for periodic tasks:

- Synthesis: daily 09:00
- Meeting fetch (queue population): every hour at :15
- Process queue (safety net/reclaim): every 10 minutes (BL-145)
- Jira sync: every 3 hours
- Rebuild index: daily 02:00
- Lint: daily 03:00
- Vault health: daily 04:00
- News Digest Converter: Mon-Fri 07:55
- News Moderator: Mon-Fri 08:00
- Trend detect: Mon 06:00

### shared (v0.7.5)

Common module, single source for pm-bot, knowledge-engine, and idea-pipeline.

- llm_client: factory for LLM clients, routing by operation, call (fallback chain), call_detailed (returns a provider_record — BL-145), multi-model fallback chains with step normalization (BL-155), 429 backoff between openrouter steps, call_transcription
- meeting_queue: enqueue core of the file queue (Unit, make_unit_id, build_meta, enqueue, path helpers) — shared between KE-fetcher and pm-bot-watcher (BL-145)
- openrouter_client: HTTP client for the OpenRouter API, list_models with a live request and TTL cache (BL-156)
- file_writer: file_lock, atomic_write, locked_append
- vault_paths: 25 functions for vault paths
- domain_config: load/save domain-config.yaml
- frontmatter_utils: read/write YAML frontmatter
- settings: load settings.yaml, dot-notation (queue section — BL-145)

---

## Web UI (v1.33.0)

SPA dashboard on Vue 3 + vanilla JS. Static HTML pages, data via the Vault API.

| Page | Purpose |
|---|---|
| today.html | Start-of-day page: Morning Digest, focus of the day, CalDAV meetings, TODO, ready reports, news/signals |
| overview.html | Command center: system status, idea funnel, KPI metrics, donut chart, today's queue, activity feed, quick capture |
| ideas.html | Idea kanban: 4 columns by status (New / Hypothesis Validation / Ready / Discarded), domain filter, drag-n-drop, readiness %, capture drawer |
| board.html | Task kanban board: classification by jira_key, types from frontmatter (BACKEND, FRONTEND, TESTING, RESEARCH, DESIGN) |
| dashboard.html | Domains, artifact statistics, Jira sync status (overdue alert >3h) |
| roadmap.html | Roadmap: epics with progress, Backlog/Todo/In Progress/Done columns |
| timeline.html | Feature timeline |
| report.html | View weekly reports (Markdown -> HTML via marked.js) |
| settings.html | Settings: theme, refresh mode, LLM Provider (Claude/Ollama/Hybrid), Transcription Provider (Default/OpenRouter), multi-model OpenRouter fallback chains with inline model selector, prompts, Jira sync |
| decay.html | Decay state dashboard: bubble scatter, tier distribution, projection, domain bars, forgotten gems |
| about.html | About the service: component versions, changelog |

Dual theme: MATRIX (dark, glow/neon) and LIGHT (cream, warm). Switched in settings, stored server-side.

Refresh mode: auto (board 30s, roadmap 60s) or manual.

Drag-n-drop rules: readiness 100% required to move to "Ready", warning at < 44% for "Hypothesis Validation".

---

## Prompts

All prompts are stored in `app/prompts/*.txt` in each component:
- **pm-bot**: 5 prompts (idea, meeting, jira_ticket, daily, weekly_report)
- **knowledge-engine**: 24 prompts (enrich, synthesize, meeting_protocol, digest, signal_*, quality_*, research_report, etc.)
- **idea-pipeline**: 3 prompts (analyst, pm, decomposer)

### Managed via Settings UI

All 32 prompts are available for viewing and editing through the Settings web interface (http://localhost:8080/settings.html, PROMPTS section):
- A tree of prompts by component with accordion navigation
- A text editor for each prompt with `{var}` variable highlighting
- Saving with hot-reload (no container restart needed)
- Reset to the default version with one button

Prompts are a key customization point for tailoring the system to a specific company/domain. Basic setup requires only Docker + Settings UI, without access to the file system.

---

## Data flows

1. **Ideas**: Telegram/Web -> handlers -> claude_client.process_idea (->JSON) -> obsidian_writer.write_idea (template-based) -> `raw/inbound/ideas/` + `wiki/domains/<domain>/ideas/` -> knowledge-engine enrich
2. **Meeting transcripts (local)**: .txt -> transcript_watcher -> `raw/meeting-queue/pending/` -> (Process worker) -> `wiki/meetings/` (BL-145)
3. **Meeting fetcher (email)**: IMAP email -> fetch -> `raw/meeting-queue/pending/` (Fetch, no LLM) -> watchdog/cron Process worker -> LLM -> validate -> `wiki/meetings/` -> done/ (BL-145)
4. **Jira tickets**: Telegram /jira -> process_jira_ticket -> `raw/inbound/tasks/` + `wiki/domains/<domain>/tasks/`
5. **Daily notes**: Telegram /daily -> process_daily -> `raw/inbound/daily-logs/` + `wiki/daily-logs/`
6. **Jira Sync** (cron 3h or /jira_sync): fetch JQL -> diff state -> write `wiki/domains/<domain>/tasks/` + `raw/inbound/tasks/` -> notify
7. **Idea Pipeline**: Telegram /pipeline or API -> Analyst -> PM -> Decomposer -> `Pipeline/<date>-<slug>/`
8. **Enrichment Reminders** (daily cron): scan ideas -> filter by readiness < 100% -> SQLite cooldown -> Telegram notify
9. **Synthesis** (cron 09:00 or /synthesize): clustering + summary -> `wiki/reports/synthesis-*.md`
10. **News Moderator** (cron Mon-Fri 08:00 or /moderate-news): digest JSON -> scoring -> analysis (AgentLoop) -> dispatch idea/report -> idea_extractor -> `wiki/signals/` + `raw/inbound/ideas/`
11. **Trend Detect** (cron Mon 06:00 or /trend-detect): SQLite signal_memory -> entity_trends -> spike/sustained/new_entrant/escalation -> Telegram notify

---

## Stack

| Dependency | Version | Service |
|---|---|---|
| Python | 3.12 | all |
| python-telegram-bot | 21.5 | pm-bot |
| anthropic | >=0.40.0 | pm-bot, knowledge-engine, idea-pipeline |
| requests | >=2.31.0 | shared (openrouter_client) |
| FastAPI | >=0.111.0 | pm-bot, idea-pipeline |
| uvicorn | >=0.30.0 | pm-bot, idea-pipeline |
| watchdog | 4.0.1 / 6.0.0 | pm-bot, knowledge-engine |
| faster-whisper | >=1.0.0 | pm-bot |
| apscheduler | >=3.10.4 | pm-bot |
| python-frontmatter | >=1.1.0 | knowledge-engine, idea-pipeline |
| Vue.js | 3.x (CDN) | web-ui |
| marked.js | 15.x (CDN) | web-ui |
| Docker Compose | v3.9 | infrastructure |
| Langfuse SDK | >=2.0.0,<3.0.0 | pm-bot, knowledge-engine, idea-pipeline |
| Claude model | claude-sonnet-4-6 | pm-bot, knowledge-engine, idea-pipeline |

---

## Docker topology

6 containers:

| Container | Role | Ports |
|---|---|---|
| pm-bot | Telegram polling + Vault API + Web UI | 8000 (API), 8080 (Web) |
| knowledge-engine | HTTP API (:8001) + Watchdog on raw/inbound/ (auto-enrichment) + queue-watch on meeting-queue/pending/ (BL-145) | 8001 (API) |
| idea-pipeline | AI agent orchestrator | 8100 |
| ke-cron | Synthesis (09:00) + Cowork-context (01:00) + Meeting fetch (:15) + Process queue (every 10 min) + Jira sync (every 3h) + News Moderator (08:00 Mon-Fri) + Trend detect (06:00 Mon) | — |
| langfuse-db | PostgreSQL 15 — Langfuse storage | — |
| langfuse | Langfuse v2 — LLM observability UI | 3100 (Web) |

---

## Running the project

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

## Environment variables

| Variable | Required | Service | Description |
|---|---|---|---|
| BOT_TOKEN | yes | pm-bot | Telegram bot token |
| CLAUDE_API_KEY | yes | pm-bot, KE, pipeline | Claude API key |
| VAULT_PATH | yes | all | Path to the Obsidian vault |
| TRANSCRIPTS_INBOX | yes | pm-bot | Folder for incoming transcripts |
| ALLOWED_CHAT_ID | yes | pm-bot | Owner chat ID (empty = first-run mode) |
| PIPELINE_API_URL | yes | pm-bot | idea-pipeline API URL |
| JIRA_URL | yes | KE | Jira server URL |
| JIRA_TOKEN | yes | KE | Personal Access Token |
| OLLAMA_URL | no | pm-bot, KE | Ollama server URL |
| OLLAMA_MODEL | no | pm-bot, KE | Ollama model (default: qwen3.5:latest) |
| OPENROUTER_API_KEY | no | pm-bot, KE | OpenRouter API key for transcriptions |
| YANDEX_CALENDAR_URL | no | pm-bot | Yandex Calendar CalDAV server URL |
| YANDEX_CALENDAR_USERNAME | no | pm-bot | Yandex Calendar login |
| YANDEX_CALENDAR_PASSWORD | no | pm-bot | Yandex Calendar app password |
| STT_ENABLED | no | pm-bot | Enable STT/Whisper (default: 1) |

Full variable list — in index.md.

---

## Performance

In-memory TTL cache (30s) in vault_cache.py (`_VaultCache`):

| Endpoint | Before optimization | After (cached) |
|---|---|---|
| /system/status | 4882 ms | 4 ms |
| /domains | 4891 ms | 7 ms |
| /tasks | 1364 ms | 34 ms |
| /overview/queue | 912 ms | 4 ms |

Warm cache on server startup — the first user request is already served from cache. Invalidation happens on any write operation.

---

## Vault Health

A system for assessing the quality and completeness of the knowledge vault. Endpoint: `GET /api/v1/vault/health`.

### Formula

```
score = max(0, min(100, 100 - Σ(count × weight) - coverage_penalty))
```

Grades:
- **healthy** (≥80) — the vault is in good shape
- **warning** (50–79) — there are issues requiring attention
- **critical** (<50) — serious structural or completeness problems

### Metrics

| Metric | Weight | What it measures | Logic |
|---|---|---|---|
| `broken_links` | 3 | Broken `[[wikilinks]]` in wiki/ | Scans the body (not frontmatter) of all wiki/*.md files. Resolves links at 3 levels: exact name → suffix match → stem match. Ignores: @mentions, `{{}}` templates, URLs, attachments, people's names (2-3 capitalized words). Resolves relative paths (`../`). The file index covers wiki/ and raw/ |
| `orphan_pages` | 5 | Unprocessed raw files | Checks `raw/inbound/daily-logs/` and `raw/inbound/meeting-notes/`. Extracts the date (YYYY-MM-DD or YYYY.MM.DD) from the raw file name and looks for a wiki counterpart: daily-logs → `wiki/daily-logs/`, meeting-notes → `wiki/meetings/` + `wiki/daily-logs/` (daily standups are transformed into daily-logs). Other types are covered by other metrics |
| `dead_ends` | 1 | Artifacts without outgoing links | Files in `wiki/domains/*/ideas,tasks,epics,prds,bugs,userstories/` without a single `[[wikilink]]` in the body. Excludes service files (index.md, log.md) and files with `jira_key` |
| `stale_drafts` | 1 | Stale drafts | Ideas with the "New" status that haven't been updated for >30 days |
| `unsorted_misc` | 0.5 | Unused misc files | Files in `raw/inbound/misc/` whose stem/name is not mentioned in any `[[wikilink]]` in wiki/. Referenced files are not penalized |
| `ingest_backlog` | 0.2 | Queue of unprocessed raw items | Ideas: match by `id:` from raw and wiki frontmatter (fallback to stem). Tasks: match by stem |
| `description_coverage` | — | Description completeness | Share of artifacts with ≥2 sentences in the body. Penalty: <50% → 10, <70% → 5, ≥70% → 0 |

### Distribution of checks by raw/ type

| raw/inbound/ type | Metric | Matching strategy |
|---|---|---|
| `ideas/` | `ingest_backlog` | Match by `id:` from frontmatter (fallback: stem) against wiki/domains/*/ideas/ |
| `tasks/` | `ingest_backlog` | Match by stem against wiki/domains/*/tasks/ |
| `daily-logs/` | `orphan_pages` | Date from file name → wiki/daily-logs/ |
| `meeting-notes/` | `orphan_pages` | Date from file name → wiki/meetings/ + wiki/daily-logs/ |
| `misc/` | `unsorted_misc` | Stem/name in [[wikilinks]] in wiki/ |
| `clippings/` | — | Reference material, transformation is not expected |

### "Processed" criterion (Definition of Done for ingest)

A raw file is considered processed if the condition for its type is met:

| raw/inbound/ type | Considered processed when |
|---|---|
| `ideas/` | A file with the same `id:` from frontmatter exists in `wiki/domains/*/ideas/` |
| `tasks/` | A file with the same stem exists in `wiki/domains/*/tasks/` |
| `daily-logs/` | A file with the same date exists in `wiki/daily-logs/` |
| `meeting-notes/` | A file with the same date exists in `wiki/meetings/` or `wiki/daily-logs/` |
| `misc/` | The stem or file name is mentioned in a `[[wikilink]]` of at least one wiki file |
| `clippings/` | No processing required (reference material) |

### Trends

The API returns `trend_7d` and `trend_30d` — score history over 7 and 30 days. History is stored in `.health-history.json` at the vault root (TTL 90 days).

### Pipeline metrics (BL-123)

On top of the (penalty-based) health score — informational metrics on pipeline processing efficiency. They do not affect the score.

| Metric | Type | Description |
|---|---|---|
| `ingest_ratio` | float 0-100 | % of processed raw files (processed / raw_total × 100) |
| `avg_lag_hours` | float \| null | Average raw→wiki time in hours (based on matched pairs' mtime) |
| `raw_total` | int | Total .md files in raw/inbound/ideas/ + raw/inbound/tasks/ |
| `raw_counts` | dict | Breakdown: `{"ideas": N, "tasks": M}` |
| `matched_pairs` | int | Number of raw files for which a wiki copy was found |

Displayed on overview.html in the Pipeline section under the penalty categories. Trends (trend_7d, trend_30d) — text arrows ↑↓→.

---

## Project statistics

- 117 implemented features
- 36 bugs fixed
- 68 ideas in the backlog
- 221 backlog items in total

Development has been ongoing since 07.05.2026. Current versions: pm-bot 1.30.0, knowledge-engine 1.25.0, idea-pipeline 1.3.0, web-ui 1.33.0, shared 0.7.5.

---

## Relationship to the knowledge vault

PM Assistant is a software implementation of the rules described in the CLAUDE.md of the `08 project hotels claude` vault. The knowledge vault defines:

- The structure of raw/ and wiki/
- Ingest rules (processing of raw files)
- Domain detection (determining the domain by keywords)
- Indexing and linting rules
- Jira integration

PM Assistant turns these rules into working services: a watchdog instead of manual /ingest, cron instead of manual /rebuild-index, an API instead of manually reading index.md, a Web UI instead of navigating the file system.

## Vault file naming formats

### raw/ — source files

| Type | Format | Example |
|---|---|---|
| Ideas | `IDEA-{NNNN}-{YYYY-MM-DD}_{slug}.md` | `IDEA-0025-2026-06-10_монолит-2.5к.md` |
| Meeting minutes | `{YYYY-MM-DD} {HHmm} (MSK) {name}.txt` | `2026-05-06 1237 (MSK) SearchOffersByTiles.txt` |
| Daily logs | `{YYYY-MM-DD} {HHmm} (MSK) {name}.txt` | `2026-05-04 0959 (MSK) R6 Daily.txt` |

### wiki/ — processed artifacts

| Type | Format | Example |
|---|---|---|
| Daily summary | `{YYYY.MM.DD}-{NNN}-Daily-summary.md` | `2026.06.09-142-Daily-summary.md` |
| Meetings | `{YYYY-MM-DD}-{HHmm}-{slug}.md` | `2026-05-06-1237-searchoffersbytiles-логика.md` |
| Ideas | `IDEA-{NNNN}-{YYYY-MM-DD}_{slug}.md` | `IDEA-0025-2026-06-10_монолит-2.5к.md` |
| Tasks (Jira) | `{JIRA-KEY}.md` | `GO-223.md`, `TMPL-15257.md` |
| Bugs (Jira) | `{JIRA-KEY}.md` | `AN-12675.md` |
| Epics | `{JIRA-KEY}.md` or `E-{NN}-{slug}.md` | `E-12-унификация-rules.md` |
| Knowledge | `knowledge-{slug}.md` or `K-{DOMAIN}-{NNNN}.md` | `K-SEARCH-ENGINE-0004.md` |
| Concepts | `C-{NNNN}-{slug}.md` | `C-0003-process-idea-workflow-v1.0.md` |
| Projects | `{slug}.md` | `r6.md`, `r7.md` |
| Daily development report | `{YYYY.MM.DD}-Daily_Dev_Report.md` | `2026.06.09-Daily_Dev_Report.md` |
| Weekly report | `{YYYY-MM-DD}-week-{NN}.md` | `2026-06-08-week-24.md` |
| Competitor analysis | `{YYYY-MM-DD}-feature-analysis-week{NN}-{NN}.md` | `2026-06-07-feature-analysis-week22-23.md` |
| Synthesis | `synthesis-{YYYY-MM-DD}.md` | `synthesis-2026-05-21.md` |
| Competitors (pages) | `{slug}.md` | `airbnb.md`, `booking-com.md` |

> ⚠️ The formats under `wiki/reports/` are inconsistent — `YYYY-MM-DD-*`, `YYYY.MM.DD-*` and plain `{slug}.md` all occur. There is no single standard for reports.



## pm_assistant — Regular tasks

### Configured automatic runs

#### 1. Nightly raw queue processing (vault-ingest-queue)

| Parameter | Value |
|---|---|
| Schedule | Daily at 02:00 MSK |
| Executor | Headless Claude Code (Windows Task Scheduler) |
| Model | `claude-sonnet-4-6` (pinned via the `--model` flag) |
| Script | `pm_assistant/jobs/vault-ingest-queue/` |

Processes unprocessed raw files in batches of 10–15 (starting with the newest):
- `raw/inbound/meeting-notes/`
- `raw/inbound/clippings/`
- `raw/inbound/misc/`
- `raw/inbound/ideas/`

Files from `raw/competitors/` — only via the `/compile-competitor-report` command.

Processing criterion: DoD §6a — an artifact pointing back to the raw file via `source:` must exist in the wiki.

> ⚠️ The `vault-ingest-queue` Cowork task is disabled (no model control). Only the headless job is active.

---

#### 2. Morning task digest (morning-digest)

| Parameter | Value |
|---|---|
| Schedule | Mon–Fri at 08:31 MSK |
| Executor | Cowork scheduled task |
| Task ID | `morning-digest` |

Generates a digest of the product backlog and personal ToDos for the current day.

---

#### 3. Daily development status (daily-dev-status-report)

| Parameter | Value |
|---|---|
| Schedule | Daily at 18:00 MSK |
| Executor | Cowork scheduled task |
| Task ID | `daily-dev-status-report` |

Final development status for active tasks.

---

#### 4. Weekly development results report *(planned)*

| Parameter | Value |
|---|---|
| Schedule | Weekly (Friday) |
| Executor | Cowork scheduled task |
| Task ID | weekly-pm-report |

Aggregated weekly report: closed tasks, blockers, epic progress.

---

#### 5. Market and competitor analysis (competitor-analysis)

| Parameter | Value |
|---|---|
| Schedule | Every 2 weeks |
| Executor | Cowork scheduled task |
| Task ID | `competitor-analysis` |

Collects and analyzes competitor data from `raw/competitors/`. Generates a report in `wiki/domains/search-engine/reports/competitors/`.
