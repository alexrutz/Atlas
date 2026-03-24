# Atlas - Local RAG System for Enterprise Documents

Atlas is a fully **on-premises** Retrieval-Augmented Generation (RAG) system for enterprise internal documents. Employees can ask natural-language questions about company documents and receive context-enriched answers powered by locally-running LLMs via llama.cpp with GPU acceleration — no data leaves the corporate network.

---

## Key Features

| Feature | Description |
|---|---|
| **100% Local** | All LLM and embedding inference runs via llama.cpp with CUDA GPU acceleration — no cloud calls |
| **Docling API** | Dedicated ML-powered document parsing container with layout analysis, table structure recognition, and HybridChunker |
| **Query Enrichment** | Automatically expands queries with collection/global context before retrieval (toggleable) |
| **Dual Thinking Modes** | Separate thinking toggles for RAG answers and query enrichment, each with optimized sampling |
| **Hybrid Search** | Combines pgvector cosine similarity with PostgreSQL full-text search, followed by cross-encoder reranking |
| **Free Chat Mode** | Switch between RAG mode and direct conversation with the model |
| **Streaming Responses** | Answers stream to the browser in real time via Server-Sent Events (SSE) |
| **Editable Prompts** | RAG, enrichment, and free chat system prompts editable live from the admin panel |
| **Permission System** | Users → Groups → Collections multi-level access control |
| **Docker Management** | Admin panel for managing Atlas containers, images, and volumes |
| **Multi-format Parsing** | PDF, DOCX, XLSX, PPTX, HTML, XML, images (via Docling); TXT, MD, CSV, JSON (local) |
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
    ├── llama-server LLM (port 8080) — Qwen3.5-35B-A3B GGUF, 65K context, GPU
    ├── llama-server Embedding (port 8081) — pplx-embed-context-v1-0.6b, 1024-dim, CPU
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

# 2. Start all services (first run downloads the LLM model from HuggingFace and builds images)
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
| `HF_TOKEN` | _(empty)_ | Hugging Face token (required for gated models) |
| `LLM_N_GPU_LAYERS` | `-1` | GPU layers for LLM (`-1` = all layers on GPU) |
| `LLM_CTX_SIZE` | `65536` | LLM context window size in tokens |
| `EMBED_CTX_SIZE` | `512` | Embedding model context size |
| `DOCLING_DO_OCR` | `true` | Enable OCR for scanned documents and images |
| `DOCLING_OCR_BACKEND` | `auto` | OCR backend: `auto` (best available), `easyocr`, or `tesseract` |
| `DOCLING_OCR_LANG` | _(empty)_ | Comma-separated OCR language codes, e.g. `de,en` (empty = auto-detect) |
| `DOCLING_TABLE_MODE` | `fast` | Table recognition: `fast` (TableFormer-fast) or `accurate` |
| `DOCLING_DO_CODE_ENRICHMENT` | `true` | Detect and label code blocks |
| `DOCLING_DOCUMENT_TIMEOUT` | `300` | Per-document processing timeout in seconds |

---

## Docker Services

| Service | Container | Port | Description |
|---|---|---|---|
| PostgreSQL + pgvector | `atlas-postgres` | 5432 | Vector database with 1024-dim embeddings |
| llama-server LLM | `atlas-llama-llm` | 8080 | Chat completion API (65K context, CUDA GPU) |
| llama-server Embedding | `atlas-llama-embed` | 8081 | Embedding API (1024-dim, CPU) |
| Docling API | `atlas-docling-api` | 8090 | ML document parsing & chunking |
| FastAPI Backend | `atlas-backend` | 8000 | API server |
| React Frontend + Nginx | `atlas-frontend` | 3000 | Web UI |
| LLM Diagnostic | `atlas-llm-diagnostic` | — | Tails colored diagnostic logs |

### Volume Layout

```
../postgres_data/  → PostgreSQL persistent data
../models/         → Model cache shared between llama-llm and llama-embed containers
./logs/            → Application and LLM diagnostic logs
```

---

## Configuration

All settings live in `config.yaml` (single source of truth). Changes require a backend restart, except for **prompts** which can be edited live from the admin panel.

### LLM & Models

- **LLM**: `unsloth/Qwen3.5-35B-A3B-GGUF` (`Qwen3.5-35B-A3B-UD-IQ3_S.gguf`) — downloaded automatically on first start
- **Embedding**: `pplx-embed-context-v1-0.6b-q8_0.gguf` (perplexity-ai/pplx-embed-context-v1-0.6b) — must be placed in `../models/` before starting
- **Reranker**: `ms-marco-MiniLM-L-12-v2` cross-encoder (ONNX, runs in the backend)

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
3. **Cross-Encoder Reranking**: Top results reranked by `ms-marco-MiniLM-L-12-v2` before the final LLM call
4. **Dual-Query Answering**: The final LLM receives both the original question and enriched query, answering in the user's terminology while leveraging enriched search terms

### Chat Controls

Below the send button, three toggles control the RAG pipeline:

- **Thinking**: Enables chain-of-thought reasoning for the final answer (visible in debug panel)
- **Enrichment**: Enables/disables query enrichment (when off, original query is passed directly)
- **Enrich Thinking**: Enables thinking for the enrichment LLM call specifically

### RAG vs Free Chat Mode

Toggle in the collections sidebar:
- **RAG Mode**: Searches selected collections and generates answers with document context
- **Free Chat Mode**: Direct conversation with the LLM without document retrieval

### Admin Panel

Accessible to admin users with five tabs:

- **Users**: Create, edit, activate/deactivate users
- **Groups**: Create groups, manage membership
- **Collections**: Create collections, manage group access (read/write)
- **Prompts**: Edit RAG, enrichment, and free chat system prompts (changes apply immediately)
- **Docker & System**: View and manage Atlas containers, images, and volumes

### LLM Diagnostics

A sidecar container (`atlas-llm-diagnostic`) tails the diagnostic log with ANSI color output:
- **Cyan**: Query enrichment calls
- **Yellow**: Final RAG/free chat calls

View with:
```bash
docker logs -f atlas-llm-diagnostic
```

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

| Route | Description |
|---|---|
| `/chat` | Conversation interface with RAG/free chat mode toggle |
| `/context` | Global context editor used by the query enrichment step |
| `/documents` | Upload documents, manage collections, edit collection context |
| `/admin` | User, group, collection, prompt, and Docker management |

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

GNU General Public License v3.0 — see [LICENSE](LICENSE).
