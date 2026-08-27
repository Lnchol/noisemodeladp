# PNMF task runner and one-click bootstrap (Windows PowerShell 5.1 compatible)
# Usage: .\pnmf.ps1 [task] [args...]
# With no task, PNMF creates/updates its local .venv and launches the web UI.

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Position = 0)]
    [string]$Task = "ui",
    [string]$Destination,
    [string]$SourceZip,
    [string]$ExtractTo,
    [switch]$Extract,
    [switch]$IncludeData,
    [switch]$ExcludeData,
    [switch]$IncludeVenv,
    [switch]$ExcludeVenv,
    [switch]$Force,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
)

$ErrorActionPreference = "Stop"
$PythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$Cli = Join-Path $PSScriptRoot "pnmf_cli.py"
$Requirements = Join-Path $PSScriptRoot "requirements.txt"
$SetupStamp = Join-Path $PSScriptRoot ".venv\.pnmf-requirements.sha256"
Set-Location -LiteralPath $PSScriptRoot

function Show-Usage {
    Write-Host "Usage: .\pnmf.ps1 [task] [args...]"
    Write-Host "       .\pnmf.ps1          - setup if needed, then launch PNMF"
    Write-Host ""
    Write-Host "Tasks:"
    Write-Host "  setup     - create/update .venv and install requirements.txt"
    Write-Host "  test      - run the pytest suite (tests/)"
    Write-Host "  validate-jet-reference - legacy-trained frozen v6.3 Jet release holdout"
    Write-Host "  validate-jet-model - evidence-gated Jet feature and learner comparison"
    Write-Host "  verify-doc29-reference - official ECAC Doc 29 Volume 3 Part 1 contract"
    Write-Host "  physics   - physics-route calibration + fleet validation"
    Write-Host "  manifest  - inspect combined v2.3 + v6.3 data provenance"
    Write-Host "  datastore - build anp_data.sqlite from staged ANP CSVs (one-time)"
    Write-Host "  predict   - predict + QA-gate + store NPD tables for a future aircraft"
    Write-Host "  zip       - adaptively package framework + data SQL into .zip archive"
    Write-Host "  export    - alias for zip"
    Write-Host "  extract   - adaptively extract framework .zip archive"
    Write-Host "  ui        - launch the local web UI (Streamlit, http://localhost:8501)"
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "[PNMF] $Message" -ForegroundColor Cyan
}

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$Path)
    $hashCommand = Get-Command Get-FileHash -ErrorAction SilentlyContinue
    if ($null -ne $hashCommand) {
        return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            return ([System.BitConverter]::ToString($sha256.ComputeHash($stream))).Replace('-', '').ToLowerInvariant()
        } finally {
            $stream.Dispose()
        }
    } finally {
        $sha256.Dispose()
    }
}

function Install-PnmfEnvironment {
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        $PyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
        if ($null -eq $PyLauncher) {
            throw "Python 3 was not found. Install Python 3 from python.org, enable the Windows 'py' launcher, and run this launcher again."
        }

        Write-Step "Creating the private Python environment (.venv)..."
        & $PyLauncher.Source -3 -m venv (Join-Path $PSScriptRoot ".venv")
        if ($LASTEXITCODE -ne 0) {
            throw "Python could not create the PNMF virtual environment (exit code $LASTEXITCODE)."
        }
    }

    $RequiredHash = Get-Sha256Hex -Path $Requirements
    $InstalledHash = if (Test-Path -LiteralPath $SetupStamp) {
        (Get-Content -LiteralPath $SetupStamp -Raw).Trim()
    } else {
        ""
    }

    if ($InstalledHash -ne $RequiredHash) {
        Write-Step "Installing PNMF dependencies into .venv (first run may take a few minutes)..."
        & $PythonExe -m pip install --disable-pip-version-check -r $Requirements
        if ($LASTEXITCODE -ne 0) {
            throw "PNMF dependency installation failed (exit code $LASTEXITCODE). Check the internet connection and run the launcher again."
        }
        Set-Content -LiteralPath $SetupStamp -Value $RequiredHash -Encoding ASCII
    }
}

