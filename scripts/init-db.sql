-- =============================================================================
-- Atlas RAG System - Database Initialization
-- =============================================================================
-- Executed automatically on first PostgreSQL container start.
-- All tables live in the default "public" schema for simplicity.
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =============================================================================
-- Users, Groups, Memberships
-- =============================================================================

CREATE TABLE users (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(100) UNIQUE NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name       VARCHAR(255) NOT NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    is_admin        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE groups (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE user_groups (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (user_id, group_id)
);

-- =============================================================================
-- Collections, Documents, Access Control
-- =============================================================================

CREATE TABLE collections (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(200) UNIQUE NOT NULL,
    description TEXT,
    context_text TEXT,
    created_by  INTEGER REFERENCES users(id),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE group_collection_access (
    group_id      INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    can_read      BOOLEAN DEFAULT TRUE,
    can_write     BOOLEAN DEFAULT FALSE,
    granted_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    granted_by    INTEGER REFERENCES users(id),
    PRIMARY KEY (group_id, collection_id)
);

CREATE TABLE documents (
    id              SERIAL PRIMARY KEY,
    collection_id   INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    filename        VARCHAR(500) NOT NULL,
    original_name   VARCHAR(500) NOT NULL,
    file_path       TEXT NOT NULL,
    file_type       VARCHAR(20) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    metadata            JSONB DEFAULT '{}',
    processing_status VARCHAR(20) DEFAULT 'pending',
    processing_error  TEXT,
    chunk_count       INTEGER DEFAULT 0,
    uploaded_by     INTEGER REFERENCES users(id),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_documents_collection ON documents(collection_id);
CREATE INDEX idx_documents_status ON documents(processing_status);

-- =============================================================================
-- Chunks & Embeddings
-- =============================================================================

CREATE TABLE chunks (
    id              SERIAL PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    section_header  VARCHAR(500),
    page_number     INTEGER,
    token_count     INTEGER,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX idx_chunks_document ON chunks(document_id);

CREATE INDEX idx_chunks_content_trgm ON chunks
    USING gin (content gin_trgm_ops);

CREATE TABLE chunk_embeddings (
    id          SERIAL PRIMARY KEY,
    chunk_id    INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    model_name  VARCHAR(200) NOT NULL,
    embedding   vector(2560),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(chunk_id, model_name)
);

CREATE INDEX idx_chunk_embeddings_vector ON chunk_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_chunk_embeddings_chunk ON chunk_embeddings(chunk_id);
CREATE INDEX idx_chunk_embeddings_model ON chunk_embeddings(model_name);

-- =============================================================================
-- Conversations, Messages, User Selections
-- =============================================================================

CREATE TABLE conversations (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       VARCHAR(500),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL,
    content         TEXT NOT NULL,
    used_collections INTEGER[] DEFAULT '{}',
    source_chunks   INTEGER[] DEFAULT '{}',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id);

CREATE TABLE user_selected_collections (
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, collection_id)
);

-- =============================================================================
-- System Settings
-- =============================================================================

CREATE TABLE system_settings (
    key         VARCHAR(200) PRIMARY KEY,
    value       TEXT DEFAULT '',
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================================================
-- HELPER: Automatic updated_at trigger
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for automatic updated_at
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_groups_updated_at BEFORE UPDATE ON groups
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_collections_updated_at BEFORE UPDATE ON collections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_conversations_updated_at BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
