# LEAN Version Matrix

> Created: 2026-07-21
> Purpose: Exact version identifiers, release dates, compatibility, and
> unresolved items for all LEAN components used or considered in this project.

---

## 1. LEAN Engine

| Attribute | Value |
|-----------|-------|
| **Repository** | https://github.com/QuantConnect/Lean |
| **License** | Apache-2.0 |
| **Latest formal release** | `v2.4.0.1` (2024-08-08) |
| **Latest commit tag** | `17932` (2026-07-17) |
| **Versioning scheme** | Formal releases (v2.x.x.x) + rolling commit tags |
| **Primary language** | C# 94.2%, Python 5.6% |
| **Runtime** | .NET 10 SDK |
| **Python integration** | Python.NET (`QuantConnect.pythonnet 2.0.64`) |
| **Docker base image** | `quantconnect/lean:foundation` |
| **Docker entry point** | `dotnet QuantConnect.Lean.Launcher.dll` |

### Evidence

- Formal release `v2.4.0.1`: CONFIRMED BY OFFICIAL DOCUMENTATION (GitHub releases page)
- Commit tags `17932`, `17931`, etc.: CONFIRMED BY OFFICIAL DOCUMENTATION (GitHub tags page)
- .NET 10 SDK: CONFIRMED BY SOURCE CODE (Dockerfile in master)
- Python.NET: CONFIRMED BY OFFICIAL DOCUMENTATION (commit message #9623)

---

## 2. LEAN CLI

| Attribute | Value |
|-----------|-------|
| **Repository** | https://github.com/QuantConnect/lean-cli |
| **PyPI package** | `lean` |
| **Latest version** | `1.0.227` |
| **Upload date** | 2026-06-26 |
| **Python requirement** | `>=3.9` |
| **License** | Apache-2.0 |
| **Key dependency** | Docker (required for local backtesting) |

### Evidence

- Version `1.0.227`: CONFIRMED BY OFFICIAL DOCUMENTATION (PyPI JSON API)
- Python `>=3.9`: CONFIRMED BY OFFICIAL DOCUMENTATION (PyPI metadata)

---

## 3. Docker Requirements

| Attribute | Value |
|-----------|-------|
| **Engine image** | `quantconnect/lean:latest` or `quantconnect/lean:<tag>` |
| **Foundation image** | `quantconnect/lean:foundation` |
| **Jupyter image** | `quantconnect/research:latest` |
| **ARM support** | `DockerfileLeanFoundationARM` available |
| **Container runtime** | Docker Engine or Docker Desktop |

### Evidence

- Dockerfile structure: CONFIRMED BY SOURCE CODE (`Lean/Dockerfile`, `Lean/DockerfileLeanFoundation`)

---

## 4. Python Compatibility

| Component | Python Version |
|-----------|---------------|
| **LEAN CLI (`lean`)** | `>=3.9` |
| **DhanHQ SDK (`dhanhq`)** | `>=3.10` (project target) |
| **This project** | `>=3.10` |

The project's effective Python floor is `>=3.10`, which satisfies both the
LEAN CLI and DhanHQ SDK requirements.

### Evidence

- LEAN CLI `>=3.9`: CONFIRMED BY OFFICIAL DOCUMENTATION (PyPI metadata)
- DhanHQ `>=3.10`: CONFIRMED BY SOURCE CODE (`references/DhanHQ-py/setup.py`)

---

## 5. Python Execution Model

Python algorithms in LEAN execute through **Python.NET**, which allows C# and
Python to interoperate in-process. The LEAN engine is a .NET application; Python
code is hosted via the `QuantConnect.pythonnet` bridge.

Key implications:
- Python algorithms have access to the full .NET standard library
- Python packages must be compatible with the Python version in the Docker image
- The `Algorithm.Python` project in the LEAN repository contains example algorithms

### Evidence

- Python.NET bridge: CONFIRMED BY SOURCE CODE (`Lean/Algorithm.Python/`)
- Python.NET version `2.0.64`: CONFIRMED BY OFFICIAL DOCUMENTATION (commit #9623)

---

## 6. Windows vs Linux

| Aspect | Windows Development | Linux VPS |
|--------|-------------------|-----------|
| **LEAN engine** | Supported (Visual Studio or CLI) | Supported (Docker or dotnet CLI) |
| **Python algorithms** | Supported | Supported |
| **Docker** | Docker Desktop | Docker Engine |
| **Data paths** | Use forward slashes in config | Native paths |
| **Timezone handling** | LEAN normalizes to UTC internally | LEAN normalizes to UTC internally |

LEAN is cross-platform. The Docker image runs on Linux. Development can occur
on Windows with results matching the Linux VPS deployment. No material
differences affect backtest determinism.

### Evidence

- Cross-platform: CONFIRMED BY OFFICIAL DOCUMENTATION (lean.io: "Cross Platform — Windows, Mac OS, Linux")

---

## 7. Unresolved Items

| Item | Status | Impact |
|------|--------|--------|
| Whether LEAN uses rolling commit tags indefinitely or will resume formal releases | UNRESOLVED | Must pin to a specific commit hash for reproducibility |
| Exact .NET 10 SDK version bundled in Docker foundation image | UNRESOLVED | Low — Docker image handles this |
| Whether Python.NET in LEAN supports numpy/pandas out of the box in Docker | UNRESOLVED | Must verify during PoC |
| Whether `lean-cli` `1.0.227` is compatible with engine commit `17932` | UNRESOLVED | Must verify during installation |

---

## 8. Version Pinning Policy

| Component | Pinning Strategy |
|-----------|-----------------|
| **LEAN engine** | Pin to specific commit tag (e.g., `17932`) or Docker image tag |
| **LEAN CLI** | Pin to specific PyPI version (`1.0.227`) |
| **Docker images** | Use specific tags, never `latest` in production |
| **Python** | `>=3.10` (system-level, managed by Docker) |

All version pins must be recorded in `docs/lean-version-matrix.md` and
committed before any installation.
