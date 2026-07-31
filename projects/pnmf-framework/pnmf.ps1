# PNMF task runner (Windows PowerShell 5.1 compatible)
# Usage: .\pnmf.ps1 <task> [args...] — thin wrapper around pnmf_cli.py

param(
    [string]$Task,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)

$PythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$Cli = Join-Path $PSScriptRoot "pnmf_cli.py"
Set-Location -LiteralPath $PSScriptRoot

function Show-Usage {
    Write-Host "Usage: .\pnmf.ps1 <task> [args...]"
    Write-Host ""
    Write-Host "Tasks:"
    Write-Host "  setup     - create .venv and install requirements.txt"
    Write-Host "  test      - run the pytest suite (tests/)"
    Write-Host "  validate  - LOO validation (default: all 8 metric:mode pairs)"
    Write-Host "  validate-model - current grouped + temporal ET/RF validation"
    Write-Host "  validate-jet-reference - legacy-trained frozen v6.3 Jet release holdout"
    Write-Host "  physics   - physics-route calibration + fleet validation"
    Write-Host "  demo      - end-to-end demo"
    Write-Host "  compare   - LOO bake-off of all candidate models"
    Write-Host "  manifest  - inspect combined v2.3 + v6.3 data provenance"
    Write-Host "  subs      - external check vs the 19.5k-aircraft substitution table"
    Write-Host "  datastore - build anp_data.sqlite from staged ANP CSVs (one-time)"
    Write-Host "  predict   - predict + QA-gate + store NPD tables for a future aircraft"
    Write-Host "  ui        - launch the local web UI (Streamlit, http://localhost:8501)"
}

function Assert-Venv {
    if (-not (Test-Path $PythonExe)) {
        throw "$PythonExe not found. Run '.\pnmf.ps1 setup' first."
    }
}

if ([string]::IsNullOrEmpty($Task)) {
    Show-Usage
    return
}

switch ($Task) {
    "setup" {
        py -3 -m venv (Join-Path $PSScriptRoot ".venv")
        if ($?) { & $PythonExe -m pip install -r (Join-Path $PSScriptRoot "requirements.txt") }
    }
    "test" {
        Assert-Venv
        & $PythonExe -m pytest tests/ -q
    }
    "validate" {
        Assert-Venv
        if ($Rest) { & $PythonExe $Cli validate @Rest }
        else { & $PythonExe $Cli validate SEL:D SEL:A EPNL:D EPNL:A LAmax:D LAmax:A PNLTM:D PNLTM:A }
    }
    "validate-model" {
        Assert-Venv
        & $PythonExe $Cli validate-model @Rest
    }
    "validate-jet-reference" {
        Assert-Venv
        & $PythonExe $Cli validate-jet-reference @Rest
    }
    "subs" {
        Assert-Venv
        if ($Rest) { & $PythonExe $Cli subs @Rest }
        else { & $PythonExe $Cli subs "03_data/anp_aircraft_substitutions_-_jets_heavy_props_22022018_.xlsx" }
    }
    { $_ -in "physics", "demo", "compare", "datastore", "manifest", "predict" } {
        Assert-Venv
        & $PythonExe $Cli $Task @Rest
    }
    "ui" {
        Assert-Venv
        $Url = "http://localhost:8501"
        # open the browser once the server is actually listening, so the tab
        # doesn't load before the port is up. Runs in a background job; we
        # pass --server.headless true so Streamlit doesn't also open one.
        Start-Job -ArgumentList $Url {
            param($u)
            for ($i = 0; $i -lt 60; $i++) {
                try {
                    $c = New-Object System.Net.Sockets.TcpClient
                    $c.Connect("localhost", 8501); $c.Close()
                    Start-Process $u; break
                } catch { Start-Sleep -Milliseconds 500 }
            }
        } | Out-Null
        & $PythonExe -m streamlit run (Join-Path $PSScriptRoot "pnmf_ui.py") `
            --server.headless true @Rest
    }
    default {
        Write-Host "Unknown task: $Task"
        Write-Host ""
        Show-Usage
    }
}
