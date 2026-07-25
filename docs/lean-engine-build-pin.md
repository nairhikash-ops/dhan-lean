> Historical pre-retirement record (non-active): retained for LEAN build provenance; it does not describe current provider dependencies.

# LEAN Engine Build Pin

> Created: 2026-07-21
> Purpose: Defines the reproducible Docker build from an exact official source commit, discarding unaccountable pre-built engine images.

## 1. Selected Source Commit
- **Repository**: `https://github.com/QuantConnect/Lean`
- **Commit SHA**: `1fee999e4f437d09e255be5c3fde783206e05389`
- **Short SHA**: `1fee999`
- **Commit Date**: `2026-07-16T15:25:22Z`
- **Commit Message**: `Update QuantConnect.pythonnet to 2.0.64 (#9623)`
- **CI Status**: Expected passing (recent master).
- **.NET SDK**: Expected .NET 8 (or exactly as defined in the repo; `global.json` omitted in this commit layer).
- **Python Version**: Configured in the upstream `quantconnect/lean:foundation` image (Python 3.11).

## 2. Docker Build Analysis
- **Dockerfile**: The repository's root `Dockerfile` builds a complete runnable engine image.
- **Foundation Dependency**: Yes, it relies on `FROM quantconnect/lean:foundation` as the OS/SDK build environment.
- **Build Context**: Repository root.
- **Final Working Directory**: `/Lean/Launcher/bin/Debug`
- **Entrypoint/Command**: `dotnet QuantConnect.Lean.Launcher.dll`
- **Launcher DLL Path**: `/Lean/Launcher/bin/Debug/QuantConnect.Lean.Launcher.dll`
- **Algorithm Path**: Usually mapped to `/Lean/Algorithm/main.py`.
- **Data Path**: `/Lean/Data/`
- **Results Path**: `/Lean/Results/`

## 3. Image Identity & Provenance
The image must be built and tagged locally as:
`dhan-lean-engine:1fee999`

**OCI Labels to apply during build**:
- `org.opencontainers.image.source="https://github.com/QuantConnect/Lean"`
- `org.opencontainers.image.revision="1fee999e4f437d09e255be5c3fde783206e05389"`
- `org.opencontainers.image.created="2026-07-21"`
- `org.opencontainers.image.title="dhan-lean-engine"`
- `org.opencontainers.image.version="1fee999"`

## 4. Reproducible Build Commands
*Do not execute these commands until disk space allows.*

```bash
# 1. Shallow clone the specific commit
git clone --depth 1 --filter=blob:none --sparse https://github.com/QuantConnect/Lean
cd Lean
git fetch --depth 1 origin 1fee999e4f437d09e255be5c3fde783206e05389
git checkout 1fee999e4f437d09e255be5c3fde783206e05389

# 2. Verify checked-out SHA
git rev-parse HEAD

# 3. Build the engine image locally with C# compilation
# Note: In LEAN, you typically compile the C# solutions first, then run docker build.
# We will use LEAN's standard dotnet build script, or direct docker build if multi-stage is supported.
# Assuming local dotnet compilation into bin/Debug, then Docker packaging:
dotnet build QuantConnect.Lean.sln -c Debug
docker build -t dhan-lean-engine:1fee999 \
  --label org.opencontainers.image.source="https://github.com/QuantConnect/Lean" \
  --label org.opencontainers.image.revision="1fee999e4f437d09e255be5c3fde783206e05389" \
  .

# 4. Record Image ID and Digest
docker inspect dhan-lean-engine:1fee999 | grep Id

# 5. Test Launcher entrypoint (no config)
docker run --rm dhan-lean-engine:1fee999 dotnet QuantConnect.Lean.Launcher.dll --help
```

## 5. Aligned Runtime Assets
All of the following configuration and sample databases MUST be sourced exactly from tree `1fee999e4f437d09e255be5c3fde783206e05389`:
- `Launcher/config.json`
- `Common/Market.cs`
- `Data/market-hours/market-hours-database.json`
- `Data/symbol-properties/symbol-properties-database.csv`
- India sample equity data (if available in `Data/equity/india/`)
- Map files (if available in `Data/equity/india/map_files/`)
- Factor files (if available in `Data/equity/india/factor_files/`)

## 6. Revised Direct Runtime Architecture
`1fee999e4f437d09e255be5c3fde783206e05389`
→ Locally built pinned runtime image (`dhan-lean-engine:1fee999`)
→ Mounted project algorithm (`main.py`)
→ Mounted local Dhan-converted data (`/Lean/Data`)
→ Mounted result directory (`/Lean/Results`)
→ Deterministic local backtest output.

*No LEAN CLI, no QuantConnect credentials, no unverified Docker Hub tags.*

## 7. Disk-Space Planning (Estimates)
- **Shallow Source Checkout**: ~200 MB
- **NuGet and Docker Build Cache**: ~3 GB
- **Intermediate Docker Layers**: ~2 GB
- **Final Runtime Image**: ~1.5 GB (on top of Foundation)
- **Peak Temporary Disk Use**: ~8-10 GB
- **Safe Minimum Free-Space Target**: **15 GB** is recommended before attempting this build.

*(Current free disk space is ~7.88 GB, which is below the safe threshold.)*

---
## Final Classification

**BLOCKED BY DISK SPACE**
