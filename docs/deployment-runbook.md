# Deployment Runbook (Docker, LEAN, DhanHQ)

---

## 1. Docker Engine Installation Rules
1. Install Docker Engine exclusively from Docker's official Ubuntu repository (`download.docker.com`).
2. Do not overwrite the pristine baseline manifest. Record post-Docker package changes separately in [`docs/package-baseline-after-docker.txt`](./package-baseline-after-docker.txt).
3. Enable Docker via UNIX socket only. **Never expose Docker over an unauthenticated TCP socket**.
4. **Security Warning**: Membership in the `docker` group effectively grants root-level control of the host. Explain security implications to user before adding `hacker`.
5. Validate installation against all verification gates.

---

## 2. Docker Rollback Procedures

Before installation:
- Record existing APT sources.
- Record installed Docker-related packages.
- Record enabled services.

If installation verification fails:
- Stop Docker and containerd.
- Purge only packages installed during this phase.
- Remove the Docker repository only after confirming no project data exists.
- **Do not delete `/var/lib/docker` without explicit approval**.

---

## 3. Docker Verification Gates

Docker installation is complete only when:
- `docker version` succeeds.
- `docker info` succeeds.
- `systemctl is-active docker` returns `active`.
- `systemctl is-enabled docker` returns `enabled`.
- `docker run --rm hello-world` exits successfully.
- No Docker TCP listener exists.
- Exact Docker and containerd versions are recorded in [`docs/package-baseline-after-docker.txt`](./package-baseline-after-docker.txt).

---

## 4. LEAN Engine Container Rules
1. Source LEAN Engine strictly from pinned commit `1fee999e4f437d09e255be5c3fde783206e05389` (per [`AGENTS.md`](../AGENTS.md)).
2. Build runtime Docker images locally with specific tags and OCI provenance labels. Never use `latest`.
3. Perform minimal LEAN smoke test before full deployment.

---

## 5. Credential & Secrets Governance
1. Keep DhanHQ credentials, SSH keys, and API tokens strictly outside Git and Docker images.
2. Use environment files excluded by `.gitignore` or secret management mechanisms.

