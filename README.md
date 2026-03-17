# Atlas - Local RAG System for Enterprise Documents

Atlas is a fully **on-premises** Retrieval-Augmented Generation (RAG) system designed for enterprise internal documents. It lets employees ask natural-language questions about company documents and receive context-enriched answers powered by locally-running large language models - without any data leaving the corporate network.

---

## Key Features

| Feature | Description |
|---|---|
| **100% Local** | All LLM inference and embeddings run via llama.cpp - no cloud calls |
| **Hybrid Search** | Combines pgvector cosine similarity with PostgreSQL full-text search |
| **Query Enrichment** | Automatically expands queries with collection context before retrieval |
| **Thinking Mode** | Optional chain-of-thought reasoning with visible thinking output |
| **Free Chat Mode** | Switch between RAG mode and direct conversation with the model |
| **Streaming Responses** | Answers stream to the browser in real time via Server-Sent Events (SSE) |
| **Permission System** | Users -> Groups -> Collections multi-level access control |
| **Docker Management** | Admin panel for managing containers, images, and volumes |
| **Multi-format OCR** | PDF, DOCX, XLSX, PPTX, TXT, CSV, HTML, XML, JSON - with OCR for scanned PDFs |
| **Conversation History** | Every conversation is persisted and resumable |
| **Admin Panel** | Full in-app management of users, groups, collections, and Docker |
| **Containerized** | One-command startup with Docker Compose |

---

## Architecture

```
Browser (React 18 + TypeScript)
    |
    v  (port 3000)
Nginx Reverse Proxy
    |
    v  (/api -> backend:8000)
FastAPI Backend (port 8000)
    |
    +--- PostgreSQL 16 + pgvector (port 5432)
    +--- llama.cpp LLM Server (port 8080)
    +--- llama.cpp Embedding Server (port 8081)
    +--- Docker Socket (container management)
```

---

## Quick Start

```bash
# 1. Clone and configure
git clone <repository-url> Atlas
cd Atlas
cp .env.example .env
nano .env  # Set DB_PASSWORD and AUTH_SECRET_KEY

# 2. Place models in ../models/
#    - Qwen3.5-35B-A3B-UD-IQ3_S.gguf (LLM)
#    - pplx-embed-context-v1-0.6b-q8_0.gguf (Embedding)

# 3. Start all services
docker compose up -d --build
```

Access at: http://localhost:3000 (default login: admin/admin)

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `DB_PASSWORD` | Yes | PostgreSQL password |
| `AUTH_SECRET_KEY` | Yes | JWT secret key (`openssl rand -hex 32`) |
| `ADMIN_DEFAULT_PASSWORD` | No | Initial admin password (default: admin) |

---

## Docker Services

| Service | Container | Port | Description |
|---|---|---|---|
| PostgreSQL + pgvector | `atlas-postgres` | 5432 | Vector database |
| llama.cpp LLM | `atlas-llama-cpp` | 8080 | Chat completion API |
| llama.cpp Embedding | `atlas-llama-cpp-embed` | 8081 | Embedding API |
| FastAPI Backend | `atlas-backend` | 8000 | API server |
| React Frontend + Nginx | `atlas-frontend` | 3000 | Web UI |

### Volume Layout

```
../postgres_data/  -> PostgreSQL data
../models/         -> GGUF model files (shared with llama.cpp containers)
```

---

## Configuration

All settings are in `config.yaml`. Changes require a backend restart.

### LLM (llama.cpp)

```yaml
llm:
  base_url: "http://llama-cpp:8080"
  model: "Qwen3.5-35B-A3B-UD-IQ3_S.gguf"
  temperature: 0.1
  max_tokens: 4096
  system_prompt: "..."           # Used for RAG answers
  enrichment_system_prompt: "..."  # Used for query enrichment
  free_chat_system_prompt: "..."   # Used for free chat mode
```

### Embedding (llama.cpp)

```yaml
embedding:
  base_url: "http://llama-cpp-embed:8081"
  model: "pplx-embed-context-v1-0.6b-q8_0.gguf"
  batch_size: 32
```

---

## Features Guide

### RAG vs Free Chat Mode

Toggle between modes in the chat sidebar:
- **RAG Mode**: Searches selected collections and generates answers with document context
- **Free Chat Mode**: Direct conversation with the LLM without document retrieval

### Thinking Mode

Enable the "Thinking" checkbox below the send button to activate chain-of-thought reasoning. The model's internal reasoning is shown in a dedicated tab below each response.

### Docker Management

Admins can manage Docker resources from the "Docker & System" tab in the admin panel:
- **Containers**: View status, restart selected containers
- **Images**: View tags and sizes, rebuild/pull selected images
- **Volumes**: View mountpoints, delete selected volumes

All actions support bulk selection.

### Query Enrichment

Every query passes through the enrichment pipeline. The LLM uses collection context and global context to expand queries with relevant domain-specific terms before retrieval.

---

## Permissions Model

```
User -> belongs to -> Group(s) -> has access to -> Collection(s) -> contains -> Documents
```

- Users can belong to multiple groups
- Groups can have read or read-write access to collections
- All queries are scoped to accessible collections
- Admins bypass access checks

---

## Development

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

---

## License

GNU General Public License v3.0 - see [LICENSE](LICENSE).
