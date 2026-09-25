# scripts/preflight-gui.ps1
# SuperOffice AI Support MCP Platform — Visual Pre-Flight Health Dashboard Launcher

$ErrorActionPreference = "Continue"

$repoRoot = (Get-Item -Path $PSScriptRoot).Parent.FullName
Set-Location $repoRoot

Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host " SuperOffice AI Support MCP Platform — Visual Pre-Flight Dashboard" -ForegroundColor Cyan
Write-Host "========================================================================" -ForegroundColor Cyan
Write-Host "Starting local diagnostic web server at http://127.0.0.1:8088 ..." -ForegroundColor Yellow
Write-Host "Press Ctrl+C to terminate dashboard when pre-flight review is complete." -ForegroundColor Gray
Write-Host ""

uv run python -m platform_core.preflight --gui --port 8088
