# Atlas RAG System - Systemarchitektur

## Überblick

Atlas ist ein vollständig lokales Retrieval-Augmented Generation (RAG) System für den Einsatz auf einem firmeninternen Server. Es ermöglicht Mitarbeitern, über eine Web-Oberfläche Fragen an firmeninterne Dokumente zu stellen und kontextbasierte Antworten zu erhalten.

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Firmennetzwerk                               │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                         │
│  │ PC       │  │ PC       │  │ PC       │  ... weitere Rechner     │
│  │ Browser  │  │ Browser  │  │ Browser  │                         │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                         │
│       │              │              │                               │
│       └──────────────┼──────────────┘                               │
│                      │ HTTP (Port 3000)                             │
│               ┌──────┴──────┐                                       │
│               │   Frontend  │  React SPA                            │
│               │   (Nginx)   │  Port 3000                            │
│               └──────┬──────┘                                       │
│                      │ REST API (Port 8000)                         │
│               ┌──────┴──────┐                                       │
│               │   Backend   │  FastAPI                              │
│               │   (Python)  │  Port 8000                            │
│               └──┬────┬──┬──┘                                       │
│                  │    │  │                                           │
│         ┌────────┘    │  └────────┐                                 │
│         │             │           │                                  │
│  ┌──────┴──────┐ ┌────┴────┐ ┌───┴───────┐                        │
│  │ PostgreSQL  │ │ Ollama  │ │  Datei-   │                         │
│  │ + pgvector  │ │ LLM &   │ │  system   │                        │
│  │ Port 5432   │ │ Embed.  │ │ (Uploads) │                        │
│  └─────────────┘ │ :11434  │ └───────────┘                        │
│                   └─────────┘                                       │
│                                                                     │
│                  ┌─ Server-Hardware ─┐                              │
│                  │ GPU (NVIDIA)      │                              │
│                  │ RAM ≥ 64 GB       │                              │
│                  │ SSD ≥ 1 TB        │                              │
│                  └───────────────────┘                              │
└─────────────────────────────────────────────────────────────────────┘
```

## Technologie-Stack

| Komponente | Technologie | Begründung |
|---|---|---|
| **Backend** | Python 3.12 + FastAPI | Async, performant, großes ML/NLP-Ökosystem |
| **Frontend** | React 18 + TypeScript + Vite | Modular, typsicher, schnelle Entwicklung |
| **UI-Framework** | shadcn/ui + Tailwind CSS | Professionell, anpassbar, keine externen Abhängigkeiten |
| **Datenbank** | PostgreSQL 16 + pgvector | Einheitliche DB für Daten UND Vektoren |
| **LLM-Server** | Ollama | Einfachste lokale LLM-Bereitstellung |
| **Embedding** | nomic-embed-text (via Ollama) | Gute Qualität, lokal, multilingual |
| **Containerisierung** | Docker Compose | Reproduzierbare Deployments |

## Kernkonzepte

### 1. Context-Enriched Embedding

Das zentrale Feature von Atlas. Da firmeninterne Dokumente viele Fachbegriffe und Abkürzungen enthalten, wird jeder Chunk vor dem Embedding mit Kontext angereichert:

```
┌─────────────────────────────────────────────────────────────┐
│                  Dokument-Upload                             │
│                                                              │
│  1. Benutzer lädt Dokument hoch                             │
│  2. Benutzer gibt Kontext-Beschreibung ein:                 │
│     "Dieses Dokument ist die DIN EN 1090-2 Norm für die     │
│      Ausführung von Stahltragwerken. EXC = Ausführungsklasse,│
│      WPS = Schweißanweisung, NDT = Zerstörungsfreie Prüfung"│
│  3. Benutzer kann Glossar-Einträge hinzufügen               │
│                                                              │
│  ┌──────────────┐     ┌──────────────────────────┐          │
│  │  Rohes PDF   │────▶│  Chunking                │          │
│  └──────────────┘     │  (semantisch/rekursiv)   │          │
│                        └──────────┬───────────────┘          │
│                                   │                          │
│                                   ▼                          │
│                        ┌──────────────────────────┐          │
│                        │  Kontext-Anreicherung    │          │
│                        │                          │          │
│                        │  Für jeden Chunk:        │          │
│                        │  • Dokumenttitel          │          │
│                        │  • Collection-Name        │          │
│                        │  • Abschnittsüberschrift  │          │
│                        │  • Kontext-Beschreibung   │          │
│                        │  • Relevante Glossar-     │          │
│                        │    Einträge               │          │
│                        │  • Original-Chunktext     │          │
│                        └──────────┬───────────────┘          │
│                                   │                          │
│                                   ▼                          │
│                        ┌──────────────────────────┐          │
│                        │  Embedding-Berechnung    │          │
│                        │  (auf angereichertem     │          │
│                        │   Text, nicht nur Chunk) │          │
│                        └──────────┬───────────────┘          │
│                                   │                          │
│                                   ▼                          │
│                        ┌──────────────────────────┐          │
│                        │  Speicherung in          │          │
│                        │  PostgreSQL + pgvector   │          │
│                        └──────────────────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

