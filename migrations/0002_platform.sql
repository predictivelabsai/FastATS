-- Recruiter depth, CRM, scheduling, and agent observability.
-- Portable SQL: runs on both SQLite and PostgreSQL. Every tenant table carries
-- organization_id and is filtered on it by the service layer.

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    author_user_id TEXT REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, name)
);

CREATE TABLE IF NOT EXISTS taggables (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (tag_id, entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS custom_field_values (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    field_key TEXT NOT NULL,
    value TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, entity_type, entity_id, field_key)
);

CREATE TABLE IF NOT EXISTS scorecard_templates (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    questions_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, name)
);

CREATE TABLE IF NOT EXISTS interviews (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    stage_id TEXT REFERENCES pipeline_stages(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    scheduled_at TEXT,
    duration_minutes INTEGER,
    location TEXT,
    status TEXT NOT NULL,
    feedback_status TEXT NOT NULL,
    created_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interview_participants (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    interview_id TEXT NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    UNIQUE (interview_id, user_id)
);

CREATE TABLE IF NOT EXISTS scorecards (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    interview_id TEXT REFERENCES interviews(id) ON DELETE SET NULL,
    template_id TEXT REFERENCES scorecard_templates(id) ON DELETE SET NULL,
    interviewer_user_id TEXT REFERENCES users(id),
    overall REAL,
    recommendation TEXT,
    summary TEXT,
    status TEXT NOT NULL,
    submitted_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scorecard_answers (
    id TEXT PRIMARY KEY,
    scorecard_id TEXT NOT NULL REFERENCES scorecards(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    rating REAL,
    comment TEXT
);

CREATE TABLE IF NOT EXISTS talent_pools (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    created_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, name)
);

CREATE TABLE IF NOT EXISTS pool_memberships (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    pool_id TEXT NOT NULL REFERENCES talent_pools(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    added_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (pool_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS email_sequences (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_by TEXT REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (organization_id, name)
);

CREATE TABLE IF NOT EXISTS sequence_steps (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    sequence_id TEXT NOT NULL REFERENCES email_sequences(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    delay_hours INTEGER NOT NULL DEFAULT 0,
    UNIQUE (sequence_id, step_order)
);

CREATE TABLE IF NOT EXISTS sequence_enrollments (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    sequence_id TEXT NOT NULL REFERENCES email_sequences(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    current_step INTEGER NOT NULL DEFAULT 0,
    enrolled_by TEXT REFERENCES users(id),
    enrolled_at TEXT NOT NULL,
    next_run_at TEXT,
    UNIQUE (sequence_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    application_id TEXT REFERENCES applications(id) ON DELETE SET NULL,
    enrollment_id TEXT REFERENCES sequence_enrollments(id) ON DELETE SET NULL,
    direction TEXT NOT NULL,
    subject TEXT,
    body TEXT NOT NULL,
    provider TEXT,
    status TEXT NOT NULL,
    sent_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    graph TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    actor_user_id TEXT REFERENCES users(id),
    status TEXT NOT NULL,
    inputs_json TEXT,
    outputs_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_notes_entity ON notes(organization_id, entity_type, entity_id, created_at);
CREATE INDEX IF NOT EXISTS idx_taggables_entity ON taggables(organization_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_custom_entity ON custom_field_values(organization_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_interviews_app ON interviews(organization_id, application_id);
CREATE INDEX IF NOT EXISTS idx_scorecards_app ON scorecards(organization_id, application_id);
CREATE INDEX IF NOT EXISTS idx_pool_members ON pool_memberships(organization_id, pool_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_due ON sequence_enrollments(status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_messages_candidate ON messages(organization_id, candidate_id, created_at);
CREATE INDEX IF NOT EXISTS idx_agent_runs_entity ON agent_runs(organization_id, graph, entity_id, created_at);
