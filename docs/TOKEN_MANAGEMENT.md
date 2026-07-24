# Private Dhan Token-Management Service

This document describes the design, operational instructions, security boundaries, and deployment requirements for the standalone Dhan Access Token Admin Web Service (`dhan_lean.services.token_admin`).

---

## Overview & Architecture

The Token Admin service provides a secure, minimal web interface allowing authorized administrators to replace the Dhan V2 access token (`DHAN_ACCESS_TOKEN`) in `/home/hacker/.config/dhan-lean/dhan.env` without requiring direct SSH shell access or manual file editing.

### Key Architectural Principles
1. **Zero External Frontend/Web Frameworks**: Implemented using standard Python `http.server` to keep the dependency footprint zero.
2. **Atomic File Mutation**: Token updates use temporary files, `0600` permissions, `fsync`, and `os.replace` to prevent partial writes, corruption, or permission leaks.
3. **Zero Token Reflection**: The current or updated access token is **never** echoed in HTML responses, HTTP headers, exceptions, terminal logs, or command history. Form inputs use `<input type="password">`.
4. **Root Refusal**: The server strictly refuses to start under root privileges (`uid == 0`).
5. **Strict `scrypt` Password Hashing**: Password authentication uses Python `hashlib.scrypt` with random salt and constant-time `hmac.compare_digest`. Legacy plain SHA-256 or plaintext password configurations are rejected.
6. **Protected POST-only Logout**: Logout requires an authenticated session and a valid session CSRF token via `POST /logout`. `GET /logout` does not mutate session state.

---

## Password Hash Generation & Server Execution

### 1. Generating an Admin Password Hash
Generate a versioned `scrypt` password hash configuration using the interactive CLI helper:

```bash
python -m dhan_lean.services.token_admin --generate-password-hash
```

Output format:
`scrypt$16384$8$1$<salt-base64>$<derived-key-base64>`

### 2. Local Development / Testing
To run locally on loopback (`127.0.0.1`):

```bash
python -c "
from pathlib import Path
from dhan_lean.services.token_admin import TokenAdminServer, TokenAdminConfig

config = TokenAdminConfig(
    host='127.0.0.1',
    port=8080,
    admin_password_hash='scrypt$16384$8$1$...',
    env_path=Path('/tmp/dhan.env')
)
server = TokenAdminServer(config)
print('TokenAdminServer running on http://127.0.0.1:8080')
server.serve_forever()
"
```

### 3. Tailscale-Only Binding (VPS / Swingserver)
When deployed on swingserver (`swingserver`), the service must bind **only** to the private Tailscale interface IP (`100.121.84.8`).

```bash
python -c "
from pathlib import Path
from dhan_lean.services.token_admin import TokenAdminServer, TokenAdminConfig

config = TokenAdminConfig(
    host='100.121.84.8',
    port=8080,
    admin_password_hash='scrypt$16384$8$1$...',
    env_path=Path('/home/hacker/.config/dhan-lean/dhan.env')
)
server = TokenAdminServer(config)
server.serve_forever()
"
```

---

## Security Boundaries & Controls

- **Fail-Closed Authentication**: Server startup fails immediately if no valid `scrypt` password hash configuration is supplied. Legacy plain SHA-256 strings are rejected.
- **Constant-Time Verification**: Password verification derives the submitted password with configured `scrypt` parameters and compares key hashes using `hmac.compare_digest`.
- **Session Protection**: Sessions use cryptographically random 256-bit hex IDs (`secrets.token_hex(32)`), expiration timeouts (default 15 mins), and `HttpOnly` / `SameSite=Strict` cookie flags.
- **CSRF Defense**: Form actions (`/update-token` and `/logout`) require a per-session cryptographic CSRF token validated via `hmac.compare_digest`. Missing or invalid CSRF tokens leave sessions active and reject the request.
- **Browser Security Headers**: All responses include `Cache-Control: no-store`, `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, and `X-Frame-Options: DENY`.
- **Safe Logging**: HTTP request logging records only safe HTTP status codes. Request bodies, query strings, headers, passwords, cookies, CSRF tokens, and access tokens are never logged.
- **Interface Restriction**: Binding to `0.0.0.0` is strictly rejected by default.

---

## Why Public Exposure is Forbidden

This service must **NEVER** be exposed to the public internet, published behind unauthenticated reverse proxies, or bound to `0.0.0.0`.

### Rationale:
1. **Critical Privilege**: Possessing the Dhan access token allows executing orders and fetching account historical/live data.
2. **Defense in Depth**: Restricting network access to loopback (`127.0.0.1`) or the encrypted Tailscale mesh (`100.121.84.8`) ensures that only authenticated devices on the private Tailscale network can reach the server socket.

---

## Deployment & Permission Model

### One-Time Administrator Deployment Requirement
The application process runs under the non-root `hacker` service user and will **never** invoke `sudo` or modify file ownership automatically.

Before deploying the service on swingserver, a one-time administrator setup action is required to ensure the target directory and file are owned by `hacker` with `0600` permissions:

```bash
# Executed once by system administrator on swingserver:
mkdir -p /home/hacker/.config/dhan-lean
touch /home/hacker/.config/dhan-lean/dhan.env
chown -R hacker:hacker /home/hacker/.config/dhan-lean
chmod 700 /home/hacker/.config/dhan-lean
chmod 600 /home/hacker/.config/dhan-lean/dhan.env
```

If the service user lacks write permission, the application cleanly catches the `PermissionError` and reports `"Permission denied writing credential file"` in the web UI without exposing file paths or failing catastrophically.
