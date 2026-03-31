"""
Central configuration - loads config.yaml and provides all settings.

How configuration works:
  1. All settings are defined in config.yaml (in the project root)
  2. This module reads that file and creates a Settings object
  3. The Settings object has flat attributes (e.g. settings.db_host, settings.llm_model)
  4. Environment variables in the YAML (like ${DB_PASSWORD}) are automatically resolved

Usage anywhere in the code:
    from app.core.config import settings
    print(settings.llm_base_url)      # "http://llama-llm:8080"
    print(settings.db_async_url)      # "postgresql+asyncpg://user:pass@host:5432/db"
    print(settings.llm_temperature)   # 0.7

All settings are loaded once at startup and cached.
Some settings (prompts) can be overridden at runtime via the admin UI.
"""

import os
import re
from pathlib import Path
from functools import lru_cache

import yaml


def _resolve_env_vars(value: str) -> str:
    """Replace ${VAR_NAME} or ${VAR_NAME:-default} with the environment variable value."""
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


class Settings:
    """Flat configuration object. All values are simple attributes."""

    def __init__(self, config: dict):
        # -- Server --
        server = config.get("server", {})
        self.server_host: str = server.get("host", "0.0.0.0")
        self.server_port: int = server.get("port", 8000)
        self.server_frontend_port: int = server.get("frontend_port", 3000)
        self.server_workers: int = server.get("workers", 4)
        self.server_cors_origins: list[str] = server.get("cors_origins", ["http://localhost:3000"])
        self.server_log_level: str = server.get("log_level", "info")

        # -- Database --
        db = config.get("database", {})
        self.db_host: str = db.get("host", "postgres")
        self.db_port: int = db.get("port", 5432)
        self.db_name: str = db.get("name", "atlas")
        self.db_user: str = db.get("user", "atlas_user")
        self.db_password: str = db.get("password", "")
        self.db_pool_size: int = db.get("pool_size", 20)
        self.db_max_overflow: int = db.get("max_overflow", 10)
        self.db_echo_sql: bool = db.get("echo_sql", False)

        # -- Vector --
        vec = config.get("vector", {})
        self.vector_dimensions: int = vec.get("dimensions", 1024)
        self.vector_index_type: str = vec.get("index_type", "hnsw")
        self.vector_distance_metric: str = vec.get("distance_metric", "cosine")
        self.vector_hnsw_m: int = vec.get("hnsw_m", 16)
        self.vector_hnsw_ef_construction: int = vec.get("hnsw_ef_construction", 64)
        self.vector_probes: int = vec.get("probes", 10)

        # -- LLM --
        llm = config.get("llm", {})
        self.llm_base_url: str = llm.get("base_url", "http://llama-llm:8080")
        self.llm_model: str = llm.get("model", "llm")
        self.llm_max_tokens: int = llm.get("max_tokens", 65536)
        self.llm_context_window: int = llm.get("context_window", 65536)
        self.llm_timeout: int = llm.get("timeout", 120)
        self.llm_system_prompt: str = llm.get("system_prompt", "")
        self.llm_enrichment_system_prompt: str = llm.get("enrichment_system_prompt", "")
        self.llm_free_chat_system_prompt: str = llm.get("free_chat_system_prompt", "")

        # LLM sampling (non-thinking mode)
        sampling = llm.get("sampling", {})
        self.llm_temperature: float = sampling.get("temperature", 0.7)
        self.llm_top_p: float = sampling.get("top_p", 0.8)
        self.llm_top_k: int = sampling.get("top_k", 20)
        self.llm_min_p: float = sampling.get("min_p", 0.0)
        self.llm_presence_penalty: float = sampling.get("presence_penalty", 1.5)
        self.llm_repetition_penalty: float = sampling.get("repetition_penalty", 1.0)

        # LLM sampling (thinking mode) - different temperature/top_p for reasoning
        thinking = llm.get("thinking_sampling", {})
        self.llm_thinking_temperature: float = thinking.get("temperature", 1.0)
        self.llm_thinking_top_p: float = thinking.get("top_p", 0.95)
        self.llm_thinking_top_k: int = thinking.get("top_k", 20)
        self.llm_thinking_min_p: float = thinking.get("min_p", 0.0)
        self.llm_thinking_presence_penalty: float = thinking.get("presence_penalty", 1.5)
        self.llm_thinking_repetition_penalty: float = thinking.get("repetition_penalty", 1.0)

        # -- Embedding --
        emb = config.get("embedding", {})
        self.embedding_base_url: str = emb.get("base_url", "http://llama-embed:8081")
        self.embedding_model: str = emb.get("model", "embed")
        self.embedding_batch_size: int = emb.get("batch_size", 32)
        self.embedding_max_retries: int = emb.get("max_retries", 3)
        self.embedding_timeout: int = emb.get("timeout", 60)

        # -- Docling Serve --
        doc = config.get("docling", {})
        self.docling_base_url: str = doc.get("base_url", "http://docling-serve:5001")
        self.docling_max_tokens: int = doc.get("max_tokens", 512)
        self.docling_merge_peers: bool = doc.get("merge_peers", True)
        self.docling_tokenizer: str = doc.get("tokenizer", "")

        # -- Chunking (local text files) --
        chunk = config.get("chunking", {})
        self.chunking_chunk_size: int = chunk.get("chunk_size", 512)
        self.chunking_chunk_overlap: int = chunk.get("chunk_overlap", 50)

        # -- Retrieval --
        ret = config.get("retrieval", {})
        self.retrieval_top_k: int = ret.get("top_k", 10)
        self.retrieval_rerank: bool = ret.get("rerank", True)
        self.retrieval_rerank_model: str = ret.get("rerank_model", "ms-marco-MiniLM-L-12-v2")
        self.retrieval_rerank_top_k: int = ret.get("rerank_top_k", 5)
        self.retrieval_similarity_threshold: float = ret.get("similarity_threshold", 0.3)

        # Query enrichment
        qe = ret.get("query_enrichment", {})
        self.enrichment_enabled: bool = qe.get("enabled", True)
        self.enrichment_prompt_template: str = qe.get(
            "prompt_template",
            "CONTEXT:\n{context}\n\nORIGINAL QUERY: {query}\n\nENRICHED QUERY:",
        )

        # -- Documents --
        docs = config.get("documents", {})
        self.documents_supported_formats: list[str] = docs.get("supported_formats", [".pdf", ".docx", ".txt"])
        self.documents_max_file_size_mb: int = docs.get("max_file_size_mb", 100)
        self.documents_temp_upload_dir: str = docs.get("temp_upload_dir", "/tmp/atlas_uploads")

        # -- Auth --
        auth = config.get("auth", {})
        self.auth_secret_key: str = auth.get("secret_key", "")
        self.auth_algorithm: str = auth.get("algorithm", "HS256")
        self.auth_access_token_expire_minutes: int = auth.get("access_token_expire_minutes", 480)
        self.auth_refresh_token_expire_days: int = auth.get("refresh_token_expire_days", 30)
        self.auth_min_password_length: int = auth.get("min_password_length", 5)
        self.auth_default_admin_username: str = auth.get("default_admin_username", "admin")
        self.auth_default_admin_password: str = auth.get("default_admin_password", "admin")

        # -- Logging --
        log = config.get("logging", {})
        self.logging_level: str = log.get("level", "INFO")
        self.logging_format: str = log.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        self.logging_file: str = log.get("file", "logs/atlas.log")
        self.logging_max_file_size_mb: int = log.get("max_file_size_mb", 50)
        self.logging_backup_count: int = log.get("backup_count", 5)
        self.logging_log_queries: bool = log.get("log_queries", False)

    @property
    def db_async_url(self) -> str:
        """PostgreSQL connection URL for asyncpg."""
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"


def load_settings(config_path: str = "config.yaml") -> Settings:
    """Load configuration from YAML file."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    resolved = _resolve_env_recursive(raw)
    return Settings(resolved)


@lru_cache()
def get_settings() -> Settings:
    """Cached Settings instance."""
    return load_settings()


# Global Settings instance
settings = get_settings()
