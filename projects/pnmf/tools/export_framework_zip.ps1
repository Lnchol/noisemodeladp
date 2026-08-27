[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [Parameter(Position = 0)]
    [string]$Destination,
    [string]$SourceZip,
    [string]$ExtractTo,
    [switch]$Extract,
    [switch]$IncludeData,
    [switch]$ExcludeData,
    [switch]$IncludeVenv,
    [switch]$ExcludeVenv,
    [switch]$IncludeTests,
    [switch]$IncludeDocs,
    [switch]$IncludeTools,
    [switch]$Force,
    [string]$PackageName = 'pnmf-framework',
    [string]$TopLevelName = 'pnmf-framework',
    [string]$ProjectRoot,
    [string[]]$AdditionalFiles = @(),
    [string[]]$ExcludePatterns = @()
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- PROJECT ROOT RESOLUTION ---
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
} else {
    $projectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path
}

$packageName = if (-not [string]::IsNullOrWhiteSpace($PackageName)) { $PackageName } else { 'pnmf-framework' }
$topLevelName = if (-not [string]::IsNullOrWhiteSpace($TopLevelName)) { $TopLevelName } else { 'pnmf-framework' }

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

function Test-ValidZipArchive {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
        $archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
        try {
            return ($archive.Entries.Count -gt 0)
        } finally {
            $archive.Dispose()
        }
    } catch {
        return $false
    }
}

# --- ADAPTIVE EXTRACTOR: EXTRACT MODE ---
if ($Extract -or (-not [string]::IsNullOrWhiteSpace($ExtractTo))) {
    $zipPath = if (-not [string]::IsNullOrWhiteSpace($SourceZip)) { $SourceZip } elseif (-not [string]::IsNullOrWhiteSpace($Destination)) { $Destination } else { "" }
    if ([string]::IsNullOrWhiteSpace($zipPath)) {
        $candidates = @(
            (Join-Path $projectRoot "$packageName.zip"),
            (Join-Path (Split-Path -Parent $projectRoot) "$packageName.zip"),
            (Join-Path (Get-Location).Path "$packageName.zip")
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
            (Join-Path $parentRoot $zipPath),
            (Join-Path (Get-Location).Path $zipPath)
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
        
        # Adaptive discovery in extracted folder
        $hasSqlite = Test-Path -LiteralPath (Join-Path $targetDir "anp_data.sqlite") -PathType Leaf
        if (-not $hasSqlite) {
            $nestedSqlite = @(Get-ChildItem -LiteralPath $targetDir -Recurse -Filter "*.sqlite" -ErrorAction SilentlyContinue)
            if ($nestedSqlite.Count -gt 0) { $hasSqlite = $true }
        }

        if ($hasSqlite) {
            Write-Host "  [+] Data SQL Database: Present (anp_data.sqlite)" -ForegroundColor Green
        } else {
            Write-Host "  [-] Data SQL Database: Not present (code-only archive)" -ForegroundColor Yellow
        }

        $hasDataDir = Test-Path -LiteralPath (Join-Path $targetDir "03_data") -PathType Container
        if (-not $hasDataDir) {
            $nestedData = @(Get-ChildItem -LiteralPath $targetDir -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.PSIsContainer -and ($_.Name -in @('03_data', 'data', 'raw_data')) })
            if ($nestedData.Count -gt 0) { $hasDataDir = $true }
        }

        if ($hasDataDir) {
            Write-Host "  [+] Raw Data Corpus: Present" -ForegroundColor Green
        } else {
            Write-Host "  [-] Raw Data Corpus: Not present" -ForegroundColor Yellow
        }

        # Check Python Virtual Environment
        $hasVenv = Test-Path -LiteralPath (Join-Path $targetDir ".venv") -PathType Container
        if (-not $hasVenv) {
            $nestedVenv = @(Get-ChildItem -LiteralPath $targetDir -Recurse -ErrorAction SilentlyContinue |
                Where-Object { $_.PSIsContainer -and ($_.Name -in @('.venv', 'venv')) })
            if ($nestedVenv.Count -gt 0) { $hasVenv = $true }
        }
        if ($hasVenv) {
            Write-Host "  [+] Python Virtual Environment: Present (.venv)" -ForegroundColor Green
        }

        # Check Python package and CLI
        $foundCli = @(Get-ChildItem -LiteralPath $targetDir -Recurse -Filter "pnmf_cli.py" -ErrorAction SilentlyContinue)
        if ($foundCli.Count -gt 0) {
            Write-Host "  [+] Framework Entry Points: Present ($($foundCli[0].Name))" -ForegroundColor Green
        }

        # Check Manifest verification if PACKAGE_MANIFEST.txt exists
        $foundManifest = @(Get-ChildItem -LiteralPath $targetDir -Recurse -Filter "PACKAGE_MANIFEST.txt" -ErrorAction SilentlyContinue)
        if ($foundManifest.Count -gt 0) {
            $manifestFile = $foundManifest[0]
            Write-Host "  [+] Integrity Manifest: Present ($($manifestFile.FullName))" -ForegroundColor Green
            $manifestBaseDir = $manifestFile.DirectoryName
            $manifestContent = @(Get-Content -LiteralPath $manifestFile.FullName -ErrorAction SilentlyContinue)
            $verifiedCount = 0
            $totalInManifest = 0
            $mismatches = 0
            foreach ($line in $manifestContent) {
                if ($line -match '^([a-fA-F0-9]{64})\s+(.+)$') {
                    $expectedHash = $Matches[1].ToLowerInvariant()
                    $relPath = $Matches[2].Trim()
                    $checkFile = Join-Path $manifestBaseDir ($relPath.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
                    $totalInManifest++
                    if (Test-Path -LiteralPath $checkFile -PathType Leaf) {
                        $actualHash = Get-Sha256Hex -Path $checkFile
                        if ($actualHash -eq $expectedHash) {
                            $verifiedCount++
                        } else {
                            $mismatches++
                            Write-Warning "Manifest SHA256 mismatch for $relPath"
                        }
                    } else {
                        $mismatches++
                        Write-Warning "Manifest file missing: $relPath"
                    }
                }
            }
            if ($totalInManifest -gt 0 -and $mismatches -eq 0) {
                Write-Host "  [+] Verification: All $verifiedCount files match manifest checksums." -ForegroundColor Green
            } elseif ($mismatches -gt 0) {
                Write-Warning "  [!] Verification: $mismatches / $totalInManifest files had issues."
            }
        }

        return
    }
    return
}

# --- SOLELY CLEAN FRAMEWORK EXPORTER: PACKAGING MODE ---
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path (Split-Path -Parent $projectRoot) "$packageName.zip"
}

