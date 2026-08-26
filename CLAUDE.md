# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All commands use the project virtualenv at `.venv`.

```bash
# Install
.venv/bin/python -m pip install -r requirements.txt

# Seed synthetic data (idempotent — safe to re-run; creates the admin user + demo org)
.venv/bin/python seed.py

# Run the web app (http://localhost:5020)
.venv/bin/python web_app.py

# Run the background queue worker (separate terminal)
.venv/bin/python worker.py

# Tests
.venv/bin/python -m pytest
.venv/bin/python -m pytest tests/test_ats.py                       # single file
.venv/bin/python -m pytest tests/test_ats.py::test_public_application_is_idempotent  # single test
```

Default login after seeding: `admin@fastats.example` / `FastATS2026$`.

Postgres + app + worker together: `docker compose up`.

## Architecture

FastATS is a recruiter-first, AI-native ATS (plus lightweight CRM, scheduling, and analytics) built on **FastHTML + HTMX** (server-rendered HTML, no separate frontend) with **LangGraph** agents over **Grok**. Configuration is environment-backed via `config.py` (`settings` singleton), loaded from `.env` (copy from `.env.sample`).

The base install runs zero-config (SQLite + local disk + DB-backed queue + fake embeddings + console email) and the test suite needs no API key or services. Production backends (Postgres+pgvector, R2, hosted embeddings, SMTP/Postmark, real Grok) are opt-in via env — see "Pluggable backends" below.

### Request/service/data layering
- `web_app.py` — all FastHTML routes for both the authenticated recruiter surface and the **public careers surface** (`/careers/...`, no auth). Routes are thin: they resolve identity, then delegate to `ATSService`. UI is built from FastHTML component functions; there are no templates.
- `ats.py` (`ATSService`) — the domain layer. **Every method takes `organization_id` as its first argument** and every query filters on it — this is the tenancy boundary (see below). Contains job/pipeline/candidate/application logic, the `activity_events` audit log (`ATSService.log`), and job-queue enqueue.
- `database.py` (`Database`) — a thin portable data layer over **both SQLite and PostgreSQL**. The same code runs on either; `Database.from_env()` picks Postgres when `FASTATS_DATABASE_URL` is set, else SQLite. `?` placeholders are rewritten to `%s` for Postgres. Use `db.one/rows/scalar` for reads and `db.transaction()` for writes. Postgres uses a connection pool and a configurable schema (`FASTATS_DB_SCHEMA`, default `fast_ats`).

### Multi-tenancy (critical invariant)
There is no ORM and no automatic tenant scoping. Isolation is enforced *by hand* in every `ATSService` query via `organization_id`. When adding any query that touches tenant data, it **must** filter by `organization_id`, and service methods must accept and thread it through. `tests/test_ats.py::test_tenant_scoping_blocks_cross_org_reads_and_moves` guards this.

### Async AI screening pipeline
Screening is decoupled from the request cycle through a **database-backed queue** (`job_queue` table), not a broker.
1. A route calls `ats.enqueue_screening(...)`, inserting a `screen_application` job row.
2. `worker.py` polls the queue (`claim_one` uses `BEGIN IMMEDIATE` on SQLite / `FOR UPDATE SKIP LOCKED` on Postgres to claim exactly one job), then calls `screening.screen_application`.
3. `screening.py` calls xAI Grok (`langchain-xai`, structured output into the `ScreeningDecision` pydantic model) and writes a `screening_runs` row plus `screening_criteria` and an audit event.

**Safety model — do not violate:** No AI surface changes application state. Screening only records evidence/scores/recommendations; the recruiter assistant is read-only and surfaces mutations as proposals, not actions. State transitions (advance/reject/offer) are human-only, gated in `ATSService.move_application` by `HUMAN_ROLES`. Prompts, tools, and graph topology are all constrained to keep this true — preserve it when extending the agent layer.

Both `screen_application` and `worker.process_one` take an injectable `evaluator` callable (default `xai_evaluator`) — tests pass a fake evaluator, so **no API key is needed to run the test suite**. The real `xai_evaluator` raises `RuntimeError` when `XAI_API_KEY` is unset.

### Migrations (dialect-aware)
Numbered `.sql` files in `migrations/`, applied in version order by `Database.migrate()` and tracked in `schema_migrations`. Migrations run automatically on app/worker/seed startup. Naming controls which engine a file targets:
- `NNNN_name.sql` — portable, runs on **both** engines (must be valid SQLite *and* Postgres SQL).
- `NNNN_name.postgres.sql` / `NNNN_name.sqlite.sql` — runs **only** on the matching dialect (this is how pgvector/GIN DDL lives beside portable SQL). The version key is the `NNNN_name` prefix, so a version is applied once regardless of tag.

Add a new migration as the next-numbered file. `0002_platform.sql` holds the recruiter-depth/CRM/scheduling/agent tables; `0003_semantic.postgres.sql` adds pgvector columns; `0004_embeddings.sql` is the portable vector store.

