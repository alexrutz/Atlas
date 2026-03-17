#!/bin/bash
# =============================================================================
# Modelle herunterladen für llama.cpp
# =============================================================================
# Die GGUF-Modelle müssen manuell in den ../models Ordner gelegt werden.
# =============================================================================

set -e

MODELS_DIR="../models"

echo "=== Atlas Modell-Setup ==="
echo ""
echo "Stelle sicher, dass folgende Modelle im Ordner '$MODELS_DIR' vorhanden sind:"
echo ""
echo "  LLM:       Qwen3.5-35B-A3B-UD-IQ3_S.gguf"
echo "  Embedding:  pplx-embed-context-v1-0.6b-q8_0.gguf"
echo ""

if [ -d "$MODELS_DIR" ]; then
    echo "Vorhandene Modelle:"
    ls -lh "$MODELS_DIR"/*.gguf 2>/dev/null || echo "  Keine .gguf Dateien gefunden"
else
    echo "Erstelle Modell-Verzeichnis: $MODELS_DIR"
    mkdir -p "$MODELS_DIR"
fi

echo ""
echo "Modelle können z.B. von Hugging Face heruntergeladen werden."
