#!/usr/bin/env bash
# =============================================================================
# Dhan-LEAN Foundation Bootstrap Script (Linux / Bash)
# =============================================================================
# Verifies local prerequisites (.NET 10 SDK, Git, patch files) before cloning
# or modifying the vendored LEAN repository. Aligns QuantConnect/Lean to
# pinned commit 1fee999e4f437d09e255be5c3fde783206e05389, applies Market.cs patch,
# creates DataLibraries/, compiles C# projects, and verifies Dockerfile COPY targets.
# =============================================================================

set -euo pipefail

PINNED_COMMIT="1fee999e4f437d09e255be5c3fde783206e05389"
LEAN_REPO_URL="https://github.com/QuantConnect/Lean.git"

# Resolve absolute path of script directory to work reliably from any execution directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

LEAN_DIR="${REPO_ROOT}/Lean"
PATCH_MARKET_CS="${REPO_ROOT}/patches/lean/Market.cs"
PATCH_README="${REPO_ROOT}/patches/lean/README.md"
TARGET_MARKET_CS="${LEAN_DIR}/Common/Market.cs"
DATALIBRARIES_DIR="${REPO_ROOT}/DataLibraries"
SLN_PATH="${LEAN_DIR}/QuantConnect.Lean.sln"

echo "=== Dhan-LEAN Foundation Bootstrap (Linux) ==="

# ---------------------------------------------------------------------------
# 1. Prerequisite Validation (Cheap Checks Before Heavy Operations)
# ---------------------------------------------------------------------------
echo "[1/6] Validating local prerequisites..."

# Check Git
if ! command -v git &>/dev/null; then
    echo "ERROR: Git CLI is not installed or not in PATH. Please install Git." >&2
    exit 1
fi

# Check Patch Files
if [[ ! -f "${PATCH_MARKET_CS}" ]]; then
    echo "ERROR: Missing required patch file: ${PATCH_MARKET_CS}. Ensure repository files are tracked in Git." >&2
    exit 1
fi

if [[ ! -f "${PATCH_README}" ]]; then
    echo "ERROR: Missing required patch documentation: ${PATCH_README}." >&2
    exit 1
fi

# Check .NET SDK & Version
if ! command -v dotnet &>/dev/null; then
    echo "ERROR: .NET SDK is not installed on this host." >&2
    echo "Required SDK: .NET 10 SDK (targetFramework: net10.0)." >&2
    exit 1
fi

DOTNET_SDKS="$(dotnet --list-sdks 2>/dev/null || true)"
if ! echo "${DOTNET_SDKS}" | grep -qE '^10\.'; then
    echo "ERROR: .NET 10 SDK is required by LEAN (QuantConnect.Lean.Launcher targets net10.0), but was not found in 'dotnet --list-sdks'." >&2
    echo "Installed SDKs:" >&2
    echo "${DOTNET_SDKS}" >&2
    exit 1
fi

echo "✓ All local prerequisites (.NET 10 SDK, Git, Patch Files) verified."

# ---------------------------------------------------------------------------
# 2. Manage Lean/ Repository Checkout
# ---------------------------------------------------------------------------
if [[ -d "${LEAN_DIR}" ]]; then
    echo "[2/6] Validating existing Lean/ directory..."
    if [[ ! -d "${LEAN_DIR}/.git" ]]; then
        echo "ERROR: Lean/ exists but is not a Git repository. Remove or inspect it manually." >&2
        exit 1
    fi

    ORIGIN_URL="$(git -C "${LEAN_DIR}" remote get-url origin 2>/dev/null || true)"
    if [[ "${ORIGIN_URL}" != *"QuantConnect/Lean"* ]]; then
        echo "ERROR: Lean/ git remote origin '${ORIGIN_URL}' does not match official QuantConnect/Lean repository." >&2
        exit 1
    fi

    UNCOMMITTED="$(git -C "${LEAN_DIR}" status --porcelain 2>/dev/null | grep -v "Common/Market.cs" || true)"
    if [[ -n "${UNCOMMITTED}" ]]; then
        echo "ERROR: Lean/ repository has uncommitted local modifications:" >&2
        echo "${UNCOMMITTED}" >&2
        exit 1
    fi

    echo "Checking out pinned commit ${PINNED_COMMIT}..."
    git -C "${LEAN_DIR}" fetch origin "${PINNED_COMMIT}" --quiet
    git -C "${LEAN_DIR}" checkout "${PINNED_COMMIT}" --quiet
    echo "✓ Lean/ aligned to pinned commit ${PINNED_COMMIT}."
else
    echo "[2/6] Cloning QuantConnect/Lean repository..."
    git clone "${LEAN_REPO_URL}" "${LEAN_DIR}"
    git -C "${LEAN_DIR}" checkout "${PINNED_COMMIT}" --quiet
    echo "✓ Cloned and aligned to pinned commit ${PINNED_COMMIT}."
fi

# ---------------------------------------------------------------------------
# 3. Apply Custom Patches
# ---------------------------------------------------------------------------
echo "[3/6] Applying custom patches..."
cp "${PATCH_MARKET_CS}" "${TARGET_MARKET_CS}"
echo "✓ Applied Market.cs patch to Lean/Common/Market.cs."

# ---------------------------------------------------------------------------
# 4. Ensure DataLibraries Directory Exists
# ---------------------------------------------------------------------------
echo "[4/6] Checking DataLibraries directory..."
if [[ ! -d "${DATALIBRARIES_DIR}" ]]; then
    mkdir -p "${DATALIBRARIES_DIR}"
    echo "✓ Created empty DataLibraries/ directory."
else
    echo "✓ DataLibraries/ directory exists."
fi

# ---------------------------------------------------------------------------
# 5. Build LEAN Solution
# ---------------------------------------------------------------------------
echo "[5/6] Building LEAN Solution projects (dotnet build)..."
dotnet build "${SLN_PATH}" -c Debug --verbosity quiet
echo "✓ LEAN solution compiled successfully."

# ---------------------------------------------------------------------------
# 6. Verify Dockerfile COPY Sources
# ---------------------------------------------------------------------------
echo "[6/6] Verifying Dockerfile COPY source targets..."
REQUIRED_PATHS=(
    "${DATALIBRARIES_DIR}"
    "${LEAN_DIR}/Data"
    "${LEAN_DIR}/Launcher/bin/Debug"
    "${LEAN_DIR}/Optimizer.Launcher/bin/Debug"
    "${LEAN_DIR}/Report/bin/Debug"
    "${LEAN_DIR}/DownloaderDataProvider/bin/Debug"
)

MISSING=()
for path in "${REQUIRED_PATHS[@]}"; do
    if [[ ! -d "${path}" ]]; then
        MISSING+=("${path}")
    fi
done

if [[ ${#MISSING[@]} -gt 0 ]]; then
    echo "ERROR: The following required Dockerfile COPY paths are missing:" >&2
    for m in "${MISSING[@]}"; do
        echo "  - ${m}" >&2
    done
    exit 1
fi

echo "✓ All required Dockerfile COPY paths verified."
echo "=== Bootstrap completed successfully! ==="
