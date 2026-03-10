# Atlas RAG System - Implementierungsleitfaden

Dieser Leitfaden beschreibt die schrittweise Implementierung des Atlas RAG Systems.
Das Projekt ist in **6 Phasen** aufgeteilt, die nacheinander umgesetzt werden sollten.

---

## Phase 1: Infrastruktur & Datenbank (Woche 1)

### Ziel
Alle Container laufen, die Datenbank ist eingerichtet, der erste Admin-User kann sich einloggen.

### Schritte

**1.1 Server vorbereiten**
```bash
# Docker & Docker Compose installieren (Ubuntu/Debian)
sudo apt update
sudo apt install docker.io docker-compose-plugin

# NVIDIA Container Toolkit installieren (für GPU-Unterstützung)
# Siehe: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

# Benutzer zur Docker-Gruppe hinzufügen
sudo usermod -aG docker $USER
```

**1.2 Repository klonen und konfigurieren**
```bash
git clone <repository-url> Atlas
cd Atlas
cp .env.example .env
# .env bearbeiten: DB_PASSWORD und AUTH_SECRET_KEY setzen
nano .env
```

**1.3 PostgreSQL starten und testen**
```bash
docker compose up -d postgres
# Prüfe ob pgvector installiert ist:
docker exec atlas-postgres psql -U atlas_user -d atlas -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

**1.4 Ollama starten und Modelle laden**
```bash
docker compose up -d ollama
# Embedding-Modell herunterladen
docker exec atlas-ollama ollama pull nomic-embed-text
# LLM herunterladen (Größe anpassen an verfügbare GPU)
docker exec atlas-ollama ollama pull llama3.1:8b
```

**1.5 Backend starten und testen**
```bash
docker compose up -d backend
# Health-Check
curl http://localhost:8000/api/health
# API-Dokumentation öffnen
# Browser: http://localhost:8000/docs
```

**1.6 Frontend starten**
```bash
docker compose up -d frontend
# Browser: http://localhost:3000
```

### Erfolgskriterien
- [ ] Alle 4 Container laufen (`docker compose ps`)
- [ ] PostgreSQL hat pgvector Extension
- [ ] Ollama antwortet auf API-Calls
- [ ] Backend Health-Check gibt `{"status": "healthy"}` zurück
- [ ] Frontend zeigt Login-Seite an

---

## Phase 2: Authentifizierung & Benutzerverwaltung (Woche 2)

### Ziel
Login funktioniert, Admin kann Benutzer und Gruppen verwalten, JWT-basierte Authentifizierung ist aktiv.

### Schritte

**2.1 Admin-Seed implementieren**
- In `backend/app/main.py` beim Startup einen Admin-User erstellen, falls keiner existiert
- Credentials aus `config.yaml` (`auth.default_admin_username/password`)

**2.2 Login-Flow fertigstellen**
- `POST /api/auth/login` → gibt JWT zurück
- Frontend `LoginPage.tsx` → speichert Token in localStorage
- `authStore.ts` → lädt Token beim App-Start

**2.3 Admin-Panel: Benutzerverwaltung**
- `AdminPage.tsx > UsersTab` implementieren:
  - Tabelle aller Benutzer
  - Dialog: Benutzer erstellen (Username, E-Mail, Name, Passwort, Admin-Flag)
  - Benutzer bearbeiten/deaktivieren/löschen

**2.4 Admin-Panel: Gruppenverwaltung**
- `AdminPage.tsx > GroupsTab` implementieren:
  - Gruppen erstellen/bearbeiten/löschen
  - Mitglieder per Drag & Drop oder Multi-Select zuordnen

### Erfolgskriterien
- [ ] Admin kann sich einloggen
- [ ] Admin kann Benutzer erstellen
- [ ] Admin kann Gruppen erstellen und Benutzer zuordnen
- [ ] Normale Benutzer sehen kein Admin-Panel
- [ ] Token-Refresh funktioniert

---

## Phase 3: Collections & Dokumenten-Upload (Woche 3-4)

### Ziel
Dokumente können hochgeladen, verarbeitet und in Collections organisiert werden. Context-Enriched Embedding funktioniert.

### Schritte

**3.1 Collection-Verwaltung (Admin)**
- `AdminPage.tsx > CollectionsTab` implementieren:
  - Collections erstellen/bearbeiten/löschen
  - Matrix: Gruppen × Collections mit Read/Write Checkboxen

**3.2 Dokument-Upload implementieren**
- `DocumentsPage.tsx` Upload-Bereich fertigstellen:
  - react-dropzone Integration
  - Fortschrittsanzeige beim Upload
  - Kontext-Beschreibung Textarea beim Upload

**3.3 Dokument-Verarbeitung (Backend)**
- `document_processor.py` fertigstellen:
  - Hintergrund-Task mit FastAPI BackgroundTasks
  - Status-Updates in DB schreiben
  - Frontend pollt Status über `/api/documents/{id}/status`

**3.4 Context-Enriched Embedding implementieren**
Dies ist die **kritischste Komponente** des Systems:

```python
# Ablauf für jeden Chunk:
# 1. Dokumenttitel + Collection-Name laden
# 2. Kontext-Beschreibung des Uploaders laden
# 3. Collection-Glossar + Dokument-Glossar zusammenführen
# 4. Relevante Glossar-Einträge für diesen Chunk filtern
# 5. Template befüllen:
#
#    Dokument: DIN EN 1090-2
#    Sammlung: Normen
#    Abschnitt: 7.5 Schweißen
#    Kontext: Europäische Norm für die Ausführung von Stahltragwerken
#    Glossar: EXC: Ausführungsklasse; WPS: Schweißanweisung
#    ---
#    [Originaler Chunk-Text]
#
# 6. Embedding auf dem ANGEREICHERTEN Text berechnen
# 7. Originaltext UND angereichertem Text in DB speichern
```

**3.5 Glossar-Verwaltung**
- `DocumentsPage.tsx` Glossar-Editor fertigstellen:
  - Einträge hinzufügen (Term, Abkürzung, Definition)
  - Einträge bearbeiten/löschen
  - Automatische Glossar-Extraktion per Button

### Erfolgskriterien
- [ ] Admin kann Collections erstellen und Gruppen Zugriff geben
- [ ] Benutzer sehen nur ihre erlaubten Collections
- [ ] Dokumente können hochgeladen werden
- [ ] Kontext-Beschreibung wird beim Upload gespeichert
- [ ] Dokument wird in Chunks aufgeteilt
- [ ] Chunks werden kontextangereichert und embedded
- [ ] Verarbeitungsstatus wird korrekt angezeigt
- [ ] Glossar-Einträge können verwaltet werden

---

## Phase 4: RAG-Pipeline & Chat (Woche 5-6)

### Ziel
Benutzer können Fragen stellen und erhalten Antworten mit Quellenangaben.

### Schritte

**4.1 Retrieval-Service fertigstellen**
- Vektor-Suche mit pgvector
- Volltext-Suche mit pg_trgm
- Hybrid-Suche (gewichtete Kombination)
- **WICHTIG**: Nur in Collections suchen, auf die der Benutzer Zugriff hat

**4.2 LLM-Integration**
- Ollama API-Anbindung testen
- System-Prompt aus `config.yaml` laden
- RAG-Prompt mit Kontexten aufbauen
- Quellenangaben in der Antwort sicherstellen

**4.3 Chat-Endpunkt implementieren**
- `POST /api/chat` fertigstellen:
  1. Ausgewählte Collections des Benutzers laden
  2. Berechtigungen prüfen
  3. Query-Embedding berechnen
  4. Hybrid-Suche durchführen
  5. Reranking
  6. LLM-Prompt bauen und Antwort generieren
  7. Konversation in DB speichern
  8. Antwort mit Quellen zurückgeben

**4.4 Chat-Frontend fertigstellen**
- `ChatPage.tsx`:
  - Collection-Checkboxen links
  - Nachrichten-Anzeige mit Markdown-Rendering
  - Quellenangaben klappbar unter jeder Antwort
  - Loading-Animation während der Antwort-Generierung
  - Konversations-Verlauf in Sidebar

**4.5 Streaming implementieren (optional aber empfohlen)**
- Server-Sent Events (SSE) für Echtzeit-Antworten
- Backend: `StreamingResponse` mit Ollama Stream
- Frontend: `EventSource` API

### Erfolgskriterien
- [ ] Fragen werden korrekt beantwortet
- [ ] Antworten basieren nur auf den Dokumenten
- [ ] Quellenangaben sind korrekt
- [ ] Nur erlaubte Collections werden durchsucht
- [ ] Chat-Verlauf wird gespeichert
- [ ] Antworten kommen innerhalb von 10-30 Sekunden

---

## Phase 5: Feinschliff & Optimierung (Woche 7)

### Ziel
System ist produktionsreif, performant und benutzerfreundlich.

### Schritte

**5.1 Retrieval-Qualität verbessern**
- Chunking-Parameter tunen (Größe, Überlappung)
- Embedding-Qualität evaluieren
- Reranking mit Cross-Encoder implementieren
- A/B-Tests verschiedener Konfigurationen

**5.2 Context-Enrichment verbessern**
- Template optimieren basierend auf Testergebnissen
- Automatische Glossar-Extraktion verbessern
- Abschnittsüberschriften besser erkennen

**5.3 Performance-Optimierung**
- Datenbank-Indizes prüfen und optimieren
- Embedding-Cache einführen (für identische Queries)
- Connection-Pool-Einstellungen tunen
- Ollama GPU-Nutzung optimieren

**5.4 UI/UX verfeinern**
- Responsive Design testen
- Keyboard-Shortcuts (Enter = Senden)
- Fehlermeldungen benutzerfreundlich gestalten
- Dark Mode (optional)

**5.5 Logging & Monitoring**
- Structured Logging fertigstellen
- Metriken: Antwortzeit, Token-Verbrauch, Queries pro Tag
- Fehler-Alerting einrichten

---

## Phase 6: Sicherheit & Deployment (Woche 8)

### Ziel
System ist sicher, dokumentiert und im Firmennetzwerk erreichbar.

### Schritte

**6.1 Sicherheit**
- Rate-Limiting implementieren
- Input-Validierung überall prüfen
- SQL-Injection-Schutz verifizieren (SQLAlchemy ORM)
- CORS-Einstellungen auf Firmennetzwerk beschränken
- HTTPS mit Self-Signed-Zertifikat oder interner CA einrichten

**6.2 Netzwerk-Konfiguration**
```bash
# Server im Firmennetzwerk erreichbar machen:
# 1. Firewall-Regeln für Port 3000 (oder 443 mit HTTPS)
# 2. DNS-Eintrag im internen DNS: atlas.firma.local → Server-IP
# 3. Optional: Reverse Proxy (nginx/traefik) vor dem System

