-- =============================================================================
-- Atlas RAG System - Database Initialization
-- =============================================================================
-- Executed automatically on first PostgreSQL container start.
-- Uses PostgreSQL schemas for logical separation of concerns.
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =============================================================================
-- SCHEMAS
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS iam;       -- Identity & Access Management
CREATE SCHEMA IF NOT EXISTS content;   -- Collections, documents
CREATE SCHEMA IF NOT EXISTS rag;       -- Chunks, embeddings, retrieval data
CREATE SCHEMA IF NOT EXISTS chat;      -- Conversations, messages
CREATE SCHEMA IF NOT EXISTS config;    -- System settings, glossary

-- =============================================================================
-- IAM SCHEMA - Users, Groups, Memberships
-- =============================================================================

CREATE TABLE iam.users (
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

CREATE TABLE iam.groups (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE iam.user_groups (
    user_id  INTEGER NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES iam.groups(id) ON DELETE CASCADE,
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (user_id, group_id)
);

-- =============================================================================
-- CONTENT SCHEMA - Collections, Documents, Access Control
-- =============================================================================

CREATE TABLE content.collections (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(200) UNIQUE NOT NULL,
    description TEXT,
    context_text TEXT,
    created_by  INTEGER REFERENCES iam.users(id),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE content.group_collection_access (
    group_id      INTEGER NOT NULL REFERENCES iam.groups(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES content.collections(id) ON DELETE CASCADE,
    can_read      BOOLEAN DEFAULT TRUE,
    can_write     BOOLEAN DEFAULT FALSE,
    granted_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    granted_by    INTEGER REFERENCES iam.users(id),
    PRIMARY KEY (group_id, collection_id)
);

CREATE TABLE content.documents (
    id              SERIAL PRIMARY KEY,
    collection_id   INTEGER NOT NULL REFERENCES content.collections(id) ON DELETE CASCADE,
    filename        VARCHAR(500) NOT NULL,
    original_name   VARCHAR(500) NOT NULL,
    file_path       TEXT NOT NULL,
    file_type       VARCHAR(20) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    context_description TEXT,
    glossary            JSONB DEFAULT '{}',
    metadata            JSONB DEFAULT '{}',
    processing_status VARCHAR(20) DEFAULT 'pending',
    processing_error  TEXT,
    chunk_count       INTEGER DEFAULT 0,
    uploaded_by     INTEGER REFERENCES iam.users(id),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_documents_collection ON content.documents(collection_id);
CREATE INDEX idx_documents_status ON content.documents(processing_status);

-- =============================================================================
-- RAG SCHEMA - Chunks & Embeddings (split into separate tables)
-- =============================================================================

-- Chunk content and metadata (text data, no vectors)
CREATE TABLE rag.chunks (
    id              SERIAL PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES content.documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    enriched_content TEXT,
    section_header  VARCHAR(500),
    page_number     INTEGER,
    token_count     INTEGER,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX idx_chunks_document ON rag.chunks(document_id);

-- Full-text search on chunk content
CREATE INDEX idx_chunks_content_trgm ON rag.chunks
    USING gin (content gin_trgm_ops);

-- Embeddings stored separately (allows re-embedding, multi-model support)
CREATE TABLE rag.chunk_embeddings (
    id          SERIAL PRIMARY KEY,
    chunk_id    INTEGER NOT NULL REFERENCES rag.chunks(id) ON DELETE CASCADE,
    model_name  VARCHAR(200) NOT NULL,
    embedding   vector(4096),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(chunk_id, model_name)
);

-- Vector index for similarity search (HNSW - supports >2000 dimensions)
CREATE INDEX idx_chunk_embeddings_vector ON rag.chunk_embeddings
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_chunk_embeddings_chunk ON rag.chunk_embeddings(chunk_id);
CREATE INDEX idx_chunk_embeddings_model ON rag.chunk_embeddings(model_name);

-- =============================================================================
-- CHAT SCHEMA - Conversations, Messages, User Selections
-- =============================================================================

CREATE TABLE chat.conversations (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
    title       VARCHAR(500),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE chat.messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES chat.conversations(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL,
    content         TEXT NOT NULL,
    used_collections INTEGER[] DEFAULT '{}',
    source_chunks   INTEGER[] DEFAULT '{}',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation ON chat.messages(conversation_id);

CREATE TABLE chat.user_selected_collections (
    user_id       INTEGER NOT NULL REFERENCES iam.users(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES content.collections(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, collection_id)
);

-- =============================================================================
-- CONFIG SCHEMA - System Settings, Glossary
-- =============================================================================

CREATE TABLE config.system_settings (
    key         VARCHAR(200) PRIMARY KEY,
    value       TEXT DEFAULT '',
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE config.glossary_entries (
    id              SERIAL PRIMARY KEY,
    collection_id   INTEGER REFERENCES content.collections(id) ON DELETE CASCADE,
    term            VARCHAR(200) NOT NULL,
    definition      TEXT NOT NULL,
    abbreviation    VARCHAR(50),
    created_by      INTEGER REFERENCES iam.users(id),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(collection_id, term)
);

CREATE INDEX idx_glossary_collection ON config.glossary_entries(collection_id);

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
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON iam.users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_groups_updated_at BEFORE UPDATE ON iam.groups
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_collections_updated_at BEFORE UPDATE ON content.collections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON content.documents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_conversations_updated_at BEFORE UPDATE ON chat.conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