$destinationPath = [System.IO.Path]::GetFullPath($Destination)
if ([System.IO.Path]::GetExtension($destinationPath) -ne '.zip') {
    throw "Destination must end in .zip: $destinationPath"
}

$rootPrefix = $projectRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
$files = [System.Collections.Generic.List[string]]::new()

# Global strictly excluded directory names (AI tools, agents, caches, tools folder, outputs)
$excludedDirNames = @(
    'tools', '.git', '.pytest_cache', '__pycache__',
    'output', 'outputs', 'tmp', 'temp', '.idea', '.vscode', '.claude',
    '.gemini', '.agents', '.codex', '.cursor', '.obsidian', 'projects', 'dist', 'build',
    '.github'
)

# If Venv is not included, add .venv/venv to excluded folders
$shouldIncludeVenv = ($IncludeVenv -and -not $ExcludeVenv)
if (-not $shouldIncludeVenv) {
    $excludedDirNames += @('.venv', 'venv', 'env')
}

# Global strictly excluded file extensions and AI / workspace rule files
$excludedFileExtensions = @('.pyc', '.pyo', '.pyd', '.swp', '.bak', '.log', '.tmp', '.DS_Store')
$excludedFileNames = @(
    'Thumbs.db', 'serdp09_reference.py', 'AGENTS.md', 'GEMINI.md', 'CLAUDE.md',
    '.cursorrules', '.gitignore', '.gitattributes'
)

