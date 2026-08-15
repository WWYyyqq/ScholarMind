#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "${script_dir}/.." && pwd)"
environment_file="${SCHOLARMIND_ENV_FILE:-${project_root}/.env.postgres}"
langgraph_port="${SCHOLARMIND_LANGGRAPH_PORT:-2024}"

if [[ ! -f "${environment_file}" ]]; then
  echo "Missing project environment file: ${environment_file}" >&2
  echo "Copy .env.postgres.example to .env.postgres and set a local password." >&2
  exit 1
fi

if [[ ! -x "${project_root}/.venv/bin/langgraph" ]]; then
  echo "Missing project application environment at ${project_root}/.venv." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${environment_file}"
set +a

export SCHOLARMIND_EMBEDDING_MODEL="${SCHOLARMIND_EMBEDDING_MODEL:-qwen3-embedding-0.6b-local}"
export SCHOLARMIND_EMBEDDING_DIMENSION="${SCHOLARMIND_EMBEDDING_DIMENSION:-1024}"
export SCHOLARMIND_EMBEDDING_BASE_URL="${SCHOLARMIND_EMBEDDING_BASE_URL:-http://[::1]:8001/v1}"
export SCHOLARMIND_EMBEDDING_API_KEY="${SCHOLARMIND_EMBEDDING_API_KEY:-local-not-required}"
export LANGSMITH_TRACING="${LANGSMITH_TRACING:-false}"

exec "${project_root}/.venv/bin/langgraph" dev \
  --config "${project_root}/langgraph.local.json" \
  --port "${langgraph_port}" \
  --no-browser \
  --allow-blocking \
  --n-jobs-per-worker 1
