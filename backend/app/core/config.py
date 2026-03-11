"""
Zentrale Konfiguration - lädt config.yaml und stellt alle Einstellungen bereit.

Umgebungsvariablen in der YAML-Datei (${VAR_NAME}) werden automatisch aufgelöst.
"""

import os
import re
from pathlib import Path
from functools import lru_cache

import yaml
from pydantic import BaseModel


# =============================================================================
# Pydantic Konfigurationsmodelle
# =============================================================================

class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    frontend_port: int = 3000
    workers: int = 4
    cors_origins: list[str] = ["http://localhost:3000"]
    log_level: str = "info"


class DatabaseConfig(BaseModel):
    host: str = "postgres"
    port: int = 5432
    name: str = "atlas"
    user: str = "atlas_user"
    password: str = ""
    pool_size: int = 20
    max_overflow: int = 10
    echo_sql: bool = False

    @property
    def async_url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        return f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class VectorConfig(BaseModel):
    dimensions: int = 768
    index_type: str = "ivfflat"
    distance_metric: str = "cosine"
    ivfflat_lists: int = 100
    hnsw_m: int = 16
    hnsw_ef_construction: int = 64
    probes: int = 10


class LLMConfig(BaseModel):
    provider: str = "ollama"
    base_url: str = "http://ollama:11434"
    model: str = "llama3.1:8b"
    temperature: float = 0.1
    top_p: float = 0.9
    top_k: int = 40
    max_tokens: int = 4096
    context_window: int = 8192
    repeat_penalty: float = 1.1
    num_gpu: int = 1
    num_threads: int = 8
    timeout: int = 120
    system_prompt: str = ""


class EmbeddingConfig(BaseModel):
    provider: str = "ollama"
    base_url: str = "http://ollama:11434"
    model: str = "nomic-embed-text"
    dimensions: int = 768
    batch_size: int = 32
    max_retries: int = 3
    timeout: int = 60


class ContextEnrichmentConfig(BaseModel):
    enabled: bool = True
    summarization_model: str = "llama3.1:8b"
    max_context_tokens: int = 512
    auto_glossary_extraction: bool = True
    include_section_headers: bool = True
    include_metadata_in_embedding: bool = True
    embedding_template: str = (
        "Dokument: {document_title}\n"
        "Sammlung: {collection_name}\n"
        "Abschnitt: {section_header}\n"
        "Kontext: {context_description}\n"
        "Glossar: {glossary}\n"
        "---\n"
        "{chunk_text}"
    )


class ChunkingConfig(BaseModel):
    strategy: str = "semantic"
    chunk_size: int = 512
    chunk_overlap: int = 50
    min_chunk_size: int = 100
    max_chunk_size: int = 1024
    separators: list[str] = ["\n\n", "\n", ". ", " "]


class RetrievalConfig(BaseModel):
    top_k: int = 10
    rerank: bool = True
    rerank_model: str = "cross-encoder"
    rerank_top_k: int = 5
    similarity_threshold: float = 0.3
    hybrid_search: bool = True
    hybrid_alpha: float = 0.7


class DocumentsConfig(BaseModel):
    supported_formats: list[str] = [".pdf", ".docx", ".txt"]
    max_file_size_mb: int = 100
    ocr_enabled: bool = True
    ocr_language: str = "deu+eng"
    temp_upload_dir: str = "/tmp/atlas_uploads"


class AuthConfig(BaseModel):
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 480
    refresh_token_expire_days: int = 30
    min_password_length: int = 5
    default_admin_username: str = "admin"
    default_admin_password: str = "admin"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: str = "logs/atlas.log"
    max_file_size_mb: int = 50
    backup_count: int = 5
    log_queries: bool = False


class Settings(BaseModel):
    server: ServerConfig = ServerConfig()
    database: DatabaseConfig = DatabaseConfig()
    vector: VectorConfig = VectorConfig()
    llm: LLMConfig = LLMConfig()
    embedding: EmbeddingConfig = EmbeddingConfig()
    context_enrichment: ContextEnrichmentConfig = ContextEnrichmentConfig()
    chunking: ChunkingConfig = ChunkingConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    documents: DocumentsConfig = DocumentsConfig()
    auth: AuthConfig = AuthConfig()
    logging: LoggingConfig = LoggingConfig()


# =============================================================================
# YAML laden mit Umgebungsvariablen-Auflösung
# =============================================================================

def _resolve_env_vars(value: str) -> str:
    """Ersetzt ${VAR_NAME} durch den Wert der Umgebungsvariable."""
    pattern = re.compile(r'\$\{(\w+)(?::-(.*?))?\}')

    def replacer(match):
        var_name = match.group(1)
        default = match.group(2)
        return os.environ.get(var_name, default if default is not None else "")

    return pattern.sub(replacer, value)


def _resolve_env_recursive(obj):
    """Rekursive Auflösung von Umgebungsvariablen in verschachtelten Strukturen."""
    if isinstance(obj, str):
        return _resolve_env_vars(obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env_recursive(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_recursive(item) for item in obj]
    return obj


def load_settings(config_path: str = "config.yaml") -> Settings:
    """Lädt die Konfiguration aus der YAML-Datei."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {config_path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    resolved = _resolve_env_recursive(raw)
    return Settings(**resolved)


@lru_cache()
def get_settings() -> Settings:
    """Cached Settings-Instanz."""
    return load_settings()


# Globale Settings-Instanz
settings = get_settings()