function Test-IsPathExcluded {
    param([Parameter(Mandatory = $true)][string]$FullPath)
    $normalized = $FullPath.Replace('/', '\')
    $rel = if ($normalized.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        $normalized.Substring($rootPrefix.Length)
    } else {
        $normalized
    }
    $parts = $rel.Split([System.IO.Path]::DirectorySeparatorChar)

    foreach ($p in $parts) {
        if ($p -in $excludedDirNames) {
            return $true
        }
    }

    $fileName = [System.IO.Path]::GetFileName($FullPath)
    $ext = [System.IO.Path]::GetExtension($FullPath)

    if ($ext -in $excludedFileExtensions) {
        return $true
    }
    if ($fileName -in $excludedFileNames) {
        return $true
    }
    if ($FullPath -eq $destinationPath) {
        return $true
    }

    $customPatterns = @($ExcludePatterns)
    foreach ($customPattern in $customPatterns) {
        if (-not [string]::IsNullOrWhiteSpace($customPattern)) {
            if ($rel -like $customPattern -or $fileName -like $customPattern) {
                return $true
            }
        }
    }

    return $false
}

# 1. CORE FRAMEWORK RUNTIME ENTRY POINTS & USER DOCS
# Discovers root framework runtime scripts and configurations adaptively:
# - Launchers: Launch_PNMF.cmd, pnmf.ps1
# - Framework entry points: pnmf_cli.py, pnmf_ui.py (and any *_cli.py, *_ui.py)
# - Requirements and configs: requirements*.txt, pyproject.toml, setup.cfg, environment.yml
# - User documentation: README.md, HOW_TO_USE.txt, LICENSE*
$rootCount = 0
$rootCandidates = @(Get-ChildItem -LiteralPath $projectRoot -File -ErrorAction SilentlyContinue)
foreach ($item in $rootCandidates) {
    if (Test-IsPathExcluded -FullPath $item.FullName) { continue }
    
    $name = $item.Name
    $ext = $item.Extension.ToLowerInvariant()

    $isScript = $ext -in @('.cmd', '.bat', '.ps1', '.sh')
    $isPythonEntryPoint = ($name -match '^(pnmf_|main|app).*\.py$') -or ($name -in @('pnmf_cli.py', 'pnmf_ui.py'))
    $isDoc = ($name -in @('README.md', 'HOW_TO_USE.txt')) -or ($name -match '^(README|HOW_TO_USE|LICENSE|NOTICE)')
    $isConfig = ($name -match '^requirements.*\.txt$') -or ($name -in @('pyproject.toml', 'setup.py', 'setup.cfg', 'environment.yml'))

    if ($isScript -or $isPythonEntryPoint -or $isDoc -or $isConfig) {
        $files.Add($item.FullName)
        $rootCount++
    }
}

# Add .streamlit configuration if present
$streamlitConfig = Join-Path $projectRoot '.streamlit/config.toml'
if (Test-Path -LiteralPath $streamlitConfig -PathType Leaf) {
    $files.Add((Resolve-Path -LiteralPath $streamlitConfig).Path)
    $rootCount++
}

# 2. FRAMEWORK PACKAGE & CALIBRATION ASSETS
# Discovers 'pnmf' package and any submodules / package directories with __init__.py,
# including all python runtime code and JSON/YAML/preset calibration assets.
$packageDirs = [System.Collections.Generic.List[string]]::new()
$pnmfDefaultPath = Join-Path $projectRoot 'pnmf'
if (Test-Path -LiteralPath $pnmfDefaultPath -PathType Container) {
    $packageDirs.Add($pnmfDefaultPath)
}

$allSubDirs = @(Get-ChildItem -LiteralPath $projectRoot -Directory -ErrorAction SilentlyContinue)
foreach ($d in $allSubDirs) {
    if (Test-IsPathExcluded -FullPath $d.FullName) { continue }
    if ($d.FullName -eq $pnmfDefaultPath) { continue }
    if (Test-Path -LiteralPath (Join-Path $d.FullName '__init__.py') -PathType Leaf) {
        $packageDirs.Add($d.FullName)
    }
}

$packageCount = 0
$packageAllowedExtensions = @('.py', '.json', '.yaml', '.yml', '.toml', '.csv', '.tsv', '.txt', '.sql', '.ini', '.dat')
foreach ($pkgDir in $packageDirs) {
    @(Get-ChildItem -LiteralPath $pkgDir -Recurse -File -ErrorAction SilentlyContinue) | ForEach-Object {
        if (-not (Test-IsPathExcluded -FullPath $_.FullName)) {
            $ext = $_.Extension.ToLowerInvariant()
            if ($ext -in $packageAllowedExtensions) {
                $files.Add($_.FullName)
                $packageCount++
            }
        }
    }
}

# Adaptive validation for physics calibration artifact or presets
$calibrationArtifacts = @(Get-ChildItem -LiteralPath $pnmfDefaultPath -Filter "physics_calibration*.json" -ErrorAction SilentlyContinue)
if ($calibrationArtifacts.Count -eq 0) {
    $anyJson = @(Get-ChildItem -LiteralPath $pnmfDefaultPath -Filter "*.json" -ErrorAction SilentlyContinue)
    if ($anyJson.Count -eq 0) {
        Write-Warning "No physics calibration JSON artifact found in $pnmfDefaultPath."
    }
}

# 3. OPTIONAL: Tools Suite (Off by default as requested)
if ($IncludeTools) {
    $toolsDir = Join-Path $projectRoot 'tools'
    if (Test-Path -LiteralPath $toolsDir -PathType Container) {
        @(Get-ChildItem -LiteralPath $toolsDir -Recurse -File -ErrorAction SilentlyContinue) | ForEach-Object {
            $ext = $_.Extension.ToLowerInvariant()
            if ($ext -in @('.ps1', '.py', '.mjs', '.js', '.sh', '.cmd', '.bat', '.json', '.md', '.txt')) {
                $files.Add($_.FullName)
            }
        }
    }
}

# 4. OPTIONAL: Tests & Documentation (off by default)
if ($IncludeTests) {
    $testsDir = Join-Path $projectRoot 'tests'
    if (Test-Path -LiteralPath $testsDir -PathType Container) {
        @(Get-ChildItem -LiteralPath $testsDir -Recurse -File -ErrorAction SilentlyContinue) | ForEach-Object {
            if (-not (Test-IsPathExcluded -FullPath $_.FullName)) {
                $files.Add($_.FullName)
            }
        }
    }
}

if ($IncludeDocs) {
    $docsDir = Join-Path $projectRoot 'docs'
    if (Test-Path -LiteralPath $docsDir -PathType Container) {
        @(Get-ChildItem -LiteralPath $docsDir -Recurse -File -ErrorAction SilentlyContinue) | ForEach-Object {
            if (-not (Test-IsPathExcluded -FullPath $_.FullName)) {
                $files.Add($_.FullName)
            }
        }
    }
}

# 5. USER SPECIFIED ADDITIONAL FILES
$extraList = @($AdditionalFiles)
if ($extraList.Count -gt 0) {
    foreach ($extra in $extraList) {
        $extraFull = if ([System.IO.Path]::IsPathRooted($extra)) { $extra } else { Join-Path $projectRoot $extra }
        if (Test-Path -LiteralPath $extraFull -PathType Leaf) {
            $files.Add([System.IO.Path]::GetFullPath($extraFull))
        } elseif (Test-Path -LiteralPath $extraFull -PathType Container) {
            @(Get-ChildItem -LiteralPath $extraFull -Recurse -File -ErrorAction SilentlyContinue) | ForEach-Object {
                if (-not (Test-IsPathExcluded -FullPath $_.FullName)) {
                    $files.Add($_.FullName)
                }
            }
        }
    }
}

# 6. DATA CORPUS & SQLITE DATASTORE
if ($IncludeData -and $ExcludeData) {
    throw 'Use either -IncludeData or -ExcludeData, not both.'
}

$shouldIncludeData = (-not $ExcludeData)
$dataCount = 0
if ($shouldIncludeData) {
    # Discover SQLite datastore
    $sqliteCandidates = @(
        (Join-Path $projectRoot 'anp_data.sqlite'),
        (Join-Path $projectRoot '03_data/anp_data.sqlite'),
        (Join-Path $projectRoot 'data/anp_data.sqlite')
    )
    $sqlitePath = $null
    foreach ($cand in $sqliteCandidates) {
        if (Test-Path -LiteralPath $cand -PathType Leaf) {
            $sqlitePath = $cand
            break
        }
    }

    if ($null -eq $sqlitePath) {
        throw "Required data store not found: $(Join-Path $projectRoot 'anp_data.sqlite'). Use -ExcludeData only for an intentional code-only archive."
    }
    $files.Add($sqlitePath)

    # Discover raw data corpus directory
    $dataDirCandidates = @(
        (Join-Path $projectRoot '03_data'),
        (Join-Path $projectRoot 'data'),
        (Join-Path $projectRoot 'raw_data'),
        (Join-Path $projectRoot '02_raw_data')
    )
    $dataDir = $null
    foreach ($dirCand in $dataDirCandidates) {
        if (Test-Path -LiteralPath $dirCand -PathType Container) {
            $dataDir = $dirCand
            break
        }
    }

    if ($null -eq $dataDir) {
        throw "Required raw data corpus not found: $(Join-Path $projectRoot '03_data'). Use -ExcludeData only for an intentional code-only archive."
    }

    $dataAllowedExts = @('.csv', '.xlsx', '.xls', '.tsv', '.parquet', '.json', '.zip', '.gz', '.sqlite', '.db')
    $dataFiles = @(Get-ChildItem -LiteralPath $dataDir -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { -not (Test-IsPathExcluded -FullPath $_.FullName) -and ($_.Extension.ToLowerInvariant() -in $dataAllowedExts) } |
        Sort-Object FullName)

    if ($dataFiles.Count -eq 0) {
        throw "Raw data corpus is empty: $dataDir"
    }

    $dataFiles | ForEach-Object { $files.Add($_.FullName) }
    $dataCount = $dataFiles.Count + 1
}

# 7. PYTHON VIRTUAL ENVIRONMENT (.venv) WITH STORAGE OPTIMIZATION
$venvCount = 0
$venvSizeMb = 0
if ($shouldIncludeVenv) {
    $venvPath = Join-Path $projectRoot '.venv'
    if (-not (Test-Path -LiteralPath $venvPath -PathType Container)) {
        $venvCandidates = @(
            (Join-Path $projectRoot 'venv'),
            (Join-Path $projectRoot 'env')
        )
        foreach ($vc in $venvCandidates) {
            if (Test-Path -LiteralPath $vc -PathType Container) {
                $venvPath = $vc
                break
            }
        }
    }

    if (Test-Path -LiteralPath $venvPath -PathType Container) {
        Write-Host "[Framework Export] Scanning Python environment: $(Split-Path -Leaf $venvPath) (optimizing storage)..." -ForegroundColor Cyan
        
        # Optimize storage by pruning bytecode cache (__pycache__, *.pyc, *.pyo), pip cache, and test bloat in site-packages
        $venvFiles = @(Get-ChildItem -LiteralPath $venvPath -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
            $_.FullName -notmatch '\\__pycache__(\\|$)' -and
            $_.Extension -ne '.pyc' -and
            $_.Extension -ne '.pyo' -and
            $_.FullName -notmatch '\\(pip|_distutils_hack)\\'
        })

        if ($venvFiles.Count -gt 0) {
            $venvBytes = ($venvFiles | Measure-Object -Property Length -Sum).Sum
            $venvSizeMb = [math]::Round($venvBytes / 1MB, 1)
            $venvCount = $venvFiles.Count
            $venvFiles | ForEach-Object { $files.Add($_.FullName) }
            Write-Host "  [+] Optimized .venv environment: $venvCount files ($venvSizeMb MB) staged." -ForegroundColor Green
        }
    } else {
        Write-Warning "Virtual environment folder (.venv) requested but not found at: $venvPath"
    }
}

