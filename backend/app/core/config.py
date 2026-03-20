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
    dimensions: int = 1024
    index_type: str = "ivfflat"
    distance_metric: str = "cosine"
    ivfflat_lists: int = 100
    hnsw_m: int = 16
    hnsw_ef_construction: int = 64
    probes: int = 10


class SamplingConfig(BaseModel):
    temperature: float = 0.7
    top_p: float = 0.8
    top_k: int = 20
    min_p: float = 0.0
    presence_penalty: float = 1.5
    repetition_penalty: float = 1.0


class ThinkingSamplingConfig(BaseModel):
    temperature: float = 1.0
    top_p: float = 0.95
    top_k: int = 20
    min_p: float = 0.0
    presence_penalty: float = 1.5
    repetition_penalty: float = 1.0


class LLMConfig(BaseModel):
    base_url: str = "http://llama-cpp:8080"
    model: str = "Qwen3.5-35B-A3B-UD-IQ3_S.gguf"
    max_tokens: int = 65536
    context_window: int = 65536
    timeout: int = 120
    system_prompt: str = ""
    enrichment_system_prompt: str = ""
    free_chat_system_prompt: str = ""
    sampling: SamplingConfig = SamplingConfig()
    thinking_sampling: ThinkingSamplingConfig = ThinkingSamplingConfig()


class EmbeddingConfig(BaseModel):
    base_url: str = "http://llama-cpp-embed:8081"
    model: str = "pplx-embed-context-v1-0.6b-q8_0.gguf"
    batch_size: int = 32
    max_retries: int = 3
    timeout: int = 60


class ChunkingConfig(BaseModel):
    strategy: str = "semantic"
    chunk_size: int = 512
    chunk_overlap: int = 50
    min_chunk_size: int = 100
    max_chunk_size: int = 1024
    separators: list[str] = ["\n\n", "\n", ". ", " "]


class QueryEnrichmentConfig(BaseModel):
    enabled: bool = True
    prompt_template: str = (
        "CONTEXT:\n{context}\n\n"
        "ORIGINAL QUERY: {query}\n\n"
        "ENRICHED QUERY:"
    )


class RetrievalConfig(BaseModel):
    top_k: int = 10
    rerank: bool = True
    rerank_model: str = "ms-marco-MiniLM-L-12-v2"
    rerank_top_k: int = 5
    similarity_threshold: float = 0.3  # Drop chunks below this cosine similarity
    hybrid_search: bool = False  # Deprecated, ignored — pure vector search is used
    hybrid_alpha: float = 0.7  # Deprecated, ignored
    query_enrichment: QueryEnrichmentConfig = QueryEnrichmentConfig()


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
