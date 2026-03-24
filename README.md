# Atlas - Local RAG System for Enterprise Documents

Atlas is a fully **on-premises** Retrieval-Augmented Generation (RAG) system for enterprise internal documents. Employees can ask natural-language questions about company documents and receive context-enriched answers powered by locally-running LLMs via vLLM with GPU acceleration - no data leaves the corporate network.

---

## Key Features

| Feature | Description |
|---|---|
| **100% Local** | All LLM and embedding inference runs via vLLM with CUDA GPU acceleration - no cloud calls |
| **Docling API** | Dedicated ML-powered document parsing container with layout analysis, table structure recognition, and HybridChunker |
| **Query Enrichment** | Automatically expands queries with collection/global context before retrieval (toggleable) |
| **Dual Thinking Modes** | Separate thinking toggles for RAG answers and query enrichment, each with optimized sampling |
| **Hybrid Search** | Combines pgvector cosine similarity with PostgreSQL full-text search |
| **Free Chat Mode** | Switch between RAG mode and direct conversation with the model |
| **Streaming Responses** | Answers stream to the browser in real time via Server-Sent Events (SSE) |
| **Editable Prompts** | RAG, enrichment, and free chat system prompts editable live from the admin panel |
| **Permission System** | Users → Groups → Collections multi-level access control |
| **Docker Management** | Admin panel for managing Atlas containers, images, and volumes |
| **Multi-format Parsing** | PDF, DOCX, XLSX, PPTX, HTML, XML (via Docling), TXT, MD, CSV, JSON (local) |
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
    ├── vLLM LLM Server (port 8080) — Qwen3.5-35B-A3B, 65K context, GPU
    ├── vLLM Embedding Server (port 8081) — pplx-embed-context-4b, GPU
    ├── Docling API (port 8090) — ML document parsing & chunking
    └── Docker Socket (container management)

LLM Diagnostic Sidecar (tails colored log output)
```

---

## Quick Start

```bash
# 1. Clone the repository
git clone <repository-url> Atlas
cd Atlas

# 2. Start all services (first run downloads models from HuggingFace and builds images)
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
| `DB_PASSWORD` | `atlas` | PostgreSQL password |
| `AUTH_SECRET_KEY` | `change_me_in_production...` | JWT secret key |
| `ADMIN_DEFAULT_PASSWORD` | `admin` | Initial admin password |
| `LLM_MODEL` | `Qwen/Qwen3.5-35B-A3B` | HuggingFace model ID for chat/reasoning |
| `EMBED_MODEL` | `pplx-ai/pplx-embed-context-4b` | HuggingFace model ID for embeddings |
| `DOCLING_DO_OCR` | `true` | Enable OCR for scanned documents |
| `DOCLING_OCR_BACKEND` | `easyocr` | OCR backend: `easyocr` (GPU) or `tesseract` |
| `DOCLING_TABLE_MODE` | `fast` | Table recognition: `fast` or `accurate` |
| `DOCLING_DO_CODE_ENRICHMENT` | `true` | Detect and label code blocks |
| `DOCLING_ACCELERATOR_DEVICE` | `auto` | GPU device: `auto`, `cuda`, `mps`, `cpu` |

---

## Docker Services

| Service | Container | Port | Description |
|---|---|---|---|
| PostgreSQL + pgvector | `atlas-postgres` | 5432 | Vector database with 4096-dim embeddings |
| vLLM LLM | `atlas-vllm-llm` | 8080 | Chat completion API (65K context, GPU) |
| vLLM Embedding | `atlas-vllm-embed` | 8081 | Embedding API (GPU) |
| Docling API | `atlas-docling-api` | 8090 | ML document parsing & chunking |
| FastAPI Backend | `atlas-backend` | 8000 | API server |
| React Frontend + Nginx | `atlas-frontend` | 3000 | Web UI |
| LLM Diagnostic | `atlas-llm-diagnostic` | — | Tails colored diagnostic logs |

### Volume Layout

```
../postgres_data/  → PostgreSQL persistent data
../models/         → HuggingFace model cache (shared with vLLM containers)
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

### Document Processing

Documents are processed through two pipelines depending on format:

- **Docling API** (PDF, DOCX, XLSX, PPTX, HTML, XML, images): Dedicated container running Docling's ML pipeline:
  - **Layout analysis** (DocLayNet model) detects headings, tables, figures, lists, code blocks
  - **Table structure** (TableFormer) recognizes rows, columns, and cell spans
  - **OCR** (EasyOCR or Tesseract) extracts text from scanned documents and images
  - **Code enrichment** detects and labels code blocks
  - **HybridChunker** produces token-aware chunks aligned to the embedding model's tokenizer
  - **Contextualization** prepends heading/caption context to each chunk for better embedding quality
  - Document statistics (tables, figures, headings, code blocks) stored as metadata
- **Local** (TXT, MD, CSV, JSON): Simple text extraction with configurable chunking strategies

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
# Backend (requires Python 3.12+)
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (requires Node 18+)
cd frontend && npm install && npm run dev
```

---

## License

GNU General Public License v3.0 - see [LICENSE](LICENSE).
