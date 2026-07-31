[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$Destination,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# This exporter is allowlist-only: files not constructed below cannot enter the archive.
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$packageName = 'pnmf-framework'
$topLevelName = 'pnmf-framework'

if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path (Split-Path -Parent $projectRoot) "$packageName.zip"
}

$destinationPath = [System.IO.Path]::GetFullPath($Destination)
if ([System.IO.Path]::GetExtension($destinationPath) -ne '.zip') {
    throw "Destination must end in .zip: $destinationPath"
}

$rootPrefix = $projectRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if ($destinationPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Destination must be outside the PNMF project tree: $destinationPath"
}

$files = [System.Collections.Generic.List[string]]::new()
foreach ($relative in @('pnmf_cli.py', 'pnmf_ui.py', 'pnmf.ps1', 'requirements.txt', 'README.md', 'HOW_TO_USE.txt', 'tools/export_framework_zip.ps1')) {
    $path = Join-Path $projectRoot $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required allowlisted file is missing: $relative"
    }
    $files.Add($path)
}

foreach ($folder in @('pnmf', 'tests')) {
    $folderPath = Join-Path $projectRoot $folder
    if (-not (Test-Path -LiteralPath $folderPath -PathType Container)) {
        throw "Required allowlisted directory is missing: $folder"
    }
    Get-ChildItem -LiteralPath $folderPath -Recurse -File -Filter '*.py' |
        Sort-Object FullName |
        ForEach-Object { $files.Add($_.FullName) }
}

$relativeManifest = $files |
    ForEach-Object { $_.Substring($rootPrefix.Length).Replace('\', '/') } |
    Sort-Object

Write-Host "PNMF framework export manifest ($($relativeManifest.Count) files):"
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

    foreach ($source in $files) {
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
        Write-Host "Created $($archive.FullName) ($([math]::Round($archive.Length / 1KB, 1)) KiB)."
        Write-Host "Included $($relativeManifest.Count) allowlisted files under $topLevelName/."
    }
}
finally {
    if (Test-Path -LiteralPath $stageRoot) {
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
}
