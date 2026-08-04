[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Position = 0)]
    [string]$Destination,
    [string]$SourceZip,
    [string]$ExtractTo,
    [switch]$Extract,
    [switch]$IncludeData,
    [switch]$ExcludeData,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$packageName = 'pnmf-framework'
$topLevelName = 'pnmf-framework'

# --- ADAPTIVE EXTRACTOR: EXTRACT MODE ---
if ($Extract -or (-not [string]::IsNullOrWhiteSpace($ExtractTo))) {
    $zipPath = if (-not [string]::IsNullOrWhiteSpace($SourceZip)) { $SourceZip } elseif (-not [string]::IsNullOrWhiteSpace($Destination)) { $Destination } else { "" }
    if ([string]::IsNullOrWhiteSpace($zipPath)) {
        $candidates = @(
            (Join-Path $projectRoot "$packageName.zip"),
            (Join-Path (Split-Path -Parent $projectRoot) "$packageName.zip")
        )
        foreach ($c in $candidates) {
            if (Test-Path -LiteralPath $c -PathType Leaf) {
                $zipPath = $c
                break
            }
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($zipPath) -and -not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
        $parentRoot = Split-Path -Parent $projectRoot
        $rawCandidates = @(
            $zipPath,
            (Join-Path $projectRoot $zipPath),
            (Join-Path $parentRoot $zipPath)
        )
        foreach ($cand in $rawCandidates) {
            try {
                $norm = [System.IO.Path]::GetFullPath($cand)
                if (Test-Path -LiteralPath $norm -PathType Leaf) {
                    $zipPath = $norm
                    break
                }
            } catch {}
        }
    }

    if ([string]::IsNullOrWhiteSpace($zipPath) -or -not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
        throw "Adaptive Extractor [Extract Mode]: Source ZIP file not found: '$zipPath'"
    }

    $zipFullPath = [System.IO.Path]::GetFullPath($zipPath)
    $targetDir = if (-not [string]::IsNullOrWhiteSpace($ExtractTo)) {
        [System.IO.Path]::GetFullPath($ExtractTo)
    } else {
        Join-Path (Split-Path -Parent $zipFullPath) ($packageName + "_extracted")
    }

    Write-Host "[Adaptive Extractor] Extracting archive: $zipFullPath" -ForegroundColor Cyan
    Write-Host "[Adaptive Extractor] Target destination: $targetDir" -ForegroundColor Cyan

    if (-not (Test-Path -LiteralPath $targetDir -PathType Container)) {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    }

    if ($PSCmdlet.ShouldProcess($targetDir, "Extract $zipFullPath to $targetDir")) {
        Expand-Archive -LiteralPath $zipFullPath -DestinationPath $targetDir -Force
        
        Write-Host "[Adaptive Extractor] Extraction complete. Performing adaptive inspection..." -ForegroundColor Green
        
        $hasSqlite = Test-Path -LiteralPath (Join-Path $targetDir "anp_data.sqlite") -PathType Leaf
        if (-not $hasSqlite) {
            $nestedSqlite = Get-ChildItem -LiteralPath $targetDir -Recurse -Filter "anp_data.sqlite" -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($null -ne $nestedSqlite) { $hasSqlite = $true }
        }

        if ($hasSqlite) {
            Write-Host "  [+] Data SQL Database: Present (anp_data.sqlite)" -ForegroundColor Green
        } else {
            Write-Host "  [-] Data SQL Database: Not present (code-only archive)" -ForegroundColor Yellow
        }

        $hasDataDir = Test-Path -LiteralPath (Join-Path $targetDir "03_data") -PathType Container
        if (-not $hasDataDir) {
            $nestedData = Get-ChildItem -LiteralPath $targetDir -Recurse -Filter "03_data" -ErrorAction SilentlyContinue | Where-Object { $_.PSIsContainer } | Select-Object -First 1
            if ($null -ne $nestedData) { $hasDataDir = $true }
        }

        if ($hasDataDir) {
            Write-Host "  [+] Raw Data Corpus: Present (03_data)" -ForegroundColor Green
        } else {
            Write-Host "  [-] Raw Data Corpus: Not present" -ForegroundColor Yellow
        }

        return
    }
    return
}

# --- ADAPTIVE EXTRACTOR: PACKAGING / EXPORT MODE ---
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path (Split-Path -Parent $projectRoot) "$packageName.zip"
}

$destinationPath = [System.IO.Path]::GetFullPath($Destination)
if ([System.IO.Path]::GetExtension($destinationPath) -ne '.zip') {
    throw "Destination must end in .zip: $destinationPath"
}

$rootPrefix = $projectRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar

