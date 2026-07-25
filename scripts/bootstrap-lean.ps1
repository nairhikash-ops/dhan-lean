<#
.SYNOPSIS
    Bootstrap script for QuantConnect LEAN engine foundation.
.DESCRIPTION
    Verifies all cheap local prerequisites (.NET 10 SDK, Git, patch files) before
    cloning or modifying the vendored LEAN repository. Aligns QuantConnect/Lean to
    pinned commit 1fee999e4f437d09e255be5c3fde783206e05389, applies Market.cs patch,
    creates DataLibraries/, compiles C# projects, and verifies Dockerfile COPY targets.
#>

$ErrorActionPreference = "Stop"

$PINNED_COMMIT = "1fee999e4f437d09e255be5c3fde783206e05389"
$LEAN_REPO_URL = "https://github.com/QuantConnect/Lean.git"
$LEAN_DIR = Join-Path $PSScriptRoot "..\Lean"
$PATCH_MARKET_CS = Join-Path $PSScriptRoot "..\patches\lean\Market.cs"
$PATCH_README = Join-Path $PSScriptRoot "..\patches\lean\README.md"
$TARGET_MARKET_CS = Join-Path $LEAN_DIR "Common\Market.cs"
$DATALIBRARIES_DIR = Join-Path $PSScriptRoot "..\DataLibraries"

Write-Host "=== Offline LEAN Foundation Bootstrap ===" -ForegroundColor Cyan

# ---------------------------------------------------------------------------
# 1. Prerequisite Validation (Cheap Checks Before Any Heavy Operations)
# ---------------------------------------------------------------------------
Write-Host "[1/6] Validating local prerequisites..." -ForegroundColor Yellow

# Check Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "ERROR: Git CLI is not installed or not in PATH. Please install Git."
    exit 1
}

# Check Patch Files
if (-not (Test-Path $PATCH_MARKET_CS)) {
    Write-Error "ERROR: Missing required patch file: $PATCH_MARKET_CS. Ensure repository files are tracked in Git."
    exit 1
}

if (-not (Test-Path $PATCH_README)) {
    Write-Error "ERROR: Missing required patch documentation: $PATCH_README."
    exit 1
}

# Check .NET SDK & Version
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    Write-Error "ERROR: .NET SDK is not installed on this host.`nRequired SDK: .NET 10 SDK (targetFramework: net10.0).`nAction: Install .NET 10 SDK from https://dotnet.microsoft.com/download"
    exit 1
}

$dotnetSdks = & dotnet --list-sdks 2>$null
if (-not ($dotnetSdks -match "10\.\d+")) {
    Write-Error "ERROR: .NET 10 SDK is required by LEAN (QuantConnect.Lean.Launcher targets net10.0), but was not found in 'dotnet --list-sdks'.`nInstalled SDKs:`n$dotnetSdks`nAction: Install .NET 10 SDK before running bootstrap."
    exit 1
}

