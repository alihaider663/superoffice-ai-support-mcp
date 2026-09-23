<#
.SYNOPSIS
    SuperOffice Local Codebase Mirror & Synchronization Utility.

.DESCRIPTION
    Extracts custom scripts (ejscript), screen definitions, and custom table schemas
    from SuperOffice into a local, user-configured filesystem path (e.g. F:\CodeBase_SuperOffice).

.PARAMETER OutputDir
    Local destination directory path (overrides SUPEROFFICE_CODEBASE_LOCAL_PATH in .env).

.PARAMETER Mode
    Extraction mode: 'http' (via CRMScript handler) or 'mssql' (via direct database connection).

.PARAMETER Tables
    Comma-separated list of entities to extract (e.g. 'ejscript,screens,schema' or 'all').

.PARAMETER DryRun
    When present, scans and evaluates without writing files to disk.

.PARAMETER Verbose
    Enable detailed debug logging.

.EXAMPLE
    .\scripts\sync-so-codebase.ps1
    .\scripts\sync-so-codebase.ps1 -OutputDir "F:\CodeBase_SuperOffice" -Mode http
    .\scripts\sync-so-codebase.ps1 -DryRun
#>

[CmdletBinding()]
param (
    [string]$OutputDir,
    [ValidateSet('http', 'mssql')]
    [string]$Mode,
    [string]$Tables,
    [switch]$DryRun,
    [switch]$Verbose
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

Push-Location $RootDir
try {
    $cliArgs = @("-m", "so_mcp.sync.cli")

    if ($OutputDir) {
        $cliArgs += @("-o", $OutputDir)
    }
    if ($Mode) {
        $cliArgs += @("-m", $Mode)
    }
    if ($Tables) {
        $cliArgs += @("-t", $Tables)
    }
    if ($DryRun) {
        $cliArgs += @("--dry-run")
    }
    if ($Verbose) {
        $cliArgs += @("-v")
    }

    Write-Host "[sync-so-codebase] Running uv run python $($cliArgs -join ' ')..." -ForegroundColor Cyan
    & uv run python @cliArgs
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
