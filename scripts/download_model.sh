#!/usr/bin/env bash
# Downloads the quantized AI model used by MiniSim v5.
# Default: Qwen2.5-3B-Instruct (Q4_K_M) ~ 2GB. Great balance for a Pi 5 16GB.
# Stored on your NVMe SSD (fast). Run once.
set -e
MODEL_DIR="$(dirname "$0")/../models"
mkdir -p "$MODEL_DIR"
URL="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"
OUT="$MODEL_DIR/qwen2.5-3b-instruct-q4_k_m.gguf"
if [ -f "$OUT" ]; then
  echo "Model already present: $OUT"; exit 0
fi
echo "Downloading quantized model (~2GB) to $OUT ..."
if command -v curl >/dev/null; then
  curl -L "$URL" -o "$OUT"
else
  wget -O "$OUT" "$URL"
fi
echo "Done. Model ready at $OUT"
echo "Tip: on a Pi 5 16GB you can use a larger model (e.g. Qwen2.5-7B Q4) for"
echo "sharper reasoning — edit LLM_MODEL_PATH in config/config.py."