Write-Host "✓ All local prerequisites (.NET 10 SDK, Git, Patch Files) verified." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 2. Manage Lean/ Repository Checkout
# ---------------------------------------------------------------------------
if (Test-Path $LEAN_DIR) {
    Write-Host "[2/6] Validating existing Lean/ directory..." -ForegroundColor Yellow
    # Verify it is a Git repository
    $gitDir = Join-Path $LEAN_DIR ".git"
    if (-not (Test-Path $gitDir)) {
        Write-Error "ERROR: Lean/ exists but is not a Git repository. Remove or inspect it manually."
        exit 1
    }

    # Verify origin remote
    $originUrl = git -C $LEAN_DIR remote get-url origin 2>$null
    if ($originUrl -notlike "*QuantConnect/Lean*") {
        Write-Error "ERROR: Lean/ git remote origin '$originUrl' does not match official QuantConnect/Lean repository."
        exit 1
    }

    # Check for uncommitted changes (excluding Common/Market.cs if already patched)
    $status = git -C $LEAN_DIR status --porcelain 2>$null
    $uncommitted = $status | Where-Object { $_ -notlike "*Common/Market.cs*" }
    if ($uncommitted) {
        Write-Error "ERROR: Lean/ repository has uncommitted local modifications:`n$($uncommitted -join "`n")"
        exit 1
    }

    # Checkout pinned commit
    Write-Host "Checking out pinned commit $PINNED_COMMIT..." -ForegroundColor Yellow
    git -C $LEAN_DIR fetch origin $PINNED_COMMIT --quiet
    git -C $LEAN_DIR checkout $PINNED_COMMIT --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ERROR: Failed to checkout pinned commit $PINNED_COMMIT."
        exit 1
    }
    Write-Host "✓ Lean/ aligned to pinned commit $PINNED_COMMIT." -ForegroundColor Green
} else {
    Write-Host "[2/6] Cloning QuantConnect/Lean repository..." -ForegroundColor Yellow
    git clone $LEAN_REPO_URL $LEAN_DIR
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ERROR: Failed to clone QuantConnect/Lean."
        exit 1
    }
    git -C $LEAN_DIR checkout $PINNED_COMMIT --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Error "ERROR: Failed to checkout pinned commit $PINNED_COMMIT after clone."
        exit 1
    }
    Write-Host "✓ Cloned and aligned to pinned commit $PINNED_COMMIT." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 3. Apply Custom Patches
# ---------------------------------------------------------------------------
Write-Host "[3/6] Applying custom patches..." -ForegroundColor Yellow
Copy-Item -Path $PATCH_MARKET_CS -Destination $TARGET_MARKET_CS -Force
Write-Host "✓ Applied Market.cs patch to Lean/Common/Market.cs." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 4. Ensure DataLibraries Directory Exists
# ---------------------------------------------------------------------------
Write-Host "[4/6] Checking DataLibraries directory..." -ForegroundColor Yellow
if (-not (Test-Path $DATALIBRARIES_DIR)) {
    New-Item -ItemType Directory -Path $DATALIBRARIES_DIR | Out-Null
    Write-Host "✓ Created empty DataLibraries/ directory." -ForegroundColor Green
} else {
    Write-Host "✓ DataLibraries/ directory exists." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 5. Build LEAN Solution
# ---------------------------------------------------------------------------
Write-Host "[5/6] Building LEAN Solution projects (dotnet build)..." -ForegroundColor Yellow
$slnPath = Join-Path $LEAN_DIR "QuantConnect.Lean.sln"
dotnet build $slnPath -c Debug --verbosity quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "ERROR: dotnet build failed for QuantConnect.Lean.sln."
    exit 1
}
Write-Host "✓ LEAN solution compiled successfully." -ForegroundColor Green

# ---------------------------------------------------------------------------
# 6. Verify Dockerfile COPY Sources
# ---------------------------------------------------------------------------
Write-Host "[6/6] Verifying Dockerfile COPY source targets..." -ForegroundColor Yellow
$requiredPaths = @(
    $DATALIBRARIES_DIR,
    (Join-Path $LEAN_DIR "Data"),
    (Join-Path $LEAN_DIR "Launcher\bin\Debug"),
    (Join-Path $LEAN_DIR "Optimizer.Launcher\bin\Debug"),
    (Join-Path $LEAN_DIR "Report\bin\Debug"),
    (Join-Path $LEAN_DIR "DownloaderDataProvider\bin\Debug")
)

$missing = @()
foreach ($path in $requiredPaths) {
    if (-not (Test-Path $path)) {
        $missing += $path
    }
}

if ($missing.Count -gt 0) {
    Write-Error "ERROR: The following required Dockerfile COPY paths are missing:`n$($missing -join "`n")"
    exit 1
}

Write-Host "✓ All required Dockerfile COPY paths verified." -ForegroundColor Green
Write-Host "=== Bootstrap completed successfully! ===" -ForegroundColor Green