### Pluggable backends (all injectable, all with offline defaults)
The system stays zero-config in dev and keyless in tests by putting every external dependency behind an interface with a fake/local default, selected in `config.py`:
- **Storage** (`storage.py`, `get_storage()`): `LocalStorage` (default) or `R2Storage` (boto3/S3). Same `put/read` + presigned-URL surface.
- **Embeddings** (`embeddings.py`, `get_embedder()`): `FakeEmbedder` (deterministic, offline, default) or `HostedEmbedder` (OpenAI-compatible).
- **Email** (`emailer.py`, `get_emailer()`): `ConsoleEmailer` (logs, default), `SMTPEmailer`, or `PostmarkEmailer`.
- **LLM + checkpointer** (`agents/models.py`): `build_chat_model()` (Grok, raises without a key) and `build_checkpointer()` (memory default; sqlite/postgres opt-in).

When adding an AI/IO feature, follow this seam: take the collaborator as an argument, default it to the configured real one, and inject a fake in tests.

### Chat-first UX (the primary surface)
The single chat agent **"Ada"** is the landing surface at `/` and drives the whole app (the dashboard moved to `/dashboard`). It's a 3-pane FastHTML page (`chat_page` in `web_app.py`): left = threads + workspace nav, center = streaming messages, right = an **artifact canvas**. Streaming uses **SSE**: `POST /chat/{thread_id}/message` returns `text/event-stream`; `agents/turn.py::stream_turn` maps LangGraph `astream_events` to `token` / `tool_start` / `artifact` / `done` events, and the inline `CHAT_JS` client renders them (tokens into the bubble, artifacts into the canvas). Tools emit an `__ARTIFACT__{json}` sentinel (`agents/recruiter.py::_artifact` / `extract_artifact`) rendered by `kind` (candidates, jobs, pipeline, candidate, draft, confirm, info). Threads/messages persist via `ChatService` (`chat.py`). Without a model key the chat still loads and returns a graceful fallback message.

**Recruiter agent** (`agents/recruiter.py`): a `create_react_agent` over read tools (search_candidates, get_candidate, list_jobs, summarize_pipeline, draft_outreach, queue_screening) plus **`propose_*` tools that never mutate state** — they return a `confirm` artifact whose form POSTs to the existing human-gated routes (e.g. `/applications/{id}/stage`). This is how the chat "drives everything" while keeping the safety model: the agent proposes, a human confirms.

### Editable skills (`skills_service.py`, `skills` table)
Recruiter-authored playbooks — name + instructions + trigger keywords + optional tool allow-list — stored per org and **composed into the agent's system prompt at runtime** (`SkillsService.compose_system_prompt`, called from `agents/recruiter.py::system_prompt_for`). Triggers matching the user's message mark a skill active. Full CRUD UI at `/skills`; built-in starter skills are seeded per org (lazily via `ensure_skills`, so existing orgs get them too). This is FastATS's own invention — the reference app (carhero) has no editable-skills feature; the injection seam is the agent's system prompt.

### Agent layer (`agents/`, LangGraph)
All AI runs through compiled LangGraph graphs; each accepts an injected model/evaluator so tests drive real graph topology with a scripted fake:
- `screening_graph.py` — `build_screening_graph(evaluator)`: prepare → score. `screening.py` loads context, runs the graph, and persists `screening_runs`/`screening_criteria`. **Still assistive-only: it never mutates application state.**
- `assistant.py` — `build_assistant_graph(model, ctx)`: a ReAct agent over **read-only, org-scoped** tools (`search_candidates`, `get_candidate_context`, `summarize_pipeline`). By design it cannot move stages, send email, or change state — mutations are surfaced as proposals for a human to confirm. This upholds the safety model.
- `content.py` — JD writer, outreach, feedback summary, interview questions (injected model → text).
- `runs.py` / `agent_runs` table — observability log for graph runs.

### Domain services beyond `ATSService`
- `crm.py` (`CRMService`) — talent pools, email sequences, enrollments, and message log. `process_enrollment` sends the current step and advances.
- `interviews.py` (`InterviewService`) — interviews, participants, scorecard templates, and structured scorecards.
- `analytics.py` (`AnalyticsService`) — funnel, source effectiveness, time-in-stage, overview.
- `ATSService` also gained notes, tags, custom fields, and bulk actions.

All follow the same tenancy rule: `organization_id` first, filtered in every query.

### Background job kinds
`job_queue` now carries three kinds, dispatched in `worker.process_one` (each handler takes an injected collaborator): `screen_application` (evaluator), `embed_entity` (embedder → `semantic.index_entity`), `send_sequence_step` (emailer → `CRMService.process_enrollment`). Enqueue via `ATSService.enqueue_screening/enqueue_embedding/enqueue_sequence_step`.

### Semantic search (`semantic.py`)
Vectors live in the portable `embeddings` table (source of truth). On Postgres, `index_entity` also writes the pgvector column and `search` uses `<=>` ANN ordering; on SQLite, similarity is computed in Python. `search_candidates` falls back to keyword `LIKE` when no vectors match, so it always returns something.

### Other boundaries
- `auth.py` — PBKDF2-SHA256 password hashing + `authenticate` (resolves user → first membership → org/role). Sessions store the resolved `identity` dict.
- `storage.py` (`LocalStorage`) — file-storage boundary for resume uploads; local disk is the dev backend.
- `documents.py` — resume text extraction (PDF via pdfplumber, DOCX via python-docx, txt/md), no local ML models.
- `seed.py` — idempotent demo data (org `northstar-labs`, admin user, jobs, candidates, one completed screening run).
