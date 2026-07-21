<#
.SYNOPSIS
    Bootstrap script for QuantConnect LEAN engine foundation.
.DESCRIPTION
    Ensures official QuantConnect/Lean repository is checked out at pinned commit
    1fee999e4f437d09e255be5c3fde783206e05389, applies custom patches (Market.cs),
    creates DataLibraries/, builds C# projects, and verifies Dockerfile build requirements.
#>

$ErrorActionPreference = "Stop"

$PINNED_COMMIT = "1fee999e4f437d09e255be5c3fde783206e05389"
$LEAN_REPO_URL = "https://github.com/QuantConnect/Lean.git"
$LEAN_DIR = Join-Path $PSScriptRoot "..\Lean"
$PATCH_MARKET_CS = Join-Path $PSScriptRoot "..\patches\lean\Market.cs"
$TARGET_MARKET_CS = Join-Path $LEAN_DIR "Common\Market.cs"
$DATALIBRARIES_DIR = Join-Path $PSScriptRoot "..\DataLibraries"

Write-Host "=== Dhan-LEAN Foundation Bootstrap ===" -ForegroundColor Cyan

# 1. Manage Lean/ Repository Checkout
if (Test-Path $LEAN_DIR) {
    Write-Host "[1/5] Validating existing Lean/ directory..." -ForegroundColor Yellow
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
    Write-Host "[1/5] Cloning QuantConnect/Lean repository..." -ForegroundColor Yellow
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

# 2. Apply Custom Patches
Write-Host "[2/5] Applying custom patches..." -ForegroundColor Yellow
if (-not (Test-Path $PATCH_MARKET_CS)) {
    Write-Error "ERROR: Patch file missing: $PATCH_MARKET_CS"
    exit 1
}
Copy-Item -Path $PATCH_MARKET_CS -Destination $TARGET_MARKET_CS -Force
Write-Host "✓ Applied Market.cs patch to Lean/Common/Market.cs." -ForegroundColor Green

# 3. Ensure DataLibraries Directory Exists
Write-Host "[3/5] Checking DataLibraries directory..." -ForegroundColor Yellow
if (-not (Test-Path $DATALIBRARIES_DIR)) {
    New-Item -ItemType Directory -Path $DATALIBRARIES_DIR | Out-Null
    Write-Host "✓ Created empty DataLibraries/ directory." -ForegroundColor Green
} else {
    Write-Host "✓ DataLibraries/ directory exists." -ForegroundColor Green
}

# 4. Build LEAN Solution
Write-Host "[4/5] Building LEAN Solution projects (dotnet build)..." -ForegroundColor Yellow
$slnPath = Join-Path $LEAN_DIR "QuantConnect.Lean.sln"
dotnet build $slnPath -c Debug --verbosity quiet
if ($LASTEXITCODE -ne 0) {
    Write-Error "ERROR: dotnet build failed for QuantConnect.Lean.sln."
    exit 1
}
Write-Host "✓ LEAN solution compiled successfully." -ForegroundColor Green

# 5. Verify Dockerfile COPY Sources
Write-Host "[5/5] Verifying Dockerfile COPY source targets..." -ForegroundColor Yellow
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
