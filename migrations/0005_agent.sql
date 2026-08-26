-- Chat-first agentic layer: persistent threads/messages and editable skills.
-- Portable SQL (SQLite + PostgreSQL). Every tenant row carries organization_id.

CREATE TABLE IF NOT EXISTS chat_threads (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL REFERENCES chat_threads(id) ON DELETE CASCADE,
    role TEXT NOT NULL,            -- user | assistant | tool | system
    content TEXT NOT NULL,
    tool_calls_json TEXT,          -- proposed/executed actions for the audit trail
    created_at TEXT NOT NULL
);

-- Editable skills: recruiter-authored playbooks the agent can load. A skill is
-- instructions (a mini system prompt) plus optional trigger keywords and an
-- allow-list of tools it may use. Enabled skills shape the agent at runtime.
CREATE TABLE IF NOT EXISTS skills (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    instructions TEXT NOT NULL,
    triggers TEXT,                 -- comma-separated keywords that surface the skill
    allowed_tools TEXT,            -- comma-separated tool names, empty = all
    enabled INTEGER NOT NULL DEFAULT 1,
    is_builtin INTEGER NOT NULL DEFAULT 0,
    created_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (organization_id, name)
);

CREATE INDEX IF NOT EXISTS idx_threads_org ON chat_threads(organization_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON chat_messages(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_skills_org ON skills(organization_id, enabled);