# Filter out duplicates and destination zip
$uniqueFiles = [System.Collections.Generic.List[string]]::new()
foreach ($f in $files) {
    $full = [System.IO.Path]::GetFullPath($f)
    if ($full -eq $destinationPath) { continue }
    if (-not $uniqueFiles.Contains($full)) {
        $uniqueFiles.Add($full)
    }
}

# GitHub file size limit check (100MB per file)
$oversized = @($uniqueFiles | Where-Object { (Get-Item -LiteralPath $_).Length -ge 100000000 })
if ($oversized.Count -gt 0) {
    $details = $oversized | ForEach-Object {
        $item = Get-Item -LiteralPath $_
        "{0} ({1} bytes)" -f $item.FullName, $item.Length
    }
    throw "Archive contains files at or above GitHub's 100,000,000-byte limit:`n$($details -join "`n")"
}

$relativeManifest = $uniqueFiles |
    ForEach-Object { $_.Substring($rootPrefix.Length).Replace('\', '/') } |
    Sort-Object

# User-friendly categorized summary
Write-Host ""
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host " PNMF Clean Framework Export Summary ($($relativeManifest.Count) files total)" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "  * Core Runtime & Launchers: $rootCount files"
Write-Host "  * Framework Package (pnmf): $packageCount files"
if ($shouldIncludeData) {
    Write-Host "  * Data Layer (SQLite + raw corpus): $dataCount files"
} else {
    Write-Host "  * Data Layer: Excluded (-ExcludeData specified)"
}
if ($shouldIncludeVenv -and $venvCount -gt 0) {
    Write-Host "  * Python Environment (.venv): $venvCount files ($venvSizeMb MB optimized)"
}
Write-Host "  * Tools Folder: Excluded (clean framework build)"
Write-Host "Destination: $destinationPath"
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host ""

if ($WhatIfPreference) {
    Write-Host 'WhatIf: archive was not created.'
    return
}

# Check existing destination
if (Test-Path -LiteralPath $destinationPath) {
    if (-not (Test-Path -LiteralPath $destinationPath -PathType Leaf)) {
        throw "Destination path exists but is not a file: $destinationPath"
    }
    $destinationIsValidZip = Test-ValidZipArchive -Path $destinationPath
    if (-not $Force -and $destinationIsValidZip) {
        throw "Destination already exists. Re-run with -Force to replace only this archive: $destinationPath"
    }
    if (-not $Force) {
        Write-Warning "Existing destination is not a valid ZIP; replacing it: $destinationPath"
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

    Write-Host "[Framework Export] Staging files for packaging..." -ForegroundColor Cyan
    foreach ($source in $uniqueFiles) {
        $relative = $source.Substring($rootPrefix.Length)
        $target = Join-Path $stageTop $relative
        $targetParent = Split-Path -Parent $target
        if (-not (Test-Path -LiteralPath $targetParent -PathType Container)) {
            New-Item -ItemType Directory -Path $targetParent -Force | Out-Null
        }
        Copy-Item -LiteralPath $source -Destination $target -Force
    }

    $manifestLines = @(
        'PNMF framework package',
        "Package Name: $packageName",
        "Generated UTC: $([DateTime]::UtcNow.ToString('o'))",
        "Data included: $shouldIncludeData",
        "Venv included: $shouldIncludeVenv",
        "Total files: $($relativeManifest.Count)",
        '',
        'SHA256  Path'
    )
    foreach ($relative in $relativeManifest) {
        $stagedPath = Join-Path $stageTop ($relative.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
        $hash = Get-Sha256Hex -Path $stagedPath
        $manifestLines += "$hash  $relative"
    }
    $manifestLines | Set-Content -LiteralPath (Join-Path $stageTop 'PACKAGE_MANIFEST.txt') -Encoding UTF8

    if ($PSCmdlet.ShouldProcess($destinationPath, 'Create PNMF framework archive')) {
        if (Test-Path -LiteralPath $destinationPath) {
            Remove-Item -LiteralPath $destinationPath -Force
        }
        Write-Host "[Framework Export] Compressing archive (this may take a moment for large packages)..." -ForegroundColor Cyan
        Compress-Archive -LiteralPath $stageTop -DestinationPath $destinationPath -CompressionLevel Optimal
        $archive = Get-Item -LiteralPath $destinationPath
        Write-Host "[Framework Export] Successfully created $($archive.FullName) ($([math]::Round($archive.Length / 1MB, 2)) MB)." -ForegroundColor Green
        Write-Host "[Framework Export] Included $($relativeManifest.Count) runtime/data files plus PACKAGE_MANIFEST.txt under $topLevelName/." -ForegroundColor Green
    }
}
finally {
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