### 2. Berechtigungssystem

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│   Benutzer  │────▶│   Gruppen    │────▶│  Collections   │
│             │ M:N │              │ M:N │                │
│ - Max       │     │ - Konstrukt. │     │ - Normen       │
│ - Anna      │     │ - Vertrieb   │     │ - Datenblätter │
│ - Tom       │     │ - Service    │     │ - Anfragen     │
└─────────────┘     └──────────────┘     └────────────────┘

Beispiel:
  Max  ∈ {Konstruktion}     → Zugriff auf: Normen, Datenblätter
  Anna ∈ {Vertrieb,Service} → Zugriff auf: Anfragen, Datenblätter
  Tom  ∈ {Service}          → Zugriff auf: Anfragen

Admin kann:
  • Benutzer erstellen/bearbeiten/löschen
  • Gruppen erstellen/bearbeiten/löschen
  • Benutzer zu Gruppen zuordnen
  • Collections erstellen/bearbeiten/löschen
  • Gruppen Zugriff auf Collections gewähren (Lesen / Lesen+Schreiben)
```

### 3. RAG-Pipeline (Frage → Antwort)

```
┌─────────┐     ┌───────────────┐     ┌──────────────────┐
│ Benutzer│     │ Ausgewählte   │     │ Query-Embedding  │
│ Frage   │────▶│ Collections   │────▶│ berechnen        │
└─────────┘     │ filtern       │     └────────┬─────────┘
                └───────────────┘              │
                                               ▼
                                    ┌──────────────────┐
                                    │ Hybrid-Suche     │
                                    │ (Vektor + Vollt.)│
                                    │ NUR in erlaubten │
                                    │ Collections      │
                                    └────────┬─────────┘
                                             │
                                             ▼
                                    ┌──────────────────┐
                                    │ Reranking        │
                                    │ (Top-K Chunks)   │
                                    └────────┬─────────┘
                                             │
                                             ▼
                                    ┌──────────────────┐
                                    │ LLM-Prompt       │
                                    │ System-Prompt +  │
                                    │ Chunks + Frage   │
                                    └────────┬─────────┘
                                             │
                                             ▼
                                    ┌──────────────────┐
                                    │ Antwort mit      │
                                    │ Quellenangaben   │
                                    └──────────────────┘
```

## Projektstruktur

```
Atlas/
├── config.yaml                    # Zentrale Konfiguration
├── docker-compose.yml             # Container-Orchestrierung
├── .env                           # Umgebungsvariablen (Secrets)
│
├── backend/                       # Python FastAPI Backend
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini                # DB-Migrations-Konfiguration
│   ├── alembic/                   # DB-Migrationen
│   │   └── versions/
│   ├── app/
│   │   ├── main.py                # FastAPI App Einstiegspunkt
│   │   ├── core/
│   │   │   ├── config.py          # config.yaml laden & validieren
│   │   │   ├── database.py        # PostgreSQL Verbindung
│   │   │   ├── security.py        # JWT, Passwort-Hashing
│   │   │   └── dependencies.py    # FastAPI Dependencies
│   │   ├── models/                # SQLAlchemy ORM Modelle
│   │   │   ├── user.py
│   │   │   ├── group.py
│   │   │   ├── collection.py
│   │   │   ├── document.py
│   │   │   ├── chunk.py
│   │   │   └── conversation.py
│   │   ├── schemas/               # Pydantic Request/Response Schemas
│   │   │   ├── user.py
│   │   │   ├── group.py
│   │   │   ├── collection.py
│   │   │   ├── document.py
│   │   │   └── chat.py
│   │   ├── api/
│   │   │   └── routes/
│   │   │       ├── auth.py        # Login, Token-Refresh
│   │   │       ├── users.py       # Benutzerverwaltung (Admin)
│   │   │       ├── groups.py      # Gruppenverwaltung (Admin)
│   │   │       ├── collections.py # Collection-Verwaltung
│   │   │       ├── documents.py   # Dokument-Upload & Verwaltung
│   │   │       └── chat.py        # Chat/RAG-Endpunkt
│   │   ├── services/              # Business-Logik
│   │   │   ├── document_processor.py  # Dokument-Parsing & Chunking
│   │   │   ├── embedding_service.py   # Embedding-Berechnung
│   │   │   ├── context_enrichment.py  # Kontext-Anreicherung
│   │   │   ├── retrieval_service.py   # Hybrid-Suche & Reranking
│   │   │   ├── llm_service.py         # LLM-Kommunikation
│   │   │   └── rag_pipeline.py        # Orchestrierung der RAG-Pipeline
│   │   └── utils/
│   │       ├── file_parsers.py    # PDF, DOCX, XLSX Parser
│   │       └── text_processing.py # Tokenisierung, Chunking
│   └── tests/
│
├── frontend/                      # React Frontend
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── public/
│   └── src/
│       ├── App.tsx                # App-Root mit Router
│       ├── main.tsx               # Einstiegspunkt
│       ├── pages/
│       │   ├── LoginPage.tsx
│       │   ├── ChatPage.tsx       # Haupt-Chatansicht
│       │   ├── DocumentsPage.tsx  # Dokumenten-Verwaltung
│       │   └── AdminPage.tsx      # Admin-Panel
│       ├── components/
│       │   ├── layout/
│       │   │   ├── Sidebar.tsx    # Navigation
│       │   │   ├── Header.tsx
│       │   │   └── MainLayout.tsx
│       │   ├── chat/
│       │   │   ├── ChatWindow.tsx
│       │   │   ├── MessageBubble.tsx
│       │   │   ├── ChatInput.tsx
│       │   │   ├── SourceReference.tsx
│       │   │   └── CollectionSelector.tsx
│       │   ├── documents/
│       │   │   ├── DocumentList.tsx
│       │   │   ├── DocumentUpload.tsx
│       │   │   ├── ContextEditor.tsx     # Kontext-Beschreibung eingeben
│       │   │   └── GlossaryEditor.tsx    # Glossar-Einträge verwalten
│       │   ├── admin/
│       │   │   ├── UserManagement.tsx
│       │   │   ├── GroupManagement.tsx
│       │   │   ├── CollectionManagement.tsx
│       │   │   └── AccessControl.tsx     # Gruppen ↔ Collections
│       │   └── auth/
│       │       └── LoginForm.tsx
│       ├── hooks/                 # Custom React Hooks
│       ├── services/              # API-Client
│       │   └── api.ts
│       ├── stores/                # Zustand State-Management
│       │   ├── authStore.ts
│       │   └── chatStore.ts
│       ├── types/                 # TypeScript Typen
│       │   └── index.ts
│       └── utils/
│
├── scripts/                       # Hilfsskripte
│   ├── init-db.sql               # Datenbank-Initialisierung
│   ├── setup.sh                  # Erstinstallation
│   └── pull-models.sh            # Ollama-Modelle herunterladen
│
└── logs/                          # Log-Dateien
```

## API-Endpunkte

### Authentifizierung
| Methode | Pfad | Beschreibung |
|---|---|---|
| POST | `/api/auth/login` | Login, gibt JWT zurück |
| POST | `/api/auth/refresh` | Token erneuern |
| POST | `/api/auth/change-password` | Passwort ändern |

### Benutzer (Admin)
| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/api/users` | Alle Benutzer auflisten |
| POST | `/api/users` | Neuen Benutzer erstellen |
| PUT | `/api/users/{id}` | Benutzer bearbeiten |
| DELETE | `/api/users/{id}` | Benutzer löschen |

