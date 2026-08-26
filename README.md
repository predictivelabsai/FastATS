# FastATS

FastATS is an open-source, recruiter-first applicant tracking system built with
Python, FastHTML, HTMX, SQLite/PostgreSQL, and xAI Grok.

The default development database is SQLite. Set `FASTATS_DATABASE_URL` and
`FASTATS_DB_SCHEMA=fast_ats` to run the same application against PostgreSQL.

## Quick start

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.sample .env
.venv/bin/python seed.py
.venv/bin/python web_app.py
```

Open <http://localhost:5020> and sign in with
`admin@fastats.example` / `FastATS2026$`.

Run the background queue in a second terminal:

```bash
.venv/bin/python worker.py
```

## Safety model

AI screening only extracts evidence and records scores, explanations, gaps, and
a recommendation. It cannot reject, advance, offer, or otherwise change an
application. Those state transitions remain explicit human actions.

