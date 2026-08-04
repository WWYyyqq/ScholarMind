#!/usr/bin/env bash
set -euo pipefail

embedding_service_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
embedding_project_root="$(cd -- "${embedding_service_dir}/../.." && pwd)"
embedding_vllm_env="${SCHOLARMIND_VLLM_ENV:-${embedding_project_root}/services/local-llm/.venv}"
embedding_model_dir="${SCHOLARMIND_EMBEDDING_MODEL_DIR:-/mnt/d/ScholarMindLocalLLM/models/Qwen3-Embedding-0.6B-modelscope}"
embedding_port="${SCHOLARMIND_EMBEDDING_PORT:-8001}"
embedding_gpu_utilization="${SCHOLARMIND_EMBEDDING_GPU_MEMORY_UTILIZATION:-0.15}"
embedding_tmpdir="${SCHOLARMIND_EMBEDDING_TMPDIR:-/tmp/scholarmind-embedding-${UID}}"

if [[ ! -x "${embedding_vllm_env}/bin/vllm" ]]; then
  echo "vLLM is not installed in ${embedding_vllm_env}." >&2
  echo "Create the project inference environment under services/local-llm first." >&2
  exit 1
fi

if [[ ! -f "${embedding_model_dir}/config.json" ]]; then
  echo "Embedding model not found at ${embedding_model_dir}." >&2
  echo "Run: ${embedding_vllm_env}/bin/python ${embedding_service_dir}/download_model.py" >&2
  exit 1
fi

mkdir -p \
  "${embedding_project_root}/.cache/vllm-embedding" \
  "${embedding_tmpdir}"
chmod 700 "${embedding_tmpdir}"

export TMPDIR="${embedding_tmpdir}"
export VLLM_CACHE_ROOT="${embedding_project_root}/.cache/vllm-embedding"
export NO_PROXY="${NO_PROXY:+${NO_PROXY},}127.0.0.1,localhost,::1"
export no_proxy="${no_proxy:+${no_proxy},}127.0.0.1,localhost,::1"

exec "${embedding_vllm_env}/bin/vllm" serve "${embedding_model_dir}" \
  --served-model-name qwen3-embedding-0.6b-local \
  --runner pooling \
  --convert embed \
  --host ::1 \
  --port "${embedding_port}" \
  --dtype half \
  --max-model-len 4096 \
  --gpu-memory-utilization "${embedding_gpu_utilization}"
