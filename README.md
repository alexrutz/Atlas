# Atlas

Lokales RAG-System (Retrieval-Augmented Generation) für firmeninterne Dokumente.

## Features

- **Vollständig lokal** — Läuft auf einem Server im Firmennetzwerk, keine Cloud-Dienste
- **Context-Enriched Embedding** — Fachbegriffe und Abkürzungen werden beim Embedding als Kontext mitgegeben
- **Benutzer & Gruppen** — Zugriffssteuerung über Gruppen (z.B. Konstruktion, Vertrieb, Service)
- **Collections** — Dokumente organisiert in Collections (z.B. Normen, Datenblätter, Anfragen)
- **Web-UI** — Chat, Dokumentenverwaltung und Admin-Panel im Browser

## Schnellstart

```bash
cp .env.example .env          # Umgebungsvariablen konfigurieren
nano .env                      # DB_PASSWORD und AUTH_SECRET_KEY setzen
chmod +x scripts/setup.sh
./scripts/setup.sh             # Alles einrichten und starten
```

Danach erreichbar unter `http://localhost:3000`

## Dokumentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — Systemarchitektur und Technologie-Stack
- [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) — Schritt-für-Schritt Implementierungsleitfaden

## Technologie-Stack

| Komponente | Technologie |
|---|---|
| Backend | Python 3.12, FastAPI |
| Frontend | React 18, TypeScript, Tailwind CSS |
| Datenbank | PostgreSQL 16 + pgvector |
| LLM | Ollama (lokale Modelle) |
| Container | Docker Compose |