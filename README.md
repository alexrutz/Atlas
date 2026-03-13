# Atlas — Local RAG System for Enterprise Documents

Atlas is a fully **on-premises** Retrieval-Augmented Generation (RAG) system designed for enterprise internal documents. It lets employees ask natural-language questions about company documents and receive context-enriched answers powered by locally-running large language models — without any data leaving the corporate network.

---

## Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Hardware Requirements](#hardware-requirements)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Quick Start (Automated)](#quick-start-automated)
  - [Manual Setup](#manual-setup)
  - [Verifying the Installation](#verifying-the-installation)
- [Configuration](#configuration)
  - [Environment Variables](#environment-variables)
  - [config.yaml Reference](#configyaml-reference)
- [Usage](#usage)
  - [First Login](#first-login)
  - [Uploading Documents](#uploading-documents)
  - [Chatting with Documents](#chatting-with-documents)
  - [Managing Users and Groups](#managing-users-and-groups)
  - [Managing Collections](#managing-collections)
- [API Reference](#api-reference)
  - [Authentication](#authentication)
  - [Users](#users)
  - [Groups](#groups)
  - [Collections](#collections)
  - [Documents](#documents)
  - [Chat & RAG](#chat--rag)
  - [Settings](#settings)
  - [Health](#health)
- [Project Structure](#project-structure)
- [RAG Pipeline Deep Dive](#rag-pipeline-deep-dive)
  - [Document Ingestion](#document-ingestion)
  - [Query Processing](#query-processing)
  - [Hybrid Search](#hybrid-search)
  - [Answer Generation](#answer-generation)
- [Permissions Model](#permissions-model)
- [Supported Document Formats](#supported-document-formats)
- [Docker Services](#docker-services)
- [Switching LLM Models](#switching-llm-models)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [License](#license)

---

## Overview

Atlas solves a common enterprise problem: critical knowledge is locked in PDFs, Word documents, spreadsheets, and other files scattered across file servers. Finding the right information is slow and error-prone.

Atlas ingests those documents, chunks and embeds them using a local embedding model, stores the vectors in PostgreSQL (via pgvector), and exposes a chat interface where users can ask questions in natural language. Text generation runs on-premises via native [llama.cpp](https://github.com/ggml-org/llama.cpp/tree/master/tools/server), and embeddings are served locally by [Ollama](https://ollama.com/), so sensitive company data never reaches external APIs.

---

## Key Features

| Feature | Description |
|---|---|
| **100% Local** | LLM inference runs via llama.cpp and embeddings via Ollama — no cloud calls |
| **Hybrid Search** | Combines pgvector cosine similarity with PostgreSQL full-text search |
| **Query Enrichment** | Automatically expands queries with collection context before retrieval |
| **Reranking** | Cross-encoder reranking narrows the initial top-10 hits to the best 5 |
| **Streaming Responses** | Answers stream to the browser in real time via Server-Sent Events (SSE) |
| **Permission System** | Users → Groups → Collections multi-level access control |
| **Multi-format OCR** | PDF, DOCX, XLSX, PPTX, TXT, CSV, HTML, XML, JSON — with OCR for scanned PDFs |
| **Conversation History** | Every conversation is persisted and resumable |
| **Admin Panel** | Full in-app management of users, groups, and document collections |
| **Containerized** | One-command startup with Docker Compose |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                        Browser                           │
│               React 18 + TypeScript SPA                  │
│         (Chat · Documents · Admin · Login)               │
└───────────────────────┬──────────────────────────────────┘
                        │ HTTP / SSE  (port 3000)
                        ▼
┌──────────────────────────────────────────────────────────┐
│                 Nginx Reverse Proxy                       │
│         SPA routing + /api → backend:8000                │
└───────────────────────┬──────────────────────────────────┘
                        │
                        ▼
┌──────────────────────────────────────────────────────────┐
│               FastAPI Backend  (port 8000)               │
│                                                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │  Auth       │  │  Documents  │  │  Chat / RAG     │  │
│  │  Users      │  │  Collections│  │  Conversations  │  │
│  │  Groups     │  │  Chunking   │  │  Streaming SSE  │  │
│  └─────────────┘  └─────────────┘  └─────────────────┘  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │             Service Layer                        │    │
│  │  DocumentProcessor · EmbeddingService           │    │
│  │  RetrievalService  · QueryEnrichmentService     │    │
│  │  LLMService        · RAGPipeline                │    │
│  └──────────────────────────────────────────────────┘    │
└──────┬────────────────────────┬────────────────────────--┘
       │                        │
       ▼                        ▼
┌─────────────────┐    ┌─────────────────────┐
│  PostgreSQL 16  │    │  llama.cpp (8080) +   │
│  + pgvector     │    │                     │
│                 │    │  nomic-embed-text    │
│  - users        │    │  llama3.1:8b         │
│  - groups       │    │  (or any model)      │
│  - collections  │    └─────────────────────┘
│  - documents    │
│  - chunks       │
│  - conversations│
│  - messages     │
└─────────────────┘
```

All four services run in Docker containers on a shared internal network (`atlas-network`). The database and Ollama model weights are persisted in named Docker volumes so they survive container restarts.

---

## Tech Stack

### Backend
| Component | Technology | Version |
|---|---|---|
| Language | Python | 3.12 |
| Web framework | FastAPI | 0.115.6 |
| ASGI server | Uvicorn | 0.34.0 |
| ORM | SQLAlchemy (async) | 2.0.36 |
| DB driver | asyncpg | 0.30.0 |
| Vector extension | pgvector | 0.3.6 |
| Auth | PyJWT + bcrypt | 2.10.1 / 4.2.1 |
| Config | PyYAML + Pydantic | 6.0.2 / 2.10.4 |
| PDF parsing | pypdf | latest |
| DOCX parsing | python-docx | latest |
| XLSX parsing | openpyxl | latest |
| HTML parsing | beautifulsoup4 | latest |
| OCR | pytesseract + pdf2image | latest |
| HTTP client | httpx + aiohttp | latest |
| Testing | pytest + pytest-asyncio | 8.3.4 / 0.25.0 |

### Frontend
| Component | Technology | Version |
|---|---|---|
| Language | TypeScript | ~5.6.3 |
| UI framework | React | 18.3.1 |
| Bundler | Vite | 6.0.3 |
| Routing | React Router | 6.28.0 |
| HTTP client | Axios | 1.7.9 |
| Data fetching | TanStack React Query | 5.62.0 |
| State management | Zustand | latest |
| Styling | Tailwind CSS | 3.4.16 |
| Icons | Lucide React | latest |
| Markdown | React Markdown | 9.0.1 |
| File upload | React Dropzone | 14.3.5 |

### Infrastructure
| Component | Technology |
|---|---|
| Database | PostgreSQL 16 + pgvector extension |
| LLM runtime | llama.cpp server |
| Web server / proxy | Nginx |
| Containerization | Docker + Docker Compose |

---

## Hardware Requirements

Because all AI inference runs locally, the hardware requirements are substantial.

| Component | Minimum | Recommended |
|---|---|---|
| RAM | 32 GB | 64 GB |
| GPU VRAM | 8 GB (llama3.1:8b) | 24 GB+ |
| Storage | 100 GB SSD | 500 GB+ NVMe SSD |
| CPU | 8 cores | 16+ cores |
| OS | Linux (Ubuntu 22.04+) | Linux with NVIDIA GPU |

> **GPU Note:** The default model (`llama3.1:8b`) requires a GPU with at least 8 GB of VRAM. CPU-only inference is possible but significantly slower (set `num_gpu: 0` in `config.yaml`). The Docker Compose file is pre-configured for NVIDIA GPUs via the NVIDIA Container Toolkit.

---

## Getting Started

### Prerequisites

Make sure the following are installed and running on your host machine:

- [Docker Engine](https://docs.docker.com/engine/install/) >= 24.0
- [Docker Compose](https://docs.docker.com/compose/install/) >= 2.20
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) (for GPU support)
- `git`, `openssl`, `curl`

Verify Docker and GPU access:

```bash
docker --version
docker compose version
docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi
```

### Quick Start (Automated)

```bash
# 1. Clone the repository
git clone <repository-url> Atlas
cd Atlas

# 2. Create your environment file
cp .env.example .env

# 3. Edit .env and set your secrets (see Environment Variables below)
#    At minimum, change DB_PASSWORD and AUTH_SECRET_KEY
nano .env

# 4. Run the automated setup script
chmod +x scripts/setup.sh
./scripts/setup.sh
```

The setup script will:
- Validate that Docker and required tools are available
- Start PostgreSQL and Ollama containers
- Download the required AI models (`nomic-embed-text` and `llama3.1:8b`)
- Build and start the backend and frontend containers
- Seed the database with the initial admin account

Once complete, access the application at:
- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8000
- **Interactive API Docs:** http://localhost:8000/docs

### Manual Setup

If you prefer to control each step manually:

```bash
# 1. Clone and configure
git clone <repository-url> Atlas
cd Atlas
cp .env.example .env
# Edit .env with your values

# 2. Start infrastructure services first
docker compose up -d postgres ollama llama-cpp

# 3. Wait for services to initialize
docker compose ps  # wait until postgres/ollama/llama-cpp are healthy

 # 4. Download embedding model and provide GGUF for llama.cpp
docker exec atlas-ollama ollama pull nomic-embed-text
mkdir -p models
# copy your GGUF model to models/llama-3.1-8b-instruct.gguf

# 5. Build and start the backend (it will auto-migrate the database)
docker compose up -d --build backend

# 6. Build and start the frontend
docker compose up -d --build frontend
```

To pull models in the background using the provided script:

```bash
chmod +x scripts/pull-models.sh
./scripts/pull-models.sh
```

### Verifying the Installation

```bash
# All four containers should show "Up" status
docker compose ps

# Backend health check
curl http://localhost:8000/api/health
# Expected: {"status": "healthy"}

# Check backend logs
docker compose logs backend --tail=50

# Check Ollama models are available
docker exec atlas-ollama ollama list
```

---

## Configuration

### Environment Variables

Copy `.env.example` to `.env` and fill in the required values before starting:

```bash
cp .env.example .env
```

| Variable | Required | Description | Example |
|---|---|---|---|
| `DB_PASSWORD` | **Yes** | Password for the PostgreSQL `atlas_user` account | `my$ecureP@ssw0rd` |
| `AUTH_SECRET_KEY` | **Yes** | Secret key used to sign JWT tokens. Generate with `openssl rand -hex 32` | `a3f9b2c1...` |
| `ADMIN_DEFAULT_PASSWORD` | No | Password for the `admin` account on first startup. Defaults to `admin` | `changeme123` |

> **Security:** Change `ADMIN_DEFAULT_PASSWORD` immediately after first login. `AUTH_SECRET_KEY` must be a cryptographically random value — never use the placeholder.

Generate a secure key:
```bash
openssl rand -hex 32
```

### config.yaml Reference

The central configuration file `config.yaml` controls every aspect of the system. Changes require a backend restart (`docker compose restart backend`).

#### Server

```yaml
server:
  host: "0.0.0.0"          # Listen on all interfaces
  port: 8000                # Backend API port
  frontend_port: 3000       # Frontend port
  workers: 4                # Number of Uvicorn worker processes
  cors_origins:             # Allowed CORS origins
    - "http://localhost:3000"
  log_level: "info"         # debug | info | warning | error | critical
```

#### Database

```yaml
database:
  host: "postgres"          # Docker service name (don't change for Docker setups)
  port: 5432
  name: "atlas"
  user: "atlas_user"
  password: "${DB_PASSWORD}" # Read from .env
  pool_size: 20             # Connection pool size
  max_overflow: 10          # Additional connections above pool_size
  echo_sql: false           # Log all SQL queries (development only)
```

#### Vector Index (pgvector)

```yaml
vector:
  dimensions: 1024          # Must match the embedding model's output size
  index_type: "ivfflat"     # ivfflat (faster build) or hnsw (faster query)
  distance_metric: "cosine" # cosine | l2 | inner_product
  ivfflat_lists: 100        # Number of IVFFlat partitions
  hnsw_m: 16                # HNSW graph connections per node
  hnsw_ef_construction: 64  # HNSW build-time search depth
  probes: 10                # Partitions to probe at query time (ivfflat)
```

> **Note:** If you change `dimensions`, you must also update `embedding.dimensions` to match and rebuild the embedding index (requires re-ingesting all documents).

#### LLM

```yaml
llm:
  provider: "llama_cpp"
  base_url: "http://llama-cpp:8080"
  model: "llama-3.1-8b-instruct"  # Must match the llama.cpp alias
  temperature: 0.1           # 0.0 = deterministic, 1.0 = creative
  top_p: 0.9
  top_k: 40
  max_tokens: 4096           # Maximum response length in tokens
  context_window: 8192       # Must match the model's context window
  repeat_penalty: 1.1
  num_gpu: 1                 # GPUs to use (0 for CPU-only)
  num_threads: 8             # CPU threads (relevant when num_gpu: 0)
  timeout: 120               # Request timeout in seconds
  system_prompt: |
    Du bist Atlas, ein KI-Assistent fuer interne Firmendokumente.
    ...
```

#### Embedding

```yaml
embedding:
  provider: "ollama"
  base_url: "http://ollama:11434"
  model: "nomic-embed-text"  # 1024-dimensional embeddings
  dimensions: 1024           # Must match vector.dimensions
  batch_size: 32             # Documents embedded per batch
  max_retries: 3
  timeout: 60
```

#### Chunking

```yaml
chunking:
  strategy: "semantic"       # fixed | sentence | semantic | recursive
  chunk_size: 512            # Target chunk size in tokens
  chunk_overlap: 50          # Token overlap between adjacent chunks
  min_chunk_size: 100
  max_chunk_size: 1024
  separators:                # Used by the "recursive" strategy
    - "\n\n"
    - "\n"
    - ". "
    - " "
```

| Strategy | Description |
|---|---|
| `fixed` | Hard-split every N tokens |
| `sentence` | Split on sentence boundaries |
| `semantic` | Group semantically similar sentences |
| `recursive` | Recursively split on the provided `separators` |

#### Retrieval

```yaml
retrieval:
  top_k: 10                  # Chunks retrieved before reranking
  rerank: true               # Enable cross-encoder reranking
  rerank_model: "cross-encoder"
  rerank_top_k: 5            # Chunks passed to the LLM after reranking
  similarity_threshold: 0.3  # Minimum cosine similarity (0.0-1.0)
  hybrid_search: true        # Combine vector search with full-text search
  hybrid_alpha: 0.7          # 1.0 = pure vector, 0.0 = pure full-text
  query_enrichment:
    enabled: true            # Expand queries with collection context
```

#### Documents

```yaml
documents:
  supported_formats:
    - ".pdf"
    - ".docx"
    - ".doc"
    - ".xlsx"
    - ".xls"
    - ".pptx"
    - ".txt"
    - ".md"
    - ".csv"
    - ".html"
    - ".xml"
    - ".json"
  max_file_size_mb: 100
  ocr_enabled: true          # OCR for scanned/image-based PDFs
  ocr_language: "deu+eng"    # Tesseract language codes
  temp_upload_dir: "/tmp/atlas_uploads"
```

#### Authentication

```yaml
auth:
  secret_key: "${AUTH_SECRET_KEY}"
  algorithm: "HS256"
  access_token_expire_minutes: 480   # 8 hours
  refresh_token_expire_days: 30
  min_password_length: 5
  default_admin_username: "admin"
  default_admin_password: "${ADMIN_DEFAULT_PASSWORD}"
```

#### Logging

```yaml
logging:
  level: "INFO"              # DEBUG | INFO | WARNING | ERROR | CRITICAL
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: "logs/atlas.log"
  max_file_size_mb: 50
  backup_count: 5
  log_queries: false         # Set to true only for debugging (privacy risk)
```

---

## Usage

### First Login

1. Open http://localhost:3000 in your browser.
2. Log in with username `admin` and the password you set in `ADMIN_DEFAULT_PASSWORD` (defaults to `admin`).
3. Navigate to the **Admin** panel (top-right menu) and **change the admin password immediately**.

### Uploading Documents

1. Create a **Collection** in the Admin panel (e.g., "Engineering Specs").
2. Navigate to **Documents** in the sidebar.
3. Select the collection from the dropdown.
4. Drag and drop files onto the upload zone, or click to browse.
5. Atlas will parse, chunk, and embed the documents in the background. A status indicator shows processing progress.
6. Once processing is complete, the documents are searchable.

### Chatting with Documents

1. Navigate to the **Chat** page.
2. Select one or more collections to search across (sidebar checkboxes).
3. Type your question in the input box and press Enter.
4. Atlas streams the answer back in real time, with cited source chunks below the response.
5. Your conversation is automatically saved and visible in the conversation history sidebar.

### Managing Users and Groups

All user management is available to admin accounts under **Admin > Users** and **Admin > Groups**.

- **Create a user:** Enter username, email, and initial password. Toggle the admin flag if needed.
- **Create a group:** Give it a name (e.g., "Engineering", "Sales").
- **Add users to a group:** Select the group and use the member management panel.
- **Grant groups access to collections:** In the Collections panel, assign read or write access per group.

### Managing Collections

Collections are logical buckets for documents. Each collection can have:
- A **name** and **description**
- A **context text** used to enrich queries before retrieval (e.g., "This collection contains engineering drawings and specifications for the product line XY")
- **Group access rules** (read-only or read-write per group)

---

## API Reference

The full interactive API documentation is available at:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

All endpoints (except `/api/auth/login` and `/api/health`) require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

### Authentication

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Authenticate with username/password. Returns access token and refresh token. |
| `POST` | `/api/auth/refresh` | Exchange a valid refresh token for a new access token. |
| `POST` | `/api/auth/change-password` | Change the current user's password. |

**Login example:**
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin"}'
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

### Users

> Admin only

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/users` | List all users |
| `POST` | `/api/users` | Create a new user |
| `PUT` | `/api/users/{id}` | Update user details |
| `DELETE` | `/api/users/{id}` | Delete a user |

### Groups

> Admin only

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/groups` | List all groups |
| `POST` | `/api/groups` | Create a group |
| `PUT` | `/api/groups/{id}` | Update group |
| `DELETE` | `/api/groups/{id}` | Delete a group |
| `POST` | `/api/groups/{id}/members` | Add users to group |
| `DELETE` | `/api/groups/{id}/members/{user_id}` | Remove a user from group |

### Collections

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `GET` | `/api/collections` | All users | List collections accessible to the current user |
| `POST` | `/api/collections` | Admin | Create a new collection |
| `PUT` | `/api/collections/{id}` | Admin | Update collection (name, description, context) |
| `DELETE` | `/api/collections/{id}` | Admin | Delete collection and all its documents |
| `POST` | `/api/collections/{id}/access` | Admin | Set group access permissions |

### Documents

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/collections/{id}/documents` | List documents in a collection |
| `POST` | `/api/collections/{id}/documents` | Upload a document (multipart/form-data) |
| `DELETE` | `/api/documents/{id}` | Delete a document and its chunks |
| `PUT` | `/api/documents/{id}/context` | Update the document's context description |
| `GET` | `/api/documents/{id}/status` | Get the processing status of a document |

**Upload example:**
```bash
curl -X POST http://localhost:8000/api/collections/1/documents \
  -H "Authorization: Bearer <token>" \
  -F "file=@/path/to/document.pdf"
```

### Chat & RAG

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/conversations` | List the current user's conversations |
| `POST` | `/api/conversations` | Create a new conversation |
| `DELETE` | `/api/conversations/{id}` | Delete a conversation |
| `GET` | `/api/conversations/{id}/messages` | Load all messages in a conversation |
| `POST` | `/api/chat` | Send a question. Returns a **Server-Sent Events** stream |
| `PUT` | `/api/chat/collections` | Update the user's active collections for search |

**Chat (SSE) example:**
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -d '{
    "conversation_id": 1,
    "message": "What are the torque specs for part #XY-421?"
  }'
```

The response is a stream of SSE events:
```
data: {"type": "token", "content": "The"}
data: {"type": "token", "content": " torque"}
...
data: {"type": "sources", "sources": [...]}
data: {"type": "done"}
```

### Settings

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/settings` | Get current system settings |
| `PUT` | `/api/settings` | Update system settings (admin only) |

### Health

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Returns `{"status": "healthy"}` when the backend is up |

---

## Project Structure

```
Atlas/
├── .env.example                    # Environment variable template
├── .gitignore
├── config.yaml                     # Central system configuration
├── docker-compose.yml              # Multi-container orchestration
├── LICENSE                         # GNU GPL v3
│
├── backend/
│   ├── Dockerfile                  # Python 3.12 + Tesseract OCR + Poppler
│   ├── requirements.txt            # Python dependencies (~55 packages)
│   └── app/
│       ├── main.py                 # FastAPI application entry point
│       ├── core/
│       │   ├── config.py           # YAML config loader + Pydantic models
│       │   ├── database.py         # SQLAlchemy async session setup
│       │   ├── security.py         # JWT encoding/decoding, bcrypt hashing
│       │   └── dependencies.py     # FastAPI dependency injection
│       ├── models/                 # SQLAlchemy ORM table definitions
│       │   ├── user.py
│       │   ├── group.py
│       │   ├── collection.py
│       │   ├── document.py
│       │   ├── chunk.py            # Includes pgvector embedding column
│       │   ├── conversation.py
│       │   └── system_setting.py
│       ├── schemas/                # Pydantic request/response schemas
│       │   ├── user.py
│       │   ├── group.py
│       │   ├── collection.py
│       │   ├── document.py
│       │   └── chat.py
│       ├── api/routes/             # API route handlers (thin controllers)
│       │   ├── auth.py
│       │   ├── users.py
│       │   ├── groups.py
│       │   ├── collections.py
│       │   ├── documents.py
│       │   ├── chat.py             # SSE streaming endpoint
│       │   └── settings.py
│       └── services/               # Business logic layer
│           ├── document_processor.py      # File parsing + chunking
│           ├── embedding_service.py       # Ollama embedding API calls
│           ├── retrieval_service.py       # Hybrid vector + full-text search
│           ├── query_enrichment_service.py # Query context expansion
│           ├── llm_service.py             # Ollama LLM calls
│           └── rag_pipeline.py            # Orchestrates the full RAG flow
│
├── frontend/
│   ├── Dockerfile                  # Multi-stage: Node build → Nginx serve
│   ├── nginx.conf                  # SPA routing + API proxy + upload limits
│   ├── package.json
│   ├── vite.config.ts              # Vite bundler + /api dev proxy
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   └── src/
│       ├── App.tsx                 # React Router setup
│       ├── main.tsx                # Application entry point
│       ├── pages/
│       │   ├── LoginPage.tsx
│       │   ├── ChatPage.tsx        # Main chat interface with SSE handling
│       │   ├── DocumentsPage.tsx   # Upload + document management
│       │   └── AdminPage.tsx       # User / group / collection management
│       ├── components/
│       │   ├── layout/             # MainLayout, Header, Sidebar
│       │   ├── chat/               # Message bubbles, input, source cards
│       │   ├── documents/          # Upload zone, document list
│       │   ├── admin/              # User, group, collection panels
│       │   └── auth/               # Login form
│       ├── stores/
│       │   ├── authStore.ts        # Zustand: JWT token + current user
│       │   └── chatStore.ts        # Zustand: active collections, conversations
│       ├── services/
│       │   └── api.ts              # Axios instance with auth interceptors
│       ├── types/
│       │   └── index.ts            # Shared TypeScript interfaces
│       ├── hooks/                  # Custom React hooks
│       └── utils/
│
├── scripts/
│   ├── setup.sh                    # Automated first-time setup
│   ├── pull-models.sh              # Download Ollama models
│   └── init-db.sql                 # PostgreSQL initialization (pgvector, trgm)
│
└── logs/                           # Application log output
```

---

## RAG Pipeline Deep Dive

### Document Ingestion

When a file is uploaded, the following steps occur asynchronously:

1. **Parsing** — `DocumentProcessor` extracts raw text from the file:
   - PDF: `pypdf` for digital PDFs; Tesseract OCR (via `pdf2image`) for scanned documents
   - DOCX: `python-docx`
   - XLSX/XLS: `openpyxl`
   - HTML: `beautifulsoup4`
   - TXT / MD / CSV / XML / JSON: plain text extraction

2. **Chunking** — The text is split into overlapping chunks using the configured strategy (`semantic` by default). Each chunk carries metadata: document title, page number, section header.

3. **Embedding** — Each chunk is sent to Ollama's `nomic-embed-text` model in batches of 32. The resulting 1024-dimensional vectors are stored in the `chunks` table (pgvector column).

4. **Full-text Indexing** — PostgreSQL's `pg_trgm` trigram index is built on the chunk text for hybrid search support.

### Query Processing

When a user sends a chat message:

1. **Query Enrichment** — `QueryEnrichmentService` prepends collection context text to the user's query before searching. This improves retrieval for domain-specific terminology.

2. **Hybrid Retrieval** — `RetrievalService` runs two searches in parallel:
   - **Vector search:** pgvector ANN (Approximate Nearest Neighbor) lookup with cosine similarity
   - **Full-text search:** PostgreSQL `pg_trgm` trigram similarity
   - Results are merged using a weighted score: `alpha * vector_score + (1 - alpha) * text_score` (default: 70% vector, 30% text)

3. **Reranking** — The top 10 merged results are passed through a cross-encoder reranker, which re-scores all chunk-query pairs together and selects the best 5.

4. **Context Assembly** — The 5 reranked chunks are formatted as a context block with source citations.

5. **LLM Generation** — The context + original question are sent to the LLM (via Ollama) with the system prompt. The response is streamed back to the browser using Server-Sent Events.

### Hybrid Search

```
User Query
    │
    ▼
Query Enrichment (+ collection context)
    │
    ├──── Vector Search (pgvector cosine ANN) ──────────────┐
    │                                                        │
    └──── Full-text Search (pg_trgm trigram similarity) ────┤
                                                             │
                                              Merge + Score (alpha weighting)
                                                             │
                                                    Cross-Encoder Reranking
                                                             │
                                                    Top-K Chunks → LLM
```

### Answer Generation

The LLM receives a prompt structured as:

```
[System Prompt]
Du bist Atlas, ein KI-Assistent fuer interne Firmendokumente.
Du antwortest ausschliesslich basierend auf den bereitgestellten Dokumenten.
...

[Context]
Quelle 1: <Document Title>, Seite 3
<chunk text>

Quelle 2: <Document Title>, Seite 7
<chunk text>
...

[Question]
<user question>
```

The response streams token by token to the frontend. After streaming completes, the source chunks are sent as a final SSE event so the UI can display clickable citations.

---

## Permissions Model

Atlas implements a three-tier permission hierarchy:

```
User
 └── belongs to → Group(s)
                    └── has access to → Collection(s)  (read | read-write)
                                          └── contains → Documents → Chunks
```

- A **user** can belong to multiple groups.
- A **group** can have read or read-write access to multiple collections.
- All retrieval queries are automatically scoped to collections the requesting user can access.
- Admin users bypass collection-level access checks and can manage all resources.

---

## Supported Document Formats

| Extension | Parser | OCR Support |
|---|---|---|
| `.pdf` | pypdf | Yes (Tesseract) |
| `.docx` / `.doc` | python-docx | No |
| `.xlsx` / `.xls` | openpyxl | No |
| `.pptx` | python-pptx | No |
| `.txt` | Plain text | No |
| `.md` | Plain text | No |
| `.csv` | Plain text | No |
| `.html` | BeautifulSoup4 | No |
| `.xml` | Plain text | No |
| `.json` | Plain text | No |

Maximum file size: **100 MB** (configurable via `documents.max_file_size_mb`).

OCR languages default to German + English (`deu+eng`). Additional Tesseract language packs can be added to the backend Dockerfile.

---

## Docker Services

| Service | Container Name | Port | Image |
|---|---|---|---|
| PostgreSQL + pgvector | `atlas-postgres` | 5432 | `pgvector/pgvector:pg16` |
| Ollama embedding server | `atlas-ollama` | 11434 | `ollama/ollama:latest` |
| llama.cpp LLM server | `atlas-llama-cpp` | 8080 | `ghcr.io/ggml-org/llama.cpp:server-cuda` |
| FastAPI backend | `atlas-backend` | 8000 | Custom (Python 3.12) |
| React frontend + Nginx | `atlas-frontend` | 3000 | Custom (Node + Nginx) |

Useful Docker Compose commands:

```bash
# Start all services
docker compose up -d

# View logs for a specific service
docker compose logs backend -f
docker compose logs ollama -f
docker compose logs llama-cpp -f

# Restart a single service after config change
docker compose restart backend

# Stop all services
docker compose down

# Stop and remove all data volumes (DESTRUCTIVE — loses all documents and embeddings)
docker compose down -v

# Rebuild images after code changes
docker compose up -d --build backend
docker compose up -d --build frontend

# Open a shell inside a container
docker exec -it atlas-backend bash
docker exec -it atlas-postgres psql -U atlas_user -d atlas
```

---

## Switching LLM Models

Atlas is model-agnostic — any model supported by Ollama can be used.

**1. Pull the new model:**
```bash
docker exec atlas-ollama ollama pull mistral:7b
# or
docker exec atlas-ollama ollama pull llama3.1:70b
# or
docker exec atlas-ollama ollama pull qwen2.5:14b
```

**2. Update `config.yaml`:**
```yaml
llm:
  model: "mistral:7b"
  context_window: 8192  # Adjust to match the model's actual context window
  max_tokens: 4096
```

**3. Restart the backend:**
```bash
docker compose restart backend
```

**Switching the embedding model** also requires re-embedding all documents (since vector dimensions may differ):

```bash
# Pull a different embedding model
docker exec atlas-ollama ollama pull mxbai-embed-large

# Update config.yaml:
#   embedding.model: "mxbai-embed-large"
#   embedding.dimensions: 1024  (verify the model's actual output size)
#   vector.dimensions: 1024

# Clear existing embeddings
docker exec -it atlas-postgres psql -U atlas_user -d atlas -c "TRUNCATE TABLE chunks;"

# Re-trigger processing for all documents via the UI or API
```

---

## Troubleshooting

### Containers fail to start

```bash
# Check which container is failing
docker compose ps
docker compose logs <service-name>
```

Common cause: missing `.env` file or unset `DB_PASSWORD` / `AUTH_SECRET_KEY`.

### Backend can't connect to the database

Check that the `postgres` container is healthy:
```bash
docker compose ps postgres
```
If it shows `(health: starting)`, wait a few seconds. The backend retries on startup but requires PostgreSQL to be healthy first.

### Ollama model not found

```bash
docker exec atlas-ollama ollama list
# If the model is missing, pull it again:
docker exec atlas-ollama ollama pull nomic-embed-text
```

### Document processing is stuck

Check the backend logs for errors:
```bash
docker compose logs backend -f
```

Large PDFs with many scanned pages can take several minutes due to OCR. You can poll the processing status via the API:
```bash
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/documents/<id>/status
```

### GPU not being used by Ollama

Verify the NVIDIA Container Toolkit is installed and the GPU is accessible:
```bash
docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi
```

If it fails, follow the [NVIDIA Container Toolkit installation guide](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html).

To force CPU-only mode, edit `config.yaml`:
```yaml
llm:
  num_gpu: 0
```

### Answers are slow or timing out

- Increase `llm.timeout` in `config.yaml`
- Switch to a smaller model (e.g., `llama3.2:3b`)
- Reduce `retrieval.top_k` and `retrieval.rerank_top_k`
- Ensure the GPU is being utilized (see above)

### Port conflicts

If ports 3000, 5432, 8000, or 11434 are already in use on the host, edit the `ports` section of `docker-compose.yml`:
```yaml
ports:
  - "8080:8000"  # Map host port 8080 to container port 8000
```

---

## Development

### Running the backend locally (without Docker)

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start a local PostgreSQL with pgvector and Ollama separately, then:
export DB_PASSWORD=dev_password
export AUTH_SECRET_KEY=$(openssl rand -hex 32)
export ADMIN_DEFAULT_PASSWORD=admin

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Running the frontend locally (without Docker)

```bash
cd frontend
npm install
npm run dev
# Proxies /api requests to http://localhost:8000 (configured in vite.config.ts)
```

### Adding a new API endpoint

1. Create or update a route file in `backend/app/api/routes/`
2. Add the corresponding Pydantic schemas to `backend/app/schemas/`
3. Add business logic to `backend/app/services/`
4. Register the router in `backend/app/main.py`

### Database migrations

The project uses SQLAlchemy's `create_all()` on startup. For production deployments, consider integrating [Alembic](https://alembic.sqlalchemy.org/). To reset the database entirely:

```bash
docker compose down -v          # Removes the postgres_data volume
docker compose up -d postgres   # Recreates the database
docker compose restart backend  # Re-seeds the admin user
```

### Viewing logs

Logs are written both to stdout (Docker) and to `logs/atlas.log` on the host (mounted volume):

```bash
tail -f logs/atlas.log
```

---

## License

Atlas is licensed under the **GNU General Public License v3.0**.

See [LICENSE](LICENSE) for the full license text.

In summary: you are free to use, study, modify, and distribute this software. Any modifications distributed to others must also be released under GPLv3.
