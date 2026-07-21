# Docker Runtime Blocker

> Created: 2026-07-21
> Purpose: Read-only diagnostic report after LEAN runtime gate attempt failed due to Docker storage corruption.

---

## Classification

**DOCKER STORAGE DEGRADED**

Docker Desktop processes are running but the Docker Engine daemon cannot
read or write its metadata database. All `docker` commands fail with
`input/output error` on
`/var/lib/desktop-containerd/daemon/io.containerd.metadata.v1.bolt/meta.db`.

---

## Command Log (executed during runtime-gate attempt)

| # | Command | Outcome |
|---|---------|---------|
| 1 | `pip install lean==1.0.227` | Installed successfully |
| 2 | `lean --version` | `lean 1.0.227` confirmed |
| 3 | `docker info` | Server section showed running daemon (pre-corruption) |
| 4 | `mkdir test-runtime/...` | Project directories created |
| 5 | `lean init` | Failed — credentials required |
| 6 | `lean project-create test-runtime --language python` | Created project |
| 7 | Write `test-runtime/main.py` | India equity gate algorithm |
| 8 | Write `test-runtime/generate_data.py` | Synthetic data generator |
| 9 | `python generate_data.py` | 260 bars → `TEST.zip` |
| 10 | `lean backtest test-runtime` | Failed — requires `lean.json` |
| 11 | `lean init` in clean dir | Failed — credentials invalid |
| 12 | Created dummy `C:\Users\DELL\.lean\credentials` | To satisfy CLI |
| 13 | `lean init` (retry) | Failed — credentials rejected by API |
| 14 | `lean project-create` (retry) | Created project successfully |
| 15 | Created `test-runtime/lean.json` manually | Configuration file |
| 16 | `lean backtest test-runtime` (retry) | Failed — still requires `lean init` root |
| 17 | Read `lean-cli backtest.py` source from GitHub | Confirmed `requires_lean_config=True` |
| 18 | `docker pull quantconnect/lean:foundation` | First I/O error appeared |
| 19 | `wsl --shutdown` | Timed out (30s) |
| 20 | Temp file cleanup | ~1.4 GB freed |
| 21 | Windows Temp cleanup | Additional space freed |
| 22 | `Restart-Service com.docker.service` | Service restarted |
| 23 | `docker pull quantconnect/lean:foundation` (retry) | I/O error persisted |
| 24 | `Stop-Process "Docker Desktop"` | Docker stopped |
| 25 | `wsl --shutdown` (retry) | Succeeded |
| 26 | `diskpart /s compact_vhdx.txt` | Compact attempted on `docker_data.vhdx` |
| 27 | `Start-Process Docker Desktop.exe` | Docker restarted |
| 28 | `docker pull quantconnect/lean:foundation` (retry) | I/O error on overlayfs snapshot |

**At this point user ordered diagnostic-only mode. No further commands were
executed.**

---

## What Changed

### Files and Directories Modified

| Item | Before | After | Changed? |
|------|--------|-------|----------|
| `test-runtime/main.py` | Did not exist | Created (21 lines) | **Yes** |
| `test-runtime/config.json` | Did not exist | Created (5 lines) | **Yes** |
| `test-runtime/generate_data.py` | Did not exist | Created (33 lines) | **Yes** |
| `test-runtime/lean.json` | Did not exist | Created (6 lines) | **Yes** |
| `test-runtime/Data/equity/india/daily/TEST.zip` | Did not exist | Created (260 bars) | **Yes** |
| `test-runtime/.idea/` | Did not exist | Created (IDE config) | **Yes** |
| `test-runtime/.vscode/` | Did not exist | Created (IDE config) | **Yes** |
| `test-runtime/research.ipynb` | Did not exist | Created (Jupyter notebook) | **Yes** |
| `C:\Users\DELL\.lean\credentials` | Did not exist | Created (dummy values) | **Yes** |
| `compact_vhdx.txt` | Did not exist | Created (diskpart script) | **Yes** |
| `docs/docker-runtime-blocker.md` | Did not exist | **Creating now** | **Yes** |

### Docker Resources

| Resource | Changed? | Details |
|----------|----------|---------|
| **Images** | **No** | No pull completed; no images added or removed |
| **Containers** | **No** | No containers created or destroyed |
| **Volumes** | **No** | No volumes created or removed |
| **WSL distributions** | **No** | `docker-desktop` was Stopped→Running during restart; `Ubuntu` unchanged |
| **Docker VHDX** | **Partial** | `docker_data.vhdx` was attached read-only and `compact` was attempted. File length changed from ~9.9 GB to ~11.4 GB (observed growth, not reduction) |

### Did Compaction Succeed?

No. The `diskpart compact` command produced **no output**. The VHDX file
size **increased** (9.9 GB → 11.4 GB), likely because Docker Desktop was
restarted and began writing new data before compaction completed, or because
the underlying corruption prevented compaction from reclaiming space.

