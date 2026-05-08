#!/bin/bash
# =============================================================================
# Model setup for Atlas RAG System (llama-server / GGUF)
# =============================================================================
# llama-server requires GGUF model files placed in the ../models/ directory.
# This script downloads the default LLM, embedding, and reranker models via
# the Hugging Face CLI. Adjust the quant levels in .env if you need a smaller
# footprint.
# =============================================================================

set -e

MODELS_DIR="../models"

LLM_REPO="unsloth/Qwen3.6-35B-A3B-GGUF"
LLM_FILE="${LLM_MODEL_FILE:-Qwen3.6-35B-A3B-UD-Q5_K_XL.gguf}"

EMBED_REPO="Qwen/Qwen3-Embedding-4B-GGUF"
EMBED_FILE="${EMBED_MODEL_FILE:-Qwen3-Embedding-4B-Q6_K.gguf}"

RERANK_REPO="Voodisss/Qwen3-Reranker-4B-GGUF-llama_cpp"
RERANK_FILE="${RERANK_MODEL_FILE:-Qwen3-Reranker-4B-Q6_K.gguf}"

echo "=== Atlas Model Setup (llama-server) ==="
echo ""
echo "Target directory: $MODELS_DIR/"
echo ""
echo "Models to download:"
echo "  LLM       : $LLM_REPO -> $LLM_FILE   (~26.6 GB)"
echo "  Embedding : $EMBED_REPO -> $EMBED_FILE   (~3.31 GB, 2560-dim)"
echo "  Reranker  : $RERANK_REPO -> $RERANK_FILE   (~3.31 GB)"
echo ""

mkdir -p "$MODELS_DIR"

if ! command -v huggingface-cli >/dev/null 2>&1; then
    echo "huggingface-cli not found. Install it with:"
    echo "  pip install -U huggingface_hub"
    exit 1
fi

echo "Downloading LLM..."
huggingface-cli download "$LLM_REPO" --include "$LLM_FILE" --local-dir "$MODELS_DIR/"

echo "Downloading embedding model..."
huggingface-cli download "$EMBED_REPO" --include "$EMBED_FILE" --local-dir "$MODELS_DIR/"

echo "Downloading reranker model..."
huggingface-cli download "$RERANK_REPO" --include "$RERANK_FILE" --local-dir "$MODELS_DIR/"

echo ""
echo "Done. Verify your .env values match the downloaded filenames:"
echo "  LLM_MODEL_FILE=$LLM_FILE"
echo "  EMBED_MODEL_FILE=$EMBED_FILE"
echo "  RERANK_MODEL_FILE=$RERANK_FILE"
echo ""
echo "Quantization guide:"
echo "  Q4_K_M / Q4_K_XL  - good balance of quality and size"
echo "  Q5_K_M / Q5_K_XL  - higher quality, larger (LLM default)"
echo "  Q6_K              - near lossless, recommended for embedding/reranker"
echo "  Q8_0              - lossless, large"
