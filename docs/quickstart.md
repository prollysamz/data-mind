# DataMind Quickstart Guide

This guide walks you through setting up DataMind from a clean repository.

## Prerequisites

- Python 3.11+
- Git
- Local Ollama with a Gemma model (`gemma4:e2b` by default) OR an OpenAI-compatible endpoint serving Gemma.
- (Optional) Snowflake account credentials with read-only access.

---

## 1. Setup Virtual Environment & Install

### Windows (PowerShell)

```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.venv\Scripts\Activate.ps1

# Upgrade pip
python -m pip install --upgrade pip

# Install in editable mode with dev extras
pip install -e ".[dev]"

# Generate the deterministic local database used by the default configuration
python examples/primary/build_demo_data.py
```

For a one-command Windows setup, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_local.ps1
```

*Note for PowerShell:* If script execution is restricted on your system, run:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
```

### Linux / macOS (bash / zsh)

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip
python -m pip install --upgrade pip

# Install in editable mode with dev extras
pip install -e ".[dev]"
```

---

## 2. Configure Secrets and Settings

Copy `.env.example` to `.env`:
```powershell
# PowerShell
Copy-Item .env.example .env

# Bash
cp .env.example .env
```

Edit `.env` to set your credentials. Never commit `.env` (it is in `.gitignore`).

---

## 3. Verify Setup

Run the verification scripts:

```bash
# Verify local Ollama model
python scripts/check_local_model.py

# Verify LLM capabilities (tools, JSON mode, round-trip)
python scripts/check_llm.py

# Verify Snowflake connectivity (if credentials provided)
python scripts/check_snowflake.py

# Verify test suite
pytest
```

---

## 4. CLI Verification

Check that the CLI entrypoint works:

```bash
datamind --help
```

---

## 5. Local Ollama Model Configuration

The model must be a Gemma variant that supports OpenAI-compatible tool calls. The setup script writes the selected model to the ignored `.env` file. To use the default:

```bash
ollama pull gemma4:e2b
python scripts/check_llm.py --model gemma4:e2b
```

**Context window (required).** Ollama's OpenAI-compatible endpoint ignores per-request `num_ctx`, so the default 4,096-token window cuts off multi-step answers (`finish_reason=length`). Bake a 16k variant (the Windows setup script does this for you):

```bash
printf 'FROM gemma4:e2b
PARAMETER num_ctx 16384
' > Modelfile
ollama create gemma4-e2b-16k -f Modelfile
```

Then use `LLM_ORCHESTRATOR_MODEL=gemma4-e2b-16k` and `LLM_FAST_MODEL=gemma4-e2b-16k` (or export `OLLAMA_CONTEXT_LENGTH=16384` before `ollama serve`). `datamind doctor` flags a missing context setting. Validate tool calling and JSON output with `scripts/check_llm.py`. Thinking mode is off by default for local servers (`llm.thinking: false`).
