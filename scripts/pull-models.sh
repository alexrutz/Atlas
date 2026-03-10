#!/bin/bash
# =============================================================================
# Ollama-Modelle herunterladen
# =============================================================================
# Lädt die in config.yaml konfigurierten Modelle herunter.
# =============================================================================

set -e

OLLAMA_URL="http://localhost:11434"

echo "Lade Embedding-Modell: nomic-embed-text..."
docker exec atlas-ollama ollama pull nomic-embed-text

echo ""
echo "Lade LLM-Modell: llama3.1:8b (kleines Modell für Kontext-Generierung)..."
docker exec atlas-ollama ollama pull llama3.1:8b

echo ""
echo "Lade LLM-Modell: llama3.1:70b (Hauptmodell für Antworten)..."
echo "HINWEIS: Dieses Modell ist ca. 40 GB groß und benötigt eine GPU mit mindestens 48 GB VRAM."
echo "Falls Sie weniger VRAM haben, ändern Sie in config.yaml das Modell auf 'llama3.1:8b'."
docker exec atlas-ollama ollama pull llama3.1:70b || {
    echo ""
    echo "WARNUNG: Download von llama3.1:70b fehlgeschlagen."
    echo "Bitte passen Sie config.yaml an ein kleineres Modell an (z.B. llama3.1:8b)."
}

echo ""
echo "Modelle erfolgreich heruntergeladen."
