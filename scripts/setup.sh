#!/bin/bash
# =============================================================================
# Atlas RAG System - Erstinstallation
# =============================================================================
# Dieses Skript richtet das System für den ersten Start ein.
# Verwendung: chmod +x scripts/setup.sh && ./scripts/setup.sh
# =============================================================================

set -e

echo "================================================"
echo " Atlas RAG System - Setup"
echo "================================================"

# 1. Prüfe Voraussetzungen
echo ""
echo "[1/6] Prüfe Voraussetzungen..."

command -v docker >/dev/null 2>&1 || { echo "FEHLER: Docker ist nicht installiert."; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "FEHLER: Docker Compose ist nicht installiert."; exit 1; }
echo "  Docker: OK"
echo "  Docker Compose: OK"

# 2. .env Datei erstellen
echo ""
echo "[2/6] Erstelle .env Datei..."

if [ ! -f .env ]; then
    cp .env.example .env
    # Generiere sicheren Secret Key
    SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/bitte_mit_openssl_rand_hex_32_generieren/$SECRET_KEY/" .env
    echo "  .env erstellt. BITTE DB_PASSWORD und ADMIN_DEFAULT_PASSWORD anpassen!"
else
    echo "  .env existiert bereits."
fi

# 3. Verzeichnisse erstellen
echo ""
echo "[3/6] Erstelle Verzeichnisse..."
mkdir -p logs models
echo "  logs/ und models/ erstellt"

# 4. Docker-Container starten
echo ""
echo "[4/6] Starte Docker-Container..."
docker compose up -d postgres ollama llama-cpp
echo "  PostgreSQL, Ollama und llama.cpp gestartet. Warte auf Bereitschaft..."
sleep 10

# 5. Ollama-Modelle herunterladen
echo ""
echo "[5/6] Bereite LLM- und Embedding-Modelle vor..."
echo "  Embedding-Download kann beim ersten Mal mehrere Minuten dauern."
bash scripts/pull-models.sh

# 6. Backend und Frontend starten
echo ""
echo "[6/6] Starte Backend und Frontend..."
docker compose up -d
echo ""
echo "================================================"
echo " Atlas ist bereit!"
echo ""
echo " Frontend: http://localhost:3000"
echo " Backend:  http://localhost:8000"
echo " API-Docs: http://localhost:8000/docs"
echo ""
echo " Standard-Login:"
echo "   Benutzer: admin"
echo "   Passwort: (siehe .env ADMIN_DEFAULT_PASSWORD)"
echo ""
echo " WICHTIG: Ändern Sie das Admin-Passwort nach"
echo " dem ersten Login!"
echo "================================================"
