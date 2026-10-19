#!/usr/bin/env bash
set -euo pipefail
# llama-server must already be built/installed. -hf downloads model/projector.
# Upstream lists SmolVLM-500M as supported. This is an alternative model, not Qwen3-VL.
llama-server -hf "${MODEL_ID:-ggml-org/SmolVLM-500M-Instruct-GGUF}"   --alias local-vlm --host 127.0.0.1 --port 8002 -c 2048 -ngl 99
