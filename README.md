# Atlas - Local RAG System for Enterprise Documents

Atlas is a fully **on-premises** Retrieval-Augmented Generation (RAG) system for enterprise internal documents. Employees can ask natural-language questions about company documents and receive context-enriched answers powered by locally-running LLMs via llama.cpp - no data leaves the corporate network.

---

## Key Features

| Feature | Description |
|---|---|
| **100% Local** | All LLM inference and embeddings run via llama.cpp with CUDA - no cloud calls |
| **Query Enrichment** | Automatically expands queries with collection/global context before retrieval (toggleable) |
| **Dual Thinking Modes** | Separate thinking toggles for RAG answers and query enrichment, each with optimized sampling |
| **Hybrid Search** | Combines pgvector cosine similarity with PostgreSQL full-text search |
| **Free Chat Mode** | Switch between RAG mode and direct conversation with the model |
| **Streaming Responses** | Answers stream to the browser in real time via Server-Sent Events (SSE) |
| **Editable Prompts** | RAG, enrichment, and free chat system prompts editable live from the admin panel |
| **Permission System** | Users → Groups → Collections multi-level access control |
| **Docker Management** | Admin panel for managing Atlas containers, images, and volumes |
| **Multi-format OCR** | PDF, DOCX, XLSX, PPTX, TXT, MD, CSV, HTML, XML, JSON - with Qianfan-OCR Layout-as-thought VLM for scanned PDFs (tesseract fallback) |
| **Conversation History** | Every conversation is persisted and resumable |
| **LLM Diagnostics** | Color-coded diagnostic log container shows all LLM inputs/outputs in real time |
| **Containerized** | One-command startup with Docker Compose |

---

## Architecture

```
Browser (React 18 + TypeScript + Tailwind)
    │
    ▼  (port 3000)
Nginx Reverse Proxy
    │
    ▼  (/api → backend:8000)
FastAPI Backend (port 8000)
    │
    ├── PostgreSQL 16 + pgvector (port 5432)
    ├── llama.cpp LLM Server (port 8080) — Qwen3.5-35B-A3B, 65K context
    ├── llama.cpp Embedding Server (port 8081) — Qianfan-OCR 4B, Layout-as-thought VLM
    └── Docker Socket (container management)

LLM Diagnostic Sidecar (tails colored log output)
```

---

## Quick Start

```bash
# 1. Clone the repository
git clone <repository-url> Atlas
cd Atlas

# 2. Place models in ../models/ (one level above the repo)
#    - Qwen3.5-35B-A3B-UD-IQ3_S.gguf       (LLM)
#    - Qianfan-OCR-Q8_0.gguf                  (Embedding + VLM OCR)
#    - mmproj-Qianfan-OCR-Q8_0.gguf           (Vision projector for Qianfan-OCR)

# 3. Start all services (first run builds frontend + backend images)
docker compose up -d --build
```

Access at: **http://localhost:3000** (default login: `admin` / `admin`)

The `.env` file ships with working defaults. For production, change `DB_PASSWORD` and `AUTH_SECRET_KEY`:

```bash
# Generate a secure secret key
openssl rand -hex 32
```

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DB_PASSWORD` | `atlas_default_password` | PostgreSQL password |
| `AUTH_SECRET_KEY` | `change_me_in_production...` | JWT secret key |
| `ADMIN_DEFAULT_PASSWORD` | `admin` | Initial admin password |

---

## Docker Services

| Service | Container | Port | Description |
|---|---|---|---|
| PostgreSQL + pgvector | `atlas-postgres` | 5432 | Vector database with 1024-dim embeddings |
| llama.cpp LLM | `atlas-llama-cpp` | 8080 | Chat completion API (65K context, CUDA) |
| llama.cpp Embedding | `atlas-llama-cpp-embed` | 8081 | Embedding + VLM OCR API (Qianfan-OCR, Layout-as-thought, CUDA) |
| FastAPI Backend | `atlas-backend` | 8000 | API server |
| React Frontend + Nginx | `atlas-frontend` | 3000 | Web UI |
| LLM Diagnostic | `atlas-llm-diagnostic` | — | Tails colored diagnostic logs |

### Volume Layout

```
../postgres_data/  → PostgreSQL persistent data
../models/         → GGUF model files (shared with llama.cpp containers)
./logs/            → Application and LLM diagnostic logs
```

---

## Configuration

All settings live in `config.yaml` (single source of truth). Changes require a backend restart, except for **prompts** which can be edited live from the admin panel.

### LLM Sampling Parameters

Two parameter sets are used depending on whether thinking mode is enabled:

| Parameter | Thinking | Non-Thinking |
|---|---|---|
| temperature | 1.0 | 0.7 |
| top_p | 0.95 | 0.8 |
| top_k | 20 | 20 |
| min_p | 0.0 | 0.0 |
| presence_penalty | 1.5 | 1.5 |
| repetition_penalty | 1.0 | 1.0 |

---

## Features Guide

### RAG Pipeline

1. **Query Enrichment** (toggleable): The LLM rephrases the user query using global + collection context to include domain-specific terms
2. **Hybrid Retrieval**: Vector similarity + full-text search across selected collections
3. **Dual-Query Answering**: The final LLM receives both the original question and enriched query, answering in the user's terminology while leveraging enriched search terms

### Chat Controls

Below the send button, three toggles control the RAG pipeline:

- **Thinking**: Enables chain-of-thought reasoning for the final answer (visible in debug panel)
- **Enrichment**: Enables/disables query enrichment (when off, original query is passed directly)
- **Enrich Thinking**: Enables thinking for the enrichment LLM specifically

### RAG vs Free Chat Mode

Toggle in the collections sidebar:
- **RAG Mode**: Searches selected collections and generates answers with document context
- **Free Chat Mode**: Direct conversation with the LLM without document retrieval

### Admin Panel

Accessible to admin users with five tabs:

- **Benutzer**: Create, edit, activate/deactivate users
- **Gruppen**: Create groups, manage membership
- **Collections**: Create collections, manage group access (read/write)
- **Prompts**: Edit RAG, enrichment, and free chat system prompts (changes apply immediately)
- **Docker & System**: View and manage Atlas containers, images, and volumes

### LLM Diagnostics

A sidecar container (`atlas-llm-diagnostic`) tails the diagnostic log with ANSI color output:
- **Cyan**: Query enrichment calls
- **Yellow**: Final RAG/free chat calls

View with: `docker logs -f atlas-llm-diagnostic`

---

## Permissions Model

```
User → belongs to → Group(s) → has access to → Collection(s) → contains → Documents
```

- Users can belong to multiple groups
- Groups can have read or read-write access to collections
- All queries are scoped to accessible collections
- Admins bypass access checks

---

## Pages

| Route | Page | Description |
|---|---|---|
| `/chat` | Chat | Conversation interface with RAG/free chat |
| `/context` | Kontext | Global context editor for query enrichment |
| `/documents` | Dokumente | Upload documents, manage collections, edit collection context |
| `/admin` | Admin | User, group, collection, prompt, and Docker management |

---

## Development

```bash
# Backend (requires Python 3.11+)
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (requires Node 18+)
cd frontend && npm install && npm run dev
```

---

## License

GNU General Public License v3.0 - see [LICENSE](LICENSE).
