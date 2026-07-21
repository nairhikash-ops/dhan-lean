# Open-Source LEAN Runtime Plan (Corrected)

> Created: 2026-07-21
> Purpose: Architectural design for running the open-source LEAN engine directly without LEAN CLI, QuantConnect API credentials, or paid cloud integration.

## 1. LEAN Version Context
- `v2.4.0.1` is the latest formal GitHub Release entry, but it represents old LEAN history and may not match the current continuously developed engine. It should not be treated as the current stable LEAN engine.

## 2. Runtime Pin & Source-to-Image Mapping
- **Docker Tag Analyzed**: `quantconnect/lean:17932`
- **Architecture**: `amd64` (and `arm64`)
- **Creation Date**: Last pushed on `2026-07-17T20:15:36Z`
- **Mapping Issue**: The tag `17932` appears to be a CI build number rather than a Git commit SHA prefix. A lookup of `17932` against the GitHub API does not resolve to a specific identifiable commit.
- **Status**: Because the exact source commit corresponding to Docker tag `17932` cannot be proven, the internal entrypoint, working directory, launcher path, and Python version of this specific image build cannot be verified against source code. 
- **Conclusion**: **UNRESOLVED**. This image is not recommended until the exact source mapping is proven.

## 3. Configuration & Source Integrity
- Master source files must not be used to configure an older tag or an unidentified Docker image. 
- `Launcher/config.json`, `Market.cs`, market databases, sample data, and Docker instructions must all be sourced from the exact selected commit. Since the commit is unresolved, no configuration can be finalized.

## 4. Foundation vs Engine Image
- **`DockerfileLeanFoundation` / `quantconnect/lean:foundation`**: This is strictly the **build environment** (containing OS dependencies, Python, .NET SDKs, etc.).
- **Complete LEAN engine runtime image** (e.g., `quantconnect/lean:<tag>`): This is the **executable backtesting environment** containing the compiled C# LEAN engine DLLs (`QuantConnect.Lean.Launcher.dll`) ready to run algorithms.

## 5. Runtime Image Verification
- **Status**: **UNRESOLVED**. Without a proven pinned commit, we cannot safely inspect the Dockerfile to verify the image entrypoint, working directory, Launcher DLL location, mount targets (config, algorithm, data, results), or exact Python runtime version.

## 6. Config Validation
- The previously proposed reduced `config.json` is **not** guaranteed to be valid for an unknown engine version. 
- For the first runtime gate, the complete official `Launcher/config.json` from the pinned source commit must be used, modifying only:
  - `environment`
  - `algorithm-language`
  - `algorithm-type-name`
  - `algorithm-location`
  - `data-folder`
  - `results-destination-folder`
  - Cloud/API handlers (to keep execution local)
- *All modifications must be documented with justifications once a commit is pinned.*

## 7. India Support Verification
- **Status**: **UNRESOLVED**. Without a pinned commit, we cannot verify:
  - India symbol-properties entry or fallback behavior.
  - India market-hours entry.
  - Exact `cccl.zip` path and casing.
  - Internal CSV filename casing.
  - Map-file path and minimum requirements.
  - Factor-file path and minimum requirements.

## 8. Disk Estimates
- **Measured Compressed Image Size**: `14.04 GB` (for tag `17932` on Docker Hub).
- **Measured Local Docker Usage**: Currently unknown / N/A (Docker image not pulled).
- **Estimated Peak Extraction Requirement**: ~30-35 GB (Extrapolated estimate based on 14 GB compressed index size across architectures, though single arch extraction may require ~15-20 GB locally). 
- *Note: These are estimates. Do not proceed unless sufficient disk space is mathematically guaranteed.*

---
## Final Classification

**ENGINE IMAGE PIN UNRESOLVED**
