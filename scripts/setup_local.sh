#!/usr/bin/env bash
# One-step local setup for Linux and macOS (mirror of scripts/setup_local.ps1).
#
# Creates .venv, installs pinned dependencies, builds the synthetic DuckDB demo data,
# bakes a 16k-context Gemma variant in Ollama, writes .env, then runs tests and diagnostics.
#
# Usage: bash scripts/setup_local.sh [ollama-model]   (default: gemma4:e2b)
#        SKIP_MODEL_CHECK=1 bash scripts/setup_local.sh   (no Ollama steps)
set -euo pipefail

MODEL="${1:-gemma4:e2b}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Python 3.11 or newer is required (found: $("$PYTHON" --version 2>&1))." >&2
  exit 1
fi

[ -x .venv/bin/python ] || "$PYTHON" -m venv .venv
VENV_PY="$REPO_ROOT/.venv/bin/python"
"$VENV_PY" -m pip install --upgrade pip setuptools wheel
"$VENV_PY" -m pip install -r requirements.lock
"$VENV_PY" -m pip install -e . --no-deps
"$VENV_PY" examples/primary/build_demo_data.py

CTX_MODEL="$(echo "$MODEL" | tr ':/' '--')-16k"
if [ "${SKIP_MODEL_CHECK:-0}" = "1" ]; then
  CTX_MODEL="$MODEL"
else
  command -v ollama >/dev/null || { echo "Ollama is not installed. Install it, run 'ollama pull $MODEL', then rerun." >&2; exit 1; }
  ollama list >/dev/null 2>&1 || { echo "Ollama is not running. Start it with 'ollama serve', then rerun." >&2; exit 1; }
  ollama list | grep -q "^${MODEL}[[:space:]]" || { echo "Model '$MODEL' is not pulled. Run 'ollama pull $MODEL', then rerun." >&2; exit 1; }
  # Ollama's /v1 endpoint ignores per-request num_ctx, so bake a 16k-context variant.
  MODELFILE="$(mktemp)"
  printf 'FROM %s\nPARAMETER num_ctx 16384\n' "$MODEL" > "$MODELFILE"
  ollama create "$CTX_MODEL" -f "$MODELFILE"
  rm -f "$MODELFILE"
fi

cat > .env <<EOF
# Local machine configuration. This file is intentionally ignored by git.
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_ORCHESTRATOR_MODEL=$CTX_MODEL
LLM_REASONING_MODEL=$CTX_MODEL
LLM_FAST_MODEL=$CTX_MODEL
EOF

"$VENV_PY" -m pytest -q
.venv/bin/datamind doctor || true

echo
echo "Local setup complete. Start DataMind with:"
echo "  .venv/bin/datamind serve --enable-uploads --port 8080"