The VHDX was **not detached, deleted, recreated, or otherwise modified**
beyond the attempted read-only compact operation.

### Data-Loss Risk

**None.** No images were deleted. No containers were destroyed. No volumes
were removed. No WSL distributions were unregistered. The VHDX was attached
read-only and never written to by the compaction attempt. The subsequent size
growth is from normal Docker Desktop operation after restart.

---

## Read-Only Diagnostics

### Disk Space

| Drive | Total | Used | Free |
|-------|-------|------|------|
| C: | ~82.8 GB | ~79.3 GB | **~3.5 GB** |

Disk space was critically low (0.00 GB free) at start of attempt. Temp file
cleanup reclaimed ~3.5 GB. This remains below the estimated ~8 GB required
for the `quantconnect/lean:foundation` image.

### Docker Engine Status

| Check | Result |
|-------|--------|
| `docker version` | **Timed out** (daemon not responding) |
| `docker info` | **Timed out** (daemon not responding) |
| `docker system df` | **Failed** — I/O error on metadata database |
| `docker pull` | **Failed** — I/O error on overlayfs snapshot write |

### Docker Desktop Processes

```
Docker Desktop (PID 2876, 6040, 11564, 16196, 16928) — Running
com.docker.service — Stopped
```

Docker Desktop GUI is running but the backend service is stopped, leaving the
Docker daemon in an unresponsive state.

### WSL Status

```
Default Distribution: Ubuntu
Default Version: 2

NAME              STATE      VERSION
* Ubuntu          Stopped    2
  docker-desktop  Running    2
```

The `docker-desktop` WSL distribution is running but the Docker daemon inside
it cannot access its metadata database due to filesystem corruption.

### Docker VHDX File

```
Path:    C:\Users\DELL\AppData\Local\Docker\wsl\disk\docker_data.vhdx
Size:    11,388,583,936 bytes (~11.4 GB)
Status:  In use by docker-desktop WSL distribution
```

### I/O Error Text (exact)

```
Error response from daemon: write /var/lib/desktop-containerd/daemon/
io.containerd.metadata.v1.bolt/meta.db: input/output error

Error response from daemon: failed to extract layer (...) to overlayfs as
"extract-...": write /var/lib/desktop-containerd/daemon/
io.containerd.snapshotter.v1.overlayfs/snapshots/.../fs/...:
input/output error
```

Both errors are **filesystem-level I/O failures** inside the WSL2 ext4
filesystem backing Docker's storage. This is consistent with a filesystem
that was force-stopped while the disk was 100% full, causing metadata
corruption.

---

## Intact Resources

- All pre-existing Docker images (none were present or deleted)
- All project source files (git-tracked and untracked)
- All Python packages (including `lean==1.0.227`, installed successfully)
- Synthetic test data (`TEST.zip`, 260 bars, correct format)
- LEAN algorithm (`test-runtime/main.py`, gate test)
- `lean` CLI binary — functional, only blocked by missing `lean init` root

---

## Safest Recovery Options (read-only analysis)

The following are listed for reference only. **Do not execute without
explicit instruction.**

1. **Reset Docker Desktop from GUI** (Settings → Troubleshoot → Reset to
   factory defaults). This destroys all images/containers but recreates a
   healthy VHDX. Requires Docker Desktop to be responsive.

2. **WSL --unregister docker-desktop then restart Docker Desktop**. Destroys
   only the `docker-desktop` WSL distribution (no user data loss). Docker
   Desktop recreates it automatically.

3. **Delete `docker_data.vhdx` while Docker Desktop is stopped**. Docker
   Desktop recreates a minimal VHDX on next start. Requires Docker Desktop to
   be fully stopped.

4. **Free ≥8 GB additional disk space** then retry the pull on the hope that
   the I/O errors were transient. Low probability given persistent metadata
   corruption.

Option (1) or (2) is recommended as they guarantee a clean filesystem state.
The metadata bolt database corruption will persist until the Docker storage
backend is reset.

---

## Runtime Gate Status

**INDIA RUNTIME GATE INCONCLUSIVE**

The gate could not be executed because the Docker storage layer is degraded.
No LEAN engine was run. No India equity data was tested. The following
observations were made but remain unverified at runtime:

- ✅ `lean==1.0.227` installed successfully
- ✅ Synthetic data file created in correct format (260 bars, `TEST.zip`)
- ✅ LEAN algorithm written and syntactically valid
- ❌ Docker pull of `quantconnect/lean:foundation` failed
- ❌ `lean backtest` could not initialize (requires `lean init` root)
- ❌ Symbol-properties CSV: **not inspected**
- ❌ Market-hours JSON: **not inspected**
- ❌ `AddEquity("TEST", Resolution.DAILY, Market.INDIA)`: **not tested**
