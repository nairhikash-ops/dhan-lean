# Infrastructure Completion & Baseline Snapshot Plan

## Goal Description
Complete Tailscale remote node authentication, verify external SSH over the Tailscale `100.x.x.x` address, create a pristine system configuration archive (`fresh-server-baseline.tar.gz`), and record version pins in `docs/lean-version-matrix.md` before installing Docker.

---

## Action Plan

### Step 1: Tailscale Node Authentication & Remote SSH Verification
1. Execute `sudo tailscale up` on `swing-server` to obtain the auth URL:
   ```bash
   sudo tailscale up
   ```
2. Display the authentication URL so it can be approved in the Tailscale web console.
3. Once approved, confirm Tailscale IP and status:
   ```bash
   tailscale status
   tailscale ip -4
   ```
4. Verify remote SSH from local Windows machine using the assigned `100.x.x.x` address:
   ```powershell
   ssh -i C:\Users\DELL\.ssh\id_ed25519 hacker@<TAILSCALE_IP> "echo TAILSCALE_SSH_SUCCESS"
   ```

---

### Step 2: Create Pristine System Baseline Archive
Package configuration files and package manifests into `/root/fresh-server-baseline.tar.gz`:
```bash
sudo tar czf /root/fresh-server-baseline.tar.gz \
  package-baseline-manual.txt \
  package-baseline-full.txt \
  enabled-services-baseline.txt \
  /etc
```
Verify archive creation and size.

---

### Step 3: Version Pinning & Pre-Docker Audit
Before installing Docker, inspect and record all version pins in `docs/lean-version-matrix.md`:
- Docker Engine version pin
- LEAN Engine commit tag (`1fee999e4f437d09e255be5c3fde783206e05389` per AGENTS.md rule)
- PyPI CLI version pin
- System Python baseline (`3.14.0`)

---

## Verification Plan

### Test Commands
- `tailscale status` & `tailscale ip -4`
- `ssh -i C:\Users\DELL\.ssh\id_ed25519 hacker@100.x.x.x`
- `sudo test -s /root/fresh-server-baseline.tar.gz`
