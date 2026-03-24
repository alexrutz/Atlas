#!/bin/bash
# =============================================================================
# Model setup for Atlas RAG System (vLLM)
# =============================================================================
# vLLM downloads models from HuggingFace automatically on first start.
# Alternatively, place models in the ../models directory.
# =============================================================================

set -e

MODELS_DIR="../models"

echo "=== Atlas Model Setup ==="
echo ""
echo "vLLM downloads models from HuggingFace automatically on first start."
echo "Default models:"
echo ""
echo "  LLM:       Qwen/Qwen3.5-35B-A3B"
echo "  Embedding: pplx-ai/pplx-embed-context-4b"
echo ""
echo "Models will be cached in '$MODELS_DIR/huggingface'."
echo ""

mkdir -p "$MODELS_DIR/huggingface"

echo "Model cache directory ready: $MODELS_DIR/huggingface"
echo ""
echo "To pre-download models, you can run:"
echo "  huggingface-cli download Qwen/Qwen3.5-35B-A3B --cache-dir $MODELS_DIR/huggingface"
echo "  huggingface-cli download pplx-ai/pplx-embed-context-4b --cache-dir $MODELS_DIR/huggingface"
