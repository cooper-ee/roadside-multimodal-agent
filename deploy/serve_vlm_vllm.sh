#!/usr/bin/env bash
set -euo pipefail
# Candidate only: check installed vLLM/model/GPU support before benchmarking.
vllm serve "${MODEL_ID:-Qwen/Qwen3-VL-2B-Instruct}"   --served-model-name local-vlm --host 127.0.0.1 --port 8002   --dtype auto --max-model-len 2048 --max-num-seqs 1   --gpu-memory-utilization 0.80 --enforce-eager   --limit-mm-per-prompt '{"image":1}'
