#!/bin/bash
# RunPod startup script — run this inside a RunPod GPU pod
# Expects: NVIDIA GPU available, Docker + docker-compose installed
#
# Usage:
#   git clone <your-repo> && cd DecRAS
#   bash scripts/runpod_start.sh
#   # or with custom task:
#   TASK="Stack the red cup on the blue plate" bash scripts/runpod_start.sh

set -euo pipefail

echo "=========================================="
echo "  DecRAS — Distributed Robotics POC"
echo "=========================================="

# Check GPU
if command -v nvidia-smi &> /dev/null; then
    echo "GPU detected:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
else
    echo "WARNING: No GPU detected. Ollama will run on CPU (slow)."
fi

# Default model
export OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"
export TASK="${TASK:-Pick up the red cup and place it on the blue plate.}"
export MAX_STEPS="${MAX_STEPS:-30}"

echo ""
echo "Configuration:"
echo "  Model:     $OLLAMA_MODEL"
echo "  Task:      $TASK"
echo "  Max steps: $MAX_STEPS"
echo ""

# Build and run
echo "Building containers..."
docker compose build controller

echo "Starting Ollama + pulling model..."
docker compose up ollama model-pull

echo "Running controller..."
docker compose up controller 2>&1 | tee run.log

echo ""
echo "=========================================="
echo "  Run complete! Check results:"
echo "  - Logs:     run.log"
echo "  - Episodes: episodes/"
echo "  - Video:    episodes/*/episode.mp4"
echo "  - Replay:   python -m scripts.replay --latest"
echo "=========================================="
