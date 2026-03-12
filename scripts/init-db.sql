-- =============================================================================
-- Atlas RAG System - Datenbank-Initialisierung
-- =============================================================================
-- Wird automatisch beim ersten Start des PostgreSQL-Containers ausgeführt.
-- =============================================================================

-- pgvector Extension aktivieren
CREATE EXTENSION IF NOT EXISTS vector;

-- pg_trgm für Volltext-Suche
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =============================================================================
-- BENUTZER & GRUPPEN
-- =============================================================================

-- Benutzer-Tabelle
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

-- Gruppen-Tabelle (z.B. Konstruktion, Vertrieb, Service)
CREATE TABLE groups (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Benutzer-Gruppen Zuordnung (M:N)
CREATE TABLE user_groups (
    user_id  INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    joined_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (user_id, group_id)
);

-- =============================================================================
-- COLLECTIONS & DOKUMENTE
-- =============================================================================

-- Collections (z.B. Normen, Anfragen, Datenblätter)
CREATE TABLE collections (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(200) UNIQUE NOT NULL,
    description TEXT,
    created_by  INTEGER REFERENCES users(id),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Gruppen-Zugriff auf Collections (M:N)
CREATE TABLE group_collection_access (
    group_id      INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    can_read      BOOLEAN DEFAULT TRUE,
    can_write     BOOLEAN DEFAULT FALSE,      -- Dokumente hinzufügen/entfernen
    granted_at    TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    granted_by    INTEGER REFERENCES users(id),
    PRIMARY KEY (group_id, collection_id)
);

-- Dokumente
CREATE TABLE documents (
    id              SERIAL PRIMARY KEY,
    collection_id   INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    filename        VARCHAR(500) NOT NULL,
    original_name   VARCHAR(500) NOT NULL,
    file_path       TEXT NOT NULL,
    file_type       VARCHAR(20) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    -- Kontext-Informationen für Context-Enriched Embedding
    context_description TEXT,                  -- Manuelle Beschreibung des Dokumentinhalts
    glossary            JSONB DEFAULT '{}',    -- Fachbegriffe & Abkürzungen als JSON
    metadata            JSONB DEFAULT '{}',    -- Weitere Metadaten
    -- Status
    processing_status VARCHAR(20) DEFAULT 'pending',  -- pending, processing, completed, error
    processing_error  TEXT,
    chunk_count       INTEGER DEFAULT 0,
    -- Tracking
    uploaded_by     INTEGER REFERENCES users(id),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index für schnelle Suche nach Collection
CREATE INDEX idx_documents_collection ON documents(collection_id);
CREATE INDEX idx_documents_status ON documents(processing_status);

-- =============================================================================
-- CHUNKS & EMBEDDINGS
-- =============================================================================

-- Dokument-Chunks mit Embeddings
CREATE TABLE chunks (
    id              SERIAL PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,          -- Position im Dokument
    content         TEXT NOT NULL,              -- Originaler Chunk-Text
    enriched_content TEXT,                      -- Kontextangereicherter Text (wird embedded)
    section_header  VARCHAR(500),              -- Abschnittsüberschrift
    page_number     INTEGER,                   -- Seitennummer (bei PDFs)
    token_count     INTEGER,                   -- Anzahl Tokens
    metadata        JSONB DEFAULT '{}',        -- Zusätzliche Metadaten
    embedding       vector(768),               -- Embedding-Vektor, Dimension muss vector.dimensions in config.yaml entsprechen
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

-- Vektor-Index für Ähnlichkeitssuche (IVFFlat)
CREATE INDEX idx_chunks_embedding ON chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Index für schnelle Dokumenten-Zuordnung
CREATE INDEX idx_chunks_document ON chunks(document_id);

-- GIN-Index für Volltext-Suche
CREATE INDEX idx_chunks_content_trgm ON chunks
    USING gin (content gin_trgm_ops);

-- =============================================================================
-- CHAT-VERLAUF
-- =============================================================================

-- Chat-Konversationen
CREATE TABLE conversations (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       VARCHAR(500),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Chat-Nachrichten
CREATE TABLE messages (
    id              SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL,       -- user, assistant
    content         TEXT NOT NULL,
    -- Welche Collections wurden bei dieser Frage berücksichtigt
    used_collections INTEGER[] DEFAULT '{}',
    -- Referenzen auf die verwendeten Chunks
    source_chunks   INTEGER[] DEFAULT '{}',
    -- Metadaten (z.B. Modell, Token-Verbrauch)
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_messages_conversation ON messages(conversation_id);

-- Welche Collections ein Benutzer aktuell ausgewählt hat
CREATE TABLE user_selected_collections (
    user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, collection_id)
);

-- =============================================================================
-- GLOSSAR (Global & pro Collection)
-- =============================================================================

-- Globales und Collection-spezifisches Glossar für Fachbegriffe
CREATE TABLE glossary_entries (
    id              SERIAL PRIMARY KEY,
    collection_id   INTEGER REFERENCES collections(id) ON DELETE CASCADE, -- NULL = global
    term            VARCHAR(200) NOT NULL,
    definition      TEXT NOT NULL,
    abbreviation    VARCHAR(50),               -- Falls es eine Abkürzung ist
    created_by      INTEGER REFERENCES users(id),
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(collection_id, term)
);

CREATE INDEX idx_glossary_collection ON glossary_entries(collection_id);

-- =============================================================================
-- HILFSFUNKTION: Automatisches updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger für automatisches updated_at
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
