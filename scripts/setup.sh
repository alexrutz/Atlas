#!/bin/bash
# =============================================================================
# Atlas RAG System - Erstinstallation
# =============================================================================
# Verwendung: chmod +x scripts/setup.sh && ./scripts/setup.sh
# =============================================================================

set -e

echo "================================================"
echo " Atlas RAG System - Setup"
echo "================================================"

# 1. Prüfe Voraussetzungen
echo ""
echo "[1/5] Prüfe Voraussetzungen..."

command -v docker >/dev/null 2>&1 || { echo "FEHLER: Docker ist nicht installiert."; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "FEHLER: Docker Compose ist nicht installiert."; exit 1; }
echo "  Docker: OK"
echo "  Docker Compose: OK"

# 2. .env Datei erstellen
echo ""
echo "[2/5] Erstelle .env Datei..."

if [ ! -f .env ]; then
    cp .env.example .env
    SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/bitte_mit_openssl_rand_hex_32_generieren/$SECRET_KEY/" .env
    echo "  .env erstellt. BITTE DB_PASSWORD und ADMIN_DEFAULT_PASSWORD anpassen!"
else
    echo "  .env existiert bereits."
fi

# 3. Verzeichnisse und Modelle prüfen
echo ""
echo "[3/5] Prüfe Verzeichnisse und Modelle..."
mkdir -p logs
mkdir -p ../models
mkdir -p ../postgres_data

if [ ! -f ../models/Qwen3.5-35B-A3B-UD-IQ3_S.gguf ]; then
    echo "  WARNUNG: LLM-Modell nicht gefunden in ../models/"
    echo "  Bitte Qwen3.5-35B-A3B-UD-IQ3_S.gguf herunterladen"
fi

if [ ! -f ../models/pplx-embed-context-v1-0.6b-q8_0.gguf ]; then
    echo "  WARNUNG: Embedding-Modell nicht gefunden in ../models/"
    echo "  Bitte pplx-embed-context-v1-0.6b-q8_0.gguf herunterladen"
fi

# 4. Docker-Container starten
echo ""
echo "[4/5] Starte Datenbank und LLM-Server..."
docker compose up -d postgres llama-cpp llama-cpp-embed
echo "  Warte auf Bereitschaft..."
sleep 15

# 5. Backend und Frontend starten
echo ""
echo "[5/5] Starte Backend und Frontend..."
docker compose up -d --build
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
