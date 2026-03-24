#!/bin/bash
# =============================================================================
# Model setup for Atlas RAG System (llama-server / GGUF)
# =============================================================================
# llama-server requires GGUF model files placed in the ../models/ directory.
# Set LLM_MODEL_FILE and EMBED_MODEL_FILE in .env to match the filenames.
#
# Example: download Qwen3-14B-Q4_K_M and a BGE-M3 embedding model
#   huggingface-cli download bartowski/Qwen3-14B-GGUF \
#       --include "Qwen3-14B-Q4_K_M.gguf" --local-dir ../models/
#   huggingface-cli download gpustack/bge-m3-GGUF \
#       --include "bge-m3-Q8_0.gguf" --local-dir ../models/
#
# Then update .env:
#   LLM_MODEL_FILE=Qwen3-14B-Q4_K_M.gguf
#   EMBED_MODEL_FILE=bge-m3-Q8_0.gguf
# =============================================================================

set -e

MODELS_DIR="../models"

echo "=== Atlas Model Setup (llama-server) ==="
echo ""
echo "Place GGUF model files in: $MODELS_DIR/"
echo ""
echo "Then set in .env:"
echo "  LLM_MODEL_FILE=<llm-model>.gguf"
echo "  EMBED_MODEL_FILE=<embed-model>.gguf"
echo ""

mkdir -p "$MODELS_DIR"

echo "Models directory ready: $MODELS_DIR"
echo ""
echo "To download models via HuggingFace CLI:"
echo "  pip install huggingface_hub"
echo "  huggingface-cli download <repo-id> --include '*.gguf' --local-dir $MODELS_DIR/"
echo ""
echo "Quantization guide:"
echo "  Q4_K_M  - good balance of quality and size (recommended)"
echo "  Q5_K_M  - higher quality, larger"
echo "  Q8_0    - near lossless, recommended for embedding models"
