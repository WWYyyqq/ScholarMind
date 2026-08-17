#!/usr/bin/env bash
set -euo pipefail

service_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "${service_dir}/../.." && pwd)"
venv_dir="${SCHOLARMIND_VLLM_ENV:-${service_dir}/.venv}"
model_dir="${SCHOLARMIND_MODEL_DIR:-/mnt/d/ScholarMindLocalLLM/models/Qwen3-14B-AWQ-modelscope}"
gpu_memory_utilization="${SCHOLARMIND_LLM_GPU_MEMORY_UTILIZATION:-0.75}"

if [[ ! -x "${venv_dir}/bin/vllm" ]]; then
  echo "vLLM is not installed in ${venv_dir}." >&2
  echo "Run: uv venv --python 3.11 ${venv_dir}" >&2
  echo "Then: UV_CACHE_DIR=/mnt/d/ScholarMindLocalLLM/uv-cache uv pip install --python ${venv_dir}/bin/python -r ${service_dir}/requirements.txt" >&2
  exit 1
fi

if [[ ! -f "${model_dir}/config.json" ]]; then
  echo "Model not found at ${model_dir}." >&2
  echo "Set SCHOLARMIND_MODEL_DIR to the downloaded Qwen3-14B-AWQ directory." >&2
  exit 1
fi

mkdir -p \
  "${project_root}/.cache/vllm" \
  "${service_dir}/.cache/flashinfer" \
  "${service_dir}/tmp"
chmod 700 "${service_dir}/tmp"

export PATH="${venv_dir}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export TMPDIR="${service_dir}/tmp"
export VLLM_CACHE_ROOT="${project_root}/.cache/vllm"
export FLASHINFER_WORKSPACE_BASE="${service_dir}"
export VLLM_USE_V2_MODEL_RUNNER=0
export VLLM_USE_FLASHINFER_SAMPLER=0
export NO_PROXY="${NO_PROXY:+${NO_PROXY},}127.0.0.1,localhost,::1"
export no_proxy="${no_proxy:+${no_proxy},}127.0.0.1,localhost,::1"

exec "${venv_dir}/bin/vllm" serve "${model_dir}" \
  --served-model-name qwen3-14b-local \
  --host ::1 \
  --port 8000 \
  --dtype half \
  --quantization awq \
  --max-model-len 16384 \
  --gpu-memory-utilization "${gpu_memory_utilization}" \
  --default-chat-template-kwargs '{"enable_thinking":false}' \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