$files = [System.Collections.Generic.List[string]]::new()

# Standard allowlisted root & tool files
$allowlist = @('Launch_PNMF.cmd', 'pnmf_cli.py', 'pnmf_ui.py', 'pnmf.ps1', 'requirements.txt', 'README.md', 'HOW_TO_USE.txt', 'AGENTS.md', 'tools/export_framework_zip.ps1')
foreach ($relative in $allowlist) {
    $path = Join-Path $projectRoot $relative
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $files.Add($path)
    }
}

# Code and test directories
foreach ($folder in @('pnmf', 'tests', 'tools')) {
    $folderPath = Join-Path $projectRoot $folder
    if (Test-Path -LiteralPath $folderPath -PathType Container) {
        Get-ChildItem -LiteralPath $folderPath -Recurse -File |
            Where-Object { $_.Extension -in @('.py', '.ps1', '.cmd', '.txt', '.md', '.json', '.yml', '.yaml') } |
            Sort-Object FullName |
            ForEach-Object { $files.Add($_.FullName) }
    }
}

# ADAPTIVE DATA SQL & CORPUS INCLUSION
$shouldIncludeData = (-not $ExcludeData)
if ($shouldIncludeData) {
    # 1. Check for SQLite Datastore
    $sqlitePath = Join-Path $projectRoot "anp_data.sqlite"
    if (Test-Path -LiteralPath $sqlitePath -PathType Leaf) {
        $files.Add($sqlitePath)
        Write-Host "[Adaptive Extractor] Including Data SQL database: anp_data.sqlite" -ForegroundColor Cyan
    }

    # 2. Check for 03_data directory
    $dataDir = Join-Path $projectRoot "03_data"
    if (Test-Path -LiteralPath $dataDir -PathType Container) {
        Get-ChildItem -LiteralPath $dataDir -Recurse -File |
            Sort-Object FullName |
            ForEach-Object { $files.Add($_.FullName) }
        Write-Host "[Adaptive Extractor] Including raw data corpus: 03_data" -ForegroundColor Cyan
    }
} else {
    Write-Host "[Adaptive Extractor] Excluding data SQL and corpus files (-ExcludeData specified)" -ForegroundColor Yellow
}

# Filter out duplicate entries and the destination zip itself if inside project root
$uniqueFiles = [System.Collections.Generic.List[string]]::new()
foreach ($f in $files) {
    $full = [System.IO.Path]::GetFullPath($f)
    if ($full -eq $destinationPath) { continue }
    if (-not $uniqueFiles.Contains($full)) {
        $uniqueFiles.Add($full)
    }
}

$relativeManifest = $uniqueFiles |
    ForEach-Object { $_.Substring($rootPrefix.Length).Replace('\', '/') } |
    Sort-Object

Write-Host "PNMF adaptive framework export manifest ($($relativeManifest.Count) files):"
$relativeManifest | ForEach-Object { Write-Host "  $_" }
Write-Host "Destination: $destinationPath"

if ($WhatIfPreference) {
    Write-Host 'WhatIf: archive was not created.'
    return
}

if (Test-Path -LiteralPath $destinationPath -PathType Leaf) {
    if (-not $Force) {
        throw "Destination already exists. Re-run with -Force to replace only this archive: $destinationPath"
    }
}

$destinationParent = Split-Path -Parent $destinationPath
if (-not (Test-Path -LiteralPath $destinationParent -PathType Container)) {
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
}

$stageRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("pnmf-export-" + [guid]::NewGuid().ToString('N'))
try {
    $stageTop = Join-Path $stageRoot $topLevelName
    New-Item -ItemType Directory -Path $stageTop -Force | Out-Null

    foreach ($source in $uniqueFiles) {
        $relative = $source.Substring($rootPrefix.Length)
        $target = Join-Path $stageTop $relative
        $targetParent = Split-Path -Parent $target
        New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
        Copy-Item -LiteralPath $source -Destination $target -Force
    }

    if ($PSCmdlet.ShouldProcess($destinationPath, 'Create PNMF framework archive')) {
        if (Test-Path -LiteralPath $destinationPath) {
            Remove-Item -LiteralPath $destinationPath -Force
        }
        Compress-Archive -LiteralPath $stageTop -DestinationPath $destinationPath -CompressionLevel Optimal
        $archive = Get-Item -LiteralPath $destinationPath
        Write-Host "Created $($archive.FullName) ($([math]::Round($archive.Length / 1KB, 1)) KiB)." -ForegroundColor Green
        Write-Host "Included $($relativeManifest.Count) adaptive files under $topLevelName/." -ForegroundColor Green
    }
}
finally {
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
}
