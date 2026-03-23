#!/bin/bash
# =============================================================================
# Atlas RAG System - Initial Setup
# =============================================================================
# Usage: chmod +x scripts/setup.sh && ./scripts/setup.sh
# =============================================================================

set -e

echo "================================================"
echo " Atlas RAG System - Setup"
echo "================================================"

# 1. Check prerequisites
echo ""
echo "[1/5] Checking prerequisites..."

command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker is not installed."; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "ERROR: Docker Compose is not installed."; exit 1; }

# Check for NVIDIA GPU support
if command -v nvidia-smi >/dev/null 2>&1; then
    echo "  NVIDIA GPU: OK"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true
else
    echo "  WARNING: nvidia-smi not found. GPU support required for vLLM."
fi

echo "  Docker: OK"
echo "  Docker Compose: OK"

# 2. Create .env file
echo ""
echo "[2/5] Creating .env file..."

if [ ! -f .env ]; then
    cp .env.example .env
    SECRET_KEY=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/bitte_mit_openssl_rand_hex_32_generieren/$SECRET_KEY/" .env
    echo "  .env created. Please set DB_PASSWORD and ADMIN_DEFAULT_PASSWORD!"
else
    echo "  .env already exists."
fi

# 3. Check directories and model cache
echo ""
echo "[3/5] Setting up directories..."
mkdir -p logs
mkdir -p ../models/huggingface
mkdir -p ../postgres_data

echo "  Models will be auto-downloaded by vLLM from HuggingFace on first start."
echo "  Cache directory: ../models/huggingface"

# 4. Start Docker containers
echo ""
echo "[4/5] Starting database and vLLM servers..."
docker compose up -d postgres vllm-llm vllm-embed vllm-ocr
echo "  Waiting for services to be ready (this may take a while on first start)..."
echo "  vLLM will download models from HuggingFace if not cached."
sleep 30

# 5. Start backend and frontend
echo ""
echo "[5/5] Starting backend and frontend..."
docker compose up -d --build
echo ""
echo "================================================"
echo " Atlas is ready!"
echo ""
echo " Frontend: http://localhost:3000"
echo " Backend:  http://localhost:8000"
echo " API-Docs: http://localhost:8000/docs"
echo ""
echo " Default login:"
echo "   Username: admin"
echo "   Password: (see .env ADMIN_DEFAULT_PASSWORD)"
echo ""
echo " IMPORTANT: Change the admin password after"
echo " the first login!"
echo "================================================"
