[CmdletBinding()]
param(
    [string]$Model = "gemma4:e2b",
    [switch]$SkipModelCheck
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python 3.11 or newer is required and was not found on PATH."
    }

    $version = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $parts = $version.Split(".")
    if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 11)) {
        throw "Python 3.11 or newer is required; found Python $version."
    }

    if (-not (Test-Path ".venv\Scripts\python.exe")) {
        & python -m venv .venv
    }

    $venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
    & $venvPython -m pip install --upgrade pip setuptools wheel
    & $venvPython -m pip install -r requirements.lock
    & $venvPython -m pip install -e . --no-deps
    & $venvPython "examples\primary\build_demo_data.py"

    $ctxModel = ($Model -replace '[:/]', '-') + "-16k"
    if ($SkipModelCheck) { $ctxModel = $Model }
    $envContent = @"
# Local machine configuration. This file is intentionally ignored by git.
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_ORCHESTRATOR_MODEL=$ctxModel
LLM_REASONING_MODEL=$ctxModel
LLM_FAST_MODEL=$ctxModel
"@
    [System.IO.File]::WriteAllText((Join-Path $repoRoot ".env"), $envContent)

    if (-not $SkipModelCheck) {
        if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
            throw "Ollama is not installed. Install it, run 'ollama pull $Model', then rerun this script."
        }

        try {
            $models = & ollama list
        }
        catch {
            throw "Ollama is installed but not running. Start it with 'ollama serve', then rerun this script."
        }

        if (-not ($models -match [regex]::Escape($Model))) {
            throw "Ollama model '$Model' is not installed. Run 'ollama pull $Model', then rerun this script."
        }
    }

    if (-not $SkipModelCheck) {
        # Ollama's /v1 endpoint ignores per-request num_ctx, so bake a 16k variant of the model.
        $modelfile = Join-Path $env:TEMP "datamind.Modelfile"
        [System.IO.File]::WriteAllText($modelfile, "FROM $Model`nPARAMETER num_ctx 16384`n")
        & ollama create $ctxModel -f $modelfile
        if ($LASTEXITCODE -ne 0) { throw "Failed to create the 16k-context model '$ctxModel'." }
    }

    & $venvPython -m pytest -q
    & (Join-Path $repoRoot ".venv\Scripts\datamind.exe") doctor

    Write-Host ""
    Write-Host "Local setup complete. Start DataMind with:"
    Write-Host ".\.venv\Scripts\datamind.exe serve --enable-uploads --port 8080"
}
finally {
    Pop-Location
}
