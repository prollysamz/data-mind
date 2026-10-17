# DataMind Quickstart Guide

This guide walks you through setting up DataMind from a clean repository.

## Prerequisites

- Python 3.11+
- Git
- Local Ollama with `gemma4:e2b` (for offline testing) OR Amazon Bedrock / OpenAI-compatible endpoint with Gemma models.
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

## 5. Local Ollama Context Window Configuration

By default, Ollama initializes models with a 2,048 or 4,096 token context window, which can cause multi-turn analytical reasoning to truncate (`finish_reason=length`). DataMind automatically passes `{"options": {"num_ctx": 16384}}` in its API requests, but for optimal local performance, configure the 16k context window directly:

```bash
# Export existing model definition
ollama show gemma4:e2b --modelfile > Modelfile

# Add the 16k context parameter:
# PARAMETER num_ctx 16384

# Re-create the model definition
ollama create gemma4:e2b -f Modelfile
```