### Gruppen (Admin)
| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/api/groups` | Alle Gruppen auflisten |
| POST | `/api/groups` | Neue Gruppe erstellen |
| PUT | `/api/groups/{id}` | Gruppe bearbeiten |
| DELETE | `/api/groups/{id}` | Gruppe löschen |
| POST | `/api/groups/{id}/members` | Mitglieder zuordnen |
| DELETE | `/api/groups/{id}/members/{user_id}` | Mitglied entfernen |

### Collections
| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/api/collections` | Eigene zugängliche Collections |
| POST | `/api/collections` | Neue Collection erstellen (Admin) |
| PUT | `/api/collections/{id}` | Collection bearbeiten (Admin) |
| DELETE | `/api/collections/{id}` | Collection löschen (Admin) |
| POST | `/api/collections/{id}/access` | Gruppenzugriff setzen (Admin) |

### Dokumente
| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/api/collections/{id}/documents` | Dokumente einer Collection |
| POST | `/api/collections/{id}/documents` | Dokument hochladen |
| DELETE | `/api/documents/{id}` | Dokument löschen |
| PUT | `/api/documents/{id}/context` | Kontext-Beschreibung aktualisieren |
| GET | `/api/documents/{id}/status` | Verarbeitungsstatus abfragen |

### Glossar
| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/api/collections/{id}/glossary` | Glossar einer Collection |
| POST | `/api/collections/{id}/glossary` | Glossar-Eintrag hinzufügen |
| PUT | `/api/glossary/{id}` | Eintrag bearbeiten |
| DELETE | `/api/glossary/{id}` | Eintrag löschen |

### Chat
| Methode | Pfad | Beschreibung |
|---|---|---|
| GET | `/api/conversations` | Eigene Konversationen |
| POST | `/api/conversations` | Neue Konversation erstellen |
| DELETE | `/api/conversations/{id}` | Konversation löschen |
| POST | `/api/chat` | Frage stellen (SSE-Stream) |
| PUT | `/api/chat/collections` | Aktive Collections setzen |

## Hardware-Anforderungen

### Minimum (für Modelle bis 8B Parameter)
- CPU: 8 Kerne
- RAM: 32 GB
- GPU: NVIDIA mit 12 GB VRAM (z.B. RTX 3060)
- SSD: 500 GB

### Empfohlen (für Modelle 30B-70B Parameter)
- CPU: 16+ Kerne
- RAM: 64+ GB
- GPU: NVIDIA mit 24+ GB VRAM (z.B. RTX 4090 oder A6000)
- SSD: 1+ TB NVMe
