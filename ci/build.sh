#!/usr/bin/env pwsh

<#
.SYNOPSIS
    Build and test the GameBridge custom RuneLite client and Python automation layer.

.DESCRIPTION
    This script:
    1. Installs Python and Java dependencies
    2. Builds the custom RuneLite client
    3. Runs all unit tests (Python + Java)
    4. Reports results

    Requires: Windows, PowerShell 5.1+, mise
#>

param(
    [switch]$SkipDependencies,
    [switch]$SkipBuild,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$WarningPreference = 'Continue'

Write-Host "====== GameBridge Build & Test ======" -ForegroundColor Cyan

# Step 1: Install dependencies
if (-not $SkipDependencies)
{
    Write-Host "`n[1/3] Installing dependencies..." -ForegroundColor Green
    
    Write-Host "  - Python packages" -ForegroundColor Gray
    mise run gamebridge-setup
    if ($LASTEXITCODE -ne 0) { throw "Failed to install Python dependencies" }
    
    Write-Host "  ✓ Dependencies installed" -ForegroundColor Green
}

# Step 2: Build custom RuneLite client
if (-not $SkipBuild)
{
    Write-Host "`n[2/3] Building custom RuneLite client..." -ForegroundColor Green
    
    mise run full-build
    if ($LASTEXITCODE -ne 0) { throw "Failed to build custom RuneLite client" }
    
    Write-Host "  ✓ Build complete" -ForegroundColor Green
}

# Step 3: Run all tests
if (-not $SkipTests)
{
    Write-Host "`n[3/3] Running unit tests..." -ForegroundColor Green
    
    mise run test
    if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
    
    Write-Host "  ✓ All tests passed" -ForegroundColor Green
}

Write-Host "`n====== Build & Test Complete ======" -ForegroundColor Cyan
exit 0

