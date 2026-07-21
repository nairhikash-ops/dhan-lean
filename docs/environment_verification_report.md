# Fresh Server Environment Verification Report (Completed Infrastructure)

## Generated: 2026-07-21

---

## 1. Verified System Specifications (CONFIRMED BY TEST)
- **OS Release**: Ubuntu 26.04 LTS (`x86_64`)
- **Kernel**: `7.0.0-28-generic`
- **CPU**: Intel(R) Core(TM) i5-2430M @ 2.40GHz (2 physical cores, 4 threads)
- **Memory**: 7.2 GiB total RAM
- **Disk Storage**: `/` root partition 116 GiB total (101 GiB free)
- **LAN SSH Access**: Verified (`10.40.2.24`) with key-based authentication (`id_ed25519`).
- **Tailscale Remote Access**: Verified (`100.121.84.8`), status `Connected` (Tailscale v1.98.9).

---

## 2. Pristine Baselines & Archives (CONFIRMED BY TEST)
- **Host Archive Snapshot**: `/root/fresh-server-baseline.tar.gz`
- **Manual Packages**: [`package-baseline-manual.txt`](./package-baseline-manual.txt)
- **Full Installed Packages**: [`package-baseline-full.txt`](./package-baseline-full.txt)
- **Enabled Services**: [`enabled-services-baseline.txt`](./enabled-services-baseline.txt)

---

## 3. Version Matrix Alignment (`CONFIRMED BY AGENTS.md & SOURCE CODE`)
- **LEAN Engine Commit**: Pinned to `1fee999e4f437d09e255be5c3fde783206e05389` in [`lean-version-matrix.md`](./lean-version-matrix.md).
- **DhanHQ SDK**: Pinned to stable `dhanhq==2.2.0`.
- **Docker Engine Setup**: Ready for pinned installation.