# In config.yaml anpassen:
# server.cors_origins: ["https://atlas.firma.local"]
```

**6.3 Backup-Strategie**
```bash
# PostgreSQL Backup (täglich per Cronjob)
docker exec atlas-postgres pg_dump -U atlas_user atlas > backup_$(date +%Y%m%d).sql

# Ollama-Modelle sind in Docker-Volume und müssen nicht gesichert werden
# (können jederzeit neu heruntergeladen werden)
```

**6.4 Dokumentation**
- Benutzerhandbuch schreiben
- Admin-Handbuch schreiben
- Troubleshooting-Guide erstellen

### Erfolgskriterien
- [ ] System über `https://atlas.firma.local` erreichbar
- [ ] Alle Mitarbeiter haben Accounts
- [ ] Gruppen und Collections sind eingerichtet
- [ ] Erste Dokumente sind hochgeladen und verarbeitet
- [ ] Backup läuft automatisch
- [ ] Benutzer sind eingewiesen

---

## Technische Hinweise

### Config.yaml ändern
Alle Änderungen an `config.yaml` erfordern einen Neustart des Backends:
```bash
docker compose restart backend
```

### Modell wechseln
```bash
# 1. Neues Modell herunterladen
docker exec atlas-ollama ollama pull mistral:7b

# 2. In config.yaml anpassen
# llm.model: "mistral:7b"

# 3. Backend neu starten
docker compose restart backend
```

