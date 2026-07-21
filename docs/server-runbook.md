# Server Maintenance & Recovery Runbook

> Target: `swingserver` (`100.121.84.8` / `10.40.2.24`)

---

## 1. Remote Access & Tailscale Recovery

### Preferred SSH Address
```powershell
ssh -i C:\Users\DELL\.ssh\id_ed25519 hacker@100.121.84.8
```

### LAN Fallback Address
```powershell
ssh -i C:\Users\DELL\.ssh\id_ed25519 hacker@10.40.2.24
```

### Tailscale Node Re-authentication
If Tailscale disconnects or requires re-authentication:
```bash
sudo tailscale up
```
Open the generated authentication URL in your browser and approve `swingserver`. Verify via `tailscale status` and `tailscale ip -4`.

---

## 2. Maintenance & Baseline Protection

### Package Baseline Check
- Manual packages: `package-baseline-manual.txt`
- Full package list: `package-baseline-full.txt`
- Enabled services: `enabled-services-baseline.txt`
- Recovery archive: `/root/fresh-server-baseline.tar.gz` and local backup `D:\fresh-server-baseline.tar.gz`

### System Health Inspection
```bash
sudo apt-get check
sudo dpkg --audit
systemctl --failed
df -h
```
