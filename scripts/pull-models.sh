#!/bin/bash
# =============================================================================
# Modelle vorbereiten
# =============================================================================
# Lädt das Embedding-Modell via Ollama und prüft das llama.cpp GGUF-Modell.
# =============================================================================

set -e

LLM_MODEL_PATH="models/llama-3.1-8b-instruct.gguf"

echo "Lade Embedding-Modell: nomic-embed-text..."
docker exec atlas-ollama ollama pull nomic-embed-text

echo ""
if [ -f "$LLM_MODEL_PATH" ]; then
    echo "llama.cpp Modell gefunden: $LLM_MODEL_PATH"
else
    echo "FEHLER: llama.cpp Modell fehlt: $LLM_MODEL_PATH"
    echo "Bitte lade ein GGUF-Instruct-Modell herunter und speichere es unter:"
    echo "  $LLM_MODEL_PATH"
    exit 1
fi

echo ""
echo "Modelle erfolgreich vorbereitet."