### Embedding-Dimensionen ändern
**ACHTUNG**: Wenn Sie das Embedding-Modell oder die Dimensionen ändern:
1. Alle bestehenden Embeddings werden ungültig
2. Die pgvector-Spalte muss angepasst werden
3. Alle Dokumente müssen neu verarbeitet werden

```sql
-- Chunks-Tabelle anpassen (z.B. auf 768 Dimensionen)
ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(768);
-- Alle Dokumente als "pending" markieren für Neuverarbeitung
UPDATE documents SET processing_status = 'pending', chunk_count = 0;
DELETE FROM chunks;
```

### Alembic-Migrationen einrichten
```bash
cd backend
alembic init alembic
# alembic.ini anpassen: sqlalchemy.url aus config.yaml laden
# alembic/env.py: target_metadata = Base.metadata

# Migration erstellen
alembic revision --autogenerate -m "initial schema"

# Migration ausführen
alembic upgrade head
```

### Häufige Probleme

| Problem | Lösung |
|---|---|
| Ollama antwortet nicht | `docker logs atlas-ollama` prüfen, GPU-Treiber checken |
| Embedding-Fehler | Prüfen ob `nomic-embed-text` heruntergeladen ist: `docker exec atlas-ollama ollama list` |
| Langsame Antworten | Kleineres Modell verwenden oder GPU prüfen |
| Speicherplatz voll | Alte Ollama-Modelle löschen: `docker exec atlas-ollama ollama rm <modell>` |
| DB-Verbindungsfehler | `docker compose restart postgres`, Pool-Einstellungen prüfen |
