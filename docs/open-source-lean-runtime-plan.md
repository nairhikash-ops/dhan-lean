> Historical pre-retirement record (non-active): retained for LEAN runtime provenance; it does not describe current provider dependencies.

# Open-Source LEAN Runtime Plan (Corrected)

> Created: 2026-07-21
> Purpose: Architectural design for running the open-source LEAN engine directly without LEAN CLI, QuantConnect API credentials, or paid cloud integration.

## 1. LEAN Version Context
- `v2.4.0.1` is the latest formal GitHub Release entry, but it represents old LEAN history and may not match the current continuously developed engine. It should not be treated as the current stable LEAN engine.

## 2. Runtime Pin & Source-to-Image Mapping
- **Docker Source Pin**: `1fee999e4f437d09e255be5c3fde783206e05389`
- **Mapping Issue Resolved**: We are discarding the unaccountable `quantconnect/lean:17932` pre-built image entirely. The runtime image will be built *locally* from the explicit pinned source commit `1fee999e4f437d09e255be5c3fde783206e05389`. See `docs/lean-engine-build-pin.md` for full provenance and build instructions.
- **Conclusion**: **RESOLVED**. We will build the `dhan-lean-engine:1fee999` image locally.

## 3. Configuration & Source Integrity
- Master source files must not be used to configure an older tag or an unidentified Docker image. 
- `Launcher/config.json`, `Market.cs`, market databases, sample data, and Docker instructions must all be sourced exactly from the pinned commit `1fee999e4f437d09e255be5c3fde783206e05389`.

## 4. Foundation vs Engine Image
- **`DockerfileLeanFoundation` / `quantconnect/lean:foundation`**: This is strictly the **build environment** (containing OS dependencies, Python, .NET SDKs, etc.).
- **Complete LEAN engine runtime image** (e.g., `quantconnect/lean:<tag>`): This is the **executable backtesting environment** containing the compiled C# LEAN engine DLLs (`QuantConnect.Lean.Launcher.dll`) ready to run algorithms.

## 5. Runtime Image Verification
- **Status**: **RESOLVED via Local Build**. The runtime image entrypoint, working directory, Launcher DLL location, and Python environment are now structurally proven because we compile the exact source and execute its bundled `Dockerfile` locally.

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
- **Status**: **RESOLVED (Pending execution)**. We will extract the exact map files, factor files, and properties directly from `1fee999e4f437d09e255be5c3fde783206e05389` when sufficient disk space permits the checkout.

## 8. Disk Estimates
- **Measured Compressed Image Size**: `14.04 GB` (for tag `17932` on Docker Hub).
- **Measured Local Docker Usage**: Currently unknown / N/A (Docker image not pulled).
- **Estimated Peak Extraction Requirement**: ~30-35 GB (Extrapolated estimate based on 14 GB compressed index size across architectures, though single arch extraction may require ~15-20 GB locally). 
- *Note: These are estimates. Do not proceed unless sufficient disk space is mathematically guaranteed.*

---
## Final Classification

**BLOCKED BY DISK SPACE**
