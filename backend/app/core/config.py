"""
Central configuration - loads config.yaml and provides all settings.

Environment variables in the YAML file (${VAR_NAME}) are resolved automatically.
"""

import os
import re
from pathlib import Path
from functools import lru_cache

import yaml
from pydantic import BaseModel


# =============================================================================
# Pydantic configuration models
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


class VectorConfig(BaseModel):
    dimensions: int = 4096
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
    base_url: str = "http://vllm-llm:8080"
    model: str = "Qwen/Qwen3.5-35B-A3B"
    max_tokens: int = 65536
    context_window: int = 65536
    timeout: int = 120
    system_prompt: str = ""
    enrichment_system_prompt: str = ""
    free_chat_system_prompt: str = ""
    sampling: SamplingConfig = SamplingConfig()
    thinking_sampling: ThinkingSamplingConfig = ThinkingSamplingConfig()


class EmbeddingConfig(BaseModel):
    base_url: str = "http://vllm-embed:8081"
    model: str = "pplx-ai/pplx-embed-context-4b"
    batch_size: int = 32
    max_retries: int = 3
    timeout: int = 60


class DoclingConfig(BaseModel):
    base_url: str = "http://docling-api:8090"
    max_tokens: int = 512
    merge_peers: bool = True
    tokenizer: str = ""


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
    similarity_threshold: float = 0.3
    query_enrichment: QueryEnrichmentConfig = QueryEnrichmentConfig()


class DocumentsConfig(BaseModel):
    supported_formats: list[str] = [".pdf", ".docx", ".txt"]
    max_file_size_mb: int = 100
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
    docling: DoclingConfig = DoclingConfig()
    chunking: ChunkingConfig = ChunkingConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    documents: DocumentsConfig = DocumentsConfig()
    auth: AuthConfig = AuthConfig()
    logging: LoggingConfig = LoggingConfig()


# =============================================================================
# YAML loading with environment variable resolution
# =============================================================================

def _resolve_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} with the environment variable value."""
    pattern = re.compile(r'\$\{(\w+)(?::-(.*?))?\}')

    def replacer(match):
        var_name = match.group(1)
        default = match.group(2)
        return os.environ.get(var_name, default if default is not None else "")

    return pattern.sub(replacer, value)


def _resolve_env_recursive(obj):
    """Recursively resolve environment variables in nested structures."""
    if isinstance(obj, str):
        return _resolve_env_vars(obj)
    elif isinstance(obj, dict):
        return {k: _resolve_env_recursive(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_resolve_env_recursive(item) for item in obj]
    return obj


def load_settings(config_path: str = "config.yaml") -> Settings:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    resolved = _resolve_env_recursive(raw)
    return Settings(**resolved)


@lru_cache()
def get_settings() -> Settings:
    """Cached Settings instance."""
    return load_settings()


# Global Settings instance
settings = get_settings()