function Test-PnmfUiRunning {
    try {
        $Client = New-Object System.Net.Sockets.TcpClient
        $Connect = $Client.BeginConnect("127.0.0.1", 8501, $null, $null)
        $Connected = $Connect.AsyncWaitHandle.WaitOne(250)
        if ($Connected) {
            $Client.EndConnect($Connect)
        }
        $Client.Close()
        return $Connected
    } catch {
        if ($null -ne $Client) {
            $Client.Close()
        }
        return $false
    }
}

if ([string]::IsNullOrWhiteSpace($Task)) {
    $Task = "ui"
}

if ($Task -in @("help", "-h", "--help")) {
    Show-Usage
    return
}

switch ($Task) {
    "setup" {
        Install-PnmfEnvironment
        Write-Step "PNMF is ready. Double-click Launch_PNMF.cmd or run .\pnmf.ps1"
    }
    "test" {
        Install-PnmfEnvironment
        & $PythonExe -m pytest tests/ -q
    }
    "validate-jet-reference" {
        Install-PnmfEnvironment
        & $PythonExe $Cli validate-jet-reference @Rest
    }
    "validate-jet-model" {
        Install-PnmfEnvironment
        & $PythonExe $Cli validate-jet-model @Rest
    }
    "verify-doc29-reference" {
        Install-PnmfEnvironment
        & $PythonExe $Cli verify-doc29-reference @Rest
    }
    { $_ -in "physics", "datastore", "manifest", "predict" } {
        Install-PnmfEnvironment
        & $PythonExe $Cli $Task @Rest
    }
    { $_ -in "zip", "export" } {
        $zipArgs = @{}
        if (-not [string]::IsNullOrWhiteSpace($Destination)) { $zipArgs["Destination"] = $Destination }
        if (-not [string]::IsNullOrWhiteSpace($SourceZip)) { $zipArgs["SourceZip"] = $SourceZip }
        if (-not [string]::IsNullOrWhiteSpace($ExtractTo)) { $zipArgs["ExtractTo"] = $ExtractTo }
        if ($Extract) { $zipArgs["Extract"] = $true }
        if ($IncludeData) { $zipArgs["IncludeData"] = $true }
        if ($ExcludeData) { $zipArgs["ExcludeData"] = $true }
        if ($IncludeVenv) { $zipArgs["IncludeVenv"] = $true }
        if ($ExcludeVenv) { $zipArgs["ExcludeVenv"] = $true }
        if ($Force) { $zipArgs["Force"] = $true }
        if ($null -ne $Rest -and $Rest.Count -gt 0) {
            & (Join-Path $PSScriptRoot "tools/export_framework_zip.ps1") @zipArgs @Rest
        } else {
            & (Join-Path $PSScriptRoot "tools/export_framework_zip.ps1") @zipArgs
        }
    }
    "extract" {
        $zipArgs = @{"Extract" = $true}
        if (-not [string]::IsNullOrWhiteSpace($Destination)) { $zipArgs["Destination"] = $Destination }
        if (-not [string]::IsNullOrWhiteSpace($SourceZip)) { $zipArgs["SourceZip"] = $SourceZip }
        if (-not [string]::IsNullOrWhiteSpace($ExtractTo)) { $zipArgs["ExtractTo"] = $ExtractTo }
        if ($IncludeData) { $zipArgs["IncludeData"] = $true }
        if ($ExcludeData) { $zipArgs["ExcludeData"] = $true }
        if ($IncludeVenv) { $zipArgs["IncludeVenv"] = $true }
        if ($ExcludeVenv) { $zipArgs["ExcludeVenv"] = $true }
        if ($Force) { $zipArgs["Force"] = $true }
        if ($null -ne $Rest -and $Rest.Count -gt 0) {
            & (Join-Path $PSScriptRoot "tools/export_framework_zip.ps1") @zipArgs @Rest
        } else {
            & (Join-Path $PSScriptRoot "tools/export_framework_zip.ps1") @zipArgs
        }
    }
    "ui" {
        Install-PnmfEnvironment
        $Url = "http://localhost:8501"
        if (Test-PnmfUiRunning) {
            Write-Step "PNMF is already running. Opening $Url"
            Start-Process $Url
            return
        }

        Write-Step "Starting PNMF at $Url (close this window to stop it)..."
        # Open the browser once the server is listening. Streamlit itself runs
        # headless so exactly one browser tab is opened.
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
        exit 2
    }
}

if ($null -ne $LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
