-- Synapse memory store schema (see CLAUDE.md section 3.1)

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto; -- gen_random_uuid()

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding VECTOR(1024) NOT NULL,
    memory_type TEXT NOT NULL CHECK (memory_type IN ('episodic', 'semantic', 'consolidated')),
    importance_score FLOAT NOT NULL CHECK (importance_score >= 0 AND importance_score <= 1),
    reasoning TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_recalled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    recall_count INT NOT NULL DEFAULT 0,
    salience FLOAT NOT NULL,
    source_memory_ids UUID[] DEFAULT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    pruned_at TIMESTAMPTZ DEFAULT NULL,
    pruned_reason TEXT DEFAULT NULL CHECK (
        pruned_reason IS NULL OR pruned_reason IN ('decayed_below_threshold', 'superseded', 'consolidated')
    )
);

CREATE INDEX IF NOT EXISTS memories_embedding_idx ON memories
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS memories_user_active_idx ON memories (user_id, is_active);
CREATE INDEX IF NOT EXISTS memories_user_type_idx ON memories (user_id, memory_type);

CREATE TABLE IF NOT EXISTS chat_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    recalled_memory_ids UUID[] DEFAULT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chat_turns_user_idx ON chat_turns (user_id, created_at);
