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
echo "Lade LLM-Modell: llama3.1:8b (Hauptmodell und Kontext-Generierung)..."
docker exec atlas-ollama ollama pull llama3.1:8b

echo ""
echo "Modelle erfolgreich heruntergeladen."
