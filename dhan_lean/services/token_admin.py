import base64
import getpass
import hashlib
import hmac
import http.cookies
import html
import json
import logging
import os
import secrets
import sys
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, List

from dhan_lean.security.token_store import (
    check_token_configured,
    save_dhan_token,
    TokenStoreError,
    PermissionDeniedError,
    SymlinkNotAllowedError,
    InvalidTokenError,
)

logger = logging.getLogger("dhan_lean.services.token_admin")


def generate_scrypt_hash(password: str, n: int = 16384, r: int = 8, p: int = 1, salt_len: int = 16) -> str:
    """
    Generates a versioned scrypt hash configuration string from a plaintext password.
    Format: scrypt$<n>$<r>$<p>$<salt-base64>$<derived-key-base64>
    """
    if not password or not isinstance(password, str):
        raise ValueError("Password must be a non-empty string.")

    salt = secrets.token_bytes(salt_len)
    derived_key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)

    salt_b64 = base64.b64encode(salt).decode("ascii")
    key_b64 = base64.b64encode(derived_key).decode("ascii")

    return f"scrypt${n}${r}${p}${salt_b64}${key_b64}"


def parse_and_verify_scrypt_hash(password: str, hash_config: str) -> bool:
    """
    Parses scrypt configuration string and verifies password using hmac.compare_digest.
    Fails closed on any format or decoding error.
    """
    if not password or not hash_config or not isinstance(hash_config, str):
        return False

    parts = hash_config.strip().split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False

    try:
        n = int(parts[1])
        r = int(parts[2])
        p = int(parts[3])
        salt = base64.b64decode(parts[4].encode("ascii"))
        expected_key = base64.b64decode(parts[5].encode("ascii"))

        if n < 1024 or r < 1 or p < 1 or len(salt) < 8 or len(expected_key) < 16:
            return False

        derived_key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected_key))
        return hmac.compare_digest(derived_key, expected_key)
    except Exception:
        return False


@dataclass
class TokenAdminConfig:
    """Configuration for TokenAdminServer."""
    host: str = "127.0.0.1"
    port: int = 8080
    admin_password_hash: Optional[str] = None
    env_path: Path = Path("/home/hacker/.config/dhan-lean/dhan.env")
    session_ttl_seconds: int = 900  # 15 minutes
    is_https: bool = False
    allow_unsafe_bind_all: bool = False
    max_failed_logins: int = 5
    login_lockout_seconds: int = 600  # 10 minutes
    max_token_submissions: int = 5
    submission_window_seconds: int = 600  # 10 minutes


@dataclass
class Session:
    session_id: str
    csrf_token: str
    created_at: float
    expires_at: float

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class TokenAdminRequestHandler(BaseHTTPRequestHandler):
    server: "TokenAdminServer"

    def log_message(self, format_str: str, *args: Any) -> None:
        """
        Safe status-only HTTP request logging.
        Never logs request bodies, query strings, tokens, passwords, cookies, or CSRF tokens.
        """
        code = args[1] if len(args) > 1 else "-"
        method = self.command if hasattr(self, "command") and self.command else "UNKNOWN"
        path = self.path.split("?")[0] if hasattr(self, "path") and self.path else "/"
        logger.info(f"[TokenAdmin] {method} {path} - Status {code}")

    def log_error(self, format_str: str, *args: Any) -> None:
        logger.error(f"[TokenAdmin] Error: {format_str % args}")

    def _send_security_headers(self) -> None:
        """Applies mandatory browser security headers to every HTTP response."""
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")

    def _get_client_ip(self) -> str:
        client_address = getattr(self, "client_address", None)
        if client_address and isinstance(client_address, tuple) and len(client_address) > 0:
            return client_address[0]
        return "127.0.0.1"

    def _parse_cookies(self) -> http.cookies.SimpleCookie:
        cookie_header = self.headers.get("Cookie", "")
        cookie = http.cookies.SimpleCookie()
        if cookie_header:
            try:
                cookie.load(cookie_header)
            except Exception:
                pass
        return cookie

    def _get_current_session(self) -> Optional[Session]:
        cookies = self._parse_cookies()
        if "session_id" in cookies:
            session_id = cookies["session_id"].value
            return self.server.get_session(session_id)
        return None

    def _read_post_body(self) -> Tuple[Dict[str, str], bool]:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except (ValueError, TypeError):
            return {}, False

        if content_length <= 0 or content_length > 10000:
            return {}, False

        body_bytes = self.rfile.read(content_length)
        body_str = body_bytes.decode("utf-8", errors="ignore")
        parsed = urllib.parse.parse_qs(body_str, keep_blank_values=True)
        result = {k: v[0] if v else "" for k, v in parsed.items()}
        return result, True

    def _respond_html(self, html_content: str, status_code: int = 200, set_cookie: Optional[str] = None) -> None:
        content_bytes = html_content.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content_bytes)))
        self._send_security_headers()
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(content_bytes)

    def _redirect(self, location: str, set_cookie: Optional[str] = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self._send_security_headers()
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()

    def do_GET(self) -> None:
        clean_path = self.path.split("?")[0]
        session = self._get_current_session()

        if clean_path == "/login":
            if session and not session.is_expired():
                self._redirect("/")
                return
            self._render_login_page()
            return

        if not session or session.is_expired():
            self._redirect("/login")
            return

        if clean_path == "/":
            self._render_admin_page(session)
            return

        if clean_path == "/logout":
            # GET /logout does NOT invalidate session or clear cookies.
            # Redirects to home page if logged in, or /login if unauthenticated.
            self._redirect("/")
            return

        self._respond_html("<h1>404 Not Found</h1>", status_code=404)

    def do_POST(self) -> None:
        clean_path = self.path.split("?")[0]
        client_ip = self._get_client_ip()

        if clean_path == "/login":
            if self.server.is_login_locked_out(client_ip):
                self._render_login_page(error_msg="Too many failed login attempts. Please try again later.")
                return

            body, ok = self._read_post_body()
            if not ok:
                self._render_login_page(error_msg="Invalid request payload.")
                return

            password = body.get("password", "")
            if self.server.verify_password(password):
                new_session = self.server.create_session()
                cookie_parts = [
                    f"session_id={new_session.session_id}",
                    "Path=/",
                    "HttpOnly",
                    "SameSite=Strict"
                ]
                if self.server.config.is_https:
                    cookie_parts.append("Secure")
                cookie_str = "; ".join(cookie_parts)
                self._redirect("/", set_cookie=cookie_str)
            else:
                self.server.record_login_failure(client_ip)
                self._render_login_page(error_msg="Invalid password.")
            return

        # Protected POST routes
        session = self._get_current_session()
        if not session or session.is_expired():
            self._redirect("/login")
            return

        if clean_path == "/logout":
            body, ok = self._read_post_body()
            if not ok:
                self._render_admin_page(session, error_msg="Invalid logout request payload.")
                return

            submitted_csrf = body.get("csrf_token", "")
            if not submitted_csrf or not hmac.compare_digest(submitted_csrf, session.csrf_token):
                self._render_admin_page(session, error_msg="CSRF verification failed. Logout rejected.")
                return

            # Valid authenticated POST logout
            self.server.invalidate_session(session.session_id)
            cookie_str = "session_id=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Strict"
            self._redirect("/login", set_cookie=cookie_str)
            return

        if clean_path == "/update-token":
            if self.server.is_submission_rate_limited(client_ip):
                self._render_admin_page(session, error_msg="Too many token submission attempts. Please wait before trying again.")
                return

            body, ok = self._read_post_body()
            if not ok:
                self._render_admin_page(session, error_msg="Invalid request payload.")
                return

            # CSRF Check
            submitted_csrf = body.get("csrf_token", "")
            if not submitted_csrf or not hmac.compare_digest(submitted_csrf, session.csrf_token):
                self._render_admin_page(session, error_msg="CSRF verification failed. Form submission rejected.")
                return

            token = body.get("token", "")
            self.server.record_submission_attempt(client_ip)

            try:
                save_dhan_token(self.server.config.env_path, token)
                self._render_admin_page(session, success_msg="Dhan access token saved successfully.")
            except InvalidTokenError as e:
                self._render_admin_page(session, error_msg=f"Token validation failed: {e}")
            except PermissionDeniedError:
                self._render_admin_page(session, error_msg="Permission denied writing credential file.")
            except SymlinkNotAllowedError:
                self._render_admin_page(session, error_msg="Symbolic links are not permitted for environment configuration.")
            except TokenStoreError:
                self._render_admin_page(session, error_msg="Failed to save access token due to storage error.")
            except Exception:
                self._render_admin_page(session, error_msg="An unexpected error occurred while saving the token.")
            return

        self._respond_html("<h1>404 Not Found</h1>", status_code=404)

    def _render_login_page(self, error_msg: Optional[str] = None) -> None:
        error_html = f'<div class="banner error">{html.escape(error_msg)}</div>' if error_msg else ""
        content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dhan Admin — Login</title>
<style>
:root {{
    --bg: #0f172a;
    --card: #1e293b;
    --text: #f8fafc;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --accent-hover: #0284c7;
    --error-bg: #451a03;
    --error-border: #f97316;
    --error-text: #fdba74;
    --border: #334155;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background-color: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    padding: 1rem;
}}
.card {{
    background-color: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 2.5rem;
    width: 100%;
    max-width: 400px;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
}}
h1 {{ font-size: 1.5rem; font-weight: 600; margin-bottom: 0.5rem; text-align: center; }}
p.sub {{ color: var(--muted); font-size: 0.875rem; text-align: center; margin-bottom: 2rem; }}
.banner {{
    padding: 0.75rem 1rem;
    border-radius: 6px;
    font-size: 0.875rem;
    margin-bottom: 1.5rem;
}}
.banner.error {{ background-color: var(--error-bg); border: 1px solid var(--error-border); color: var(--error-text); }}
.form-group {{ margin-bottom: 1.5rem; }}
label {{ display: block; font-size: 0.875rem; font-weight: 500; margin-bottom: 0.5rem; color: var(--muted); }}
input[type="password"] {{
    width: 100%;
    padding: 0.75rem 1rem;
    background-color: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 1rem;
    outline: none;
}}
input[type="password"]:focus {{ border-color: var(--accent); }}
button {{
    width: 100%;
    padding: 0.75rem 1rem;
    background-color: var(--accent);
    color: #000;
    font-weight: 600;
    border: none;
    border-radius: 6px;
    font-size: 1rem;
    cursor: pointer;
    transition: background-color 0.2s;
}}
button:hover {{ background-color: var(--accent-hover); }}
</style>
</head>
<body>
<div class="card">
    <h1>Dhan Token Admin</h1>
    <p class="sub">Authentication Required</p>
    {error_html}
    <form method="POST" action="/login">
        <div class="form-group">
            <label for="password">Admin Password</label>
            <input type="password" id="password" name="password" required autocomplete="current-password">
        </div>
        <button type="submit">Log In</button>
    </form>
</div>
</body>
</html>"""
        self._respond_html(content, status_code=200 if not error_msg else 401)

    def _render_admin_page(
        self,
        session: Session,
        success_msg: Optional[str] = None,
        error_msg: Optional[str] = None
    ) -> None:
        is_configured = False
        try:
            is_configured = check_token_configured(self.server.config.env_path)
        except Exception:
            is_configured = False

        status_badge = '<span class="pill pill-green">● Configured</span>' if is_configured else '<span class="pill pill-red">○ Not Configured</span>'

        banner_html = ""
        if success_msg:
            banner_html = f'<div class="banner success">{html.escape(success_msg)}</div>'
        elif error_msg:
            banner_html = f'<div class="banner error">{html.escape(error_msg)}</div>'

        content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dhan Admin — Token Manager</title>
<style>
:root {{
    --bg: #0f172a;
    --card: #1e293b;
    --text: #f8fafc;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --accent-hover: #0284c7;
    --success-bg: #064e3b;
    --success-border: #10b981;
    --success-text: #6ee7b7;
    --error-bg: #451a03;
    --error-border: #f97316;
    --error-text: #fdba74;
    --border: #334155;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background-color: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    padding: 1rem;
}}
.card {{
    background-color: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 2.5rem;
    width: 100%;
    max-width: 520px;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
}}
.header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border);
}}
h1 {{ font-size: 1.25rem; font-weight: 600; }}
.logout-form {{ display: inline; margin: 0; padding: 0; }}
.logout-btn {{
    color: var(--muted);
    font-size: 0.875rem;
    background: none;
    border: 1px solid var(--border);
    padding: 0.25rem 0.6rem;
    border-radius: 4px;
    cursor: pointer;
}}
.logout-btn:hover {{ color: var(--text); background-color: var(--border); }}
.status-row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    background-color: var(--bg);
    padding: 0.75rem 1rem;
    border-radius: 6px;
    margin-bottom: 1.5rem;
}}
.status-label {{ font-size: 0.875rem; color: var(--muted); }}
.pill {{
    font-size: 0.75rem;
    font-weight: 600;
    padding: 0.25rem 0.6rem;
    border-radius: 9999px;
    text-transform: uppercase;
}}
.pill-green {{ background-color: #064e3b; color: #34d399; border: 1px solid #059669; }}
.pill-red {{ background-color: #451a03; color: #fb923c; border: 1px solid #ea580c; }}
.banner {{
    padding: 0.75rem 1rem;
    border-radius: 6px;
    font-size: 0.875rem;
    margin-bottom: 1.5rem;
}}
.banner.success {{ background-color: var(--success-bg); border: 1px solid var(--success-border); color: var(--success-text); }}
.banner.error {{ background-color: var(--error-bg); border: 1px solid var(--error-border); color: var(--error-text); }}
.form-group {{ margin-bottom: 1.5rem; }}
label {{ display: block; font-size: 0.875rem; font-weight: 500; margin-bottom: 0.5rem; color: var(--muted); }}
input[type="password"] {{
    width: 100%;
    padding: 0.75rem 1rem;
    background-color: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    font-size: 0.875rem;
    outline: none;
    font-family: monospace;
}}
input[type="password"]:focus {{ border-color: var(--accent); }}
button.submit-btn {{
    width: 100%;
    padding: 0.75rem 1rem;
    background-color: var(--accent);
    color: #000;
    font-weight: 600;
    border: none;
    border-radius: 6px;
    font-size: 0.875rem;
    cursor: pointer;
    transition: background-color 0.2s;
}}
button.submit-btn:hover {{ background-color: var(--accent-hover); }}
.footer-note {{ margin-top: 1.5rem; font-size: 0.75rem; color: var(--muted); text-align: center; line-height: 1.4; }}
</style>
</head>
<body>
<div class="card">
    <div class="header">
        <h1>Dhan Token Manager</h1>
        <form method="POST" action="/logout" class="logout-form">
            <input type="hidden" name="csrf_token" value="{session.csrf_token}">
            <button type="submit" class="logout-btn">Log out</button>
        </form>
    </div>

    <div class="status-row">
        <span class="status-label">Current Token Status</span>
        {status_badge}
    </div>

    {banner_html}

    <form method="POST" action="/update-token">
        <input type="hidden" name="csrf_token" value="{session.csrf_token}">
        <div class="form-group">
            <label for="token">New Dhan Access Token</label>
            <input type="password" id="token" name="token" placeholder="Paste new access token here" required autocomplete="off">
        </div>
        <button type="submit" class="submit-btn">Save Token</button>
    </form>

    <div class="footer-note">
        Token will be saved atomically with 0600 mode permissions to<br>
        <code>{html.escape(str(self.server.config.env_path))}</code>
    </div>
</div>
</body>
</html>"""
        self._respond_html(content, status_code=200)


class TokenAdminServer(HTTPServer):
    """
    Standalone HTTP Server for private Dhan token administration.
    """
    def __init__(self, config: TokenAdminConfig):
        # Security Guard: Root Check
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise PermissionError("TokenAdminServer must never run as root user.")

        # Security Guard: Binding check
        if config.host == "0.0.0.0" and not config.allow_unsafe_bind_all:
            raise ValueError("Binding to 0.0.0.0 is rejected for security. Specify loopback (127.0.0.1) or Tailscale IP address.")

        # Security Guard: Authentication check (Fail Closed)
        if not config.admin_password_hash or not isinstance(config.admin_password_hash, str):
            raise ValueError("TokenAdminServer requires a valid scrypt password hash configuration (scrypt$<n>$<r>$<p>$<salt>$<key>). Startup failed closed.")

        parts = config.admin_password_hash.strip().split("$")
        if len(parts) != 6 or parts[0] != "scrypt":
            raise ValueError("TokenAdminServer rejects legacy or invalid password hash formats. Strict scrypt format required.")

        self.config = config
        self.sessions: Dict[str, Session] = {}
        self.login_failures: Dict[str, List[float]] = {}
        self.submission_attempts: Dict[str, List[float]] = {}

        super().__init__((config.host, config.port), TokenAdminRequestHandler)

    def verify_password(self, password: str) -> bool:
        return parse_and_verify_scrypt_hash(password, self.config.admin_password_hash)

    def create_session(self) -> Session:
        session_id = secrets.token_hex(32)
        csrf_token = secrets.token_hex(32)
        now = time.time()
        session = Session(
            session_id=session_id,
            csrf_token=csrf_token,
            created_at=now,
            expires_at=now + self.config.session_ttl_seconds
        )
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[Session]:
        session = self.sessions.get(session_id)
        if not session:
            return None
        if session.is_expired():
            del self.sessions[session_id]
            return None
        return session

    def invalidate_session(self, session_id: str) -> None:
        if session_id in self.sessions:
            del self.sessions[session_id]

    def is_login_locked_out(self, ip: str) -> bool:
        now = time.time()
        window = self.config.login_lockout_seconds
        attempts = [t for t in self.login_failures.get(ip, []) if now - t < window]
        self.login_failures[ip] = attempts
        return len(attempts) >= self.config.max_failed_logins

    def record_login_failure(self, ip: str) -> None:
        now = time.time()
        attempts = self.login_failures.get(ip, [])
        attempts.append(now)
        self.login_failures[ip] = attempts

    def is_submission_rate_limited(self, ip: str) -> bool:
        now = time.time()
        window = self.config.submission_window_seconds
        attempts = [t for t in self.submission_attempts.get(ip, []) if now - t < window]
        self.submission_attempts[ip] = attempts
        return len(attempts) >= self.config.max_token_submissions

    def record_submission_attempt(self, ip: str) -> None:
        now = time.time()
        attempts = self.submission_attempts.get(ip, [])
        attempts.append(now)
        self.submission_attempts[ip] = attempts


def main() -> None:
    """CLI entry point for hash generation and running the admin server."""
    if len(sys.argv) > 1 and sys.argv[1] == "--generate-password-hash":
        pwd1 = getpass.getpass("Enter admin password: ")
        pwd2 = getpass.getpass("Confirm admin password: ")
        if not pwd1 or pwd1 != pwd2:
            print("Error: Passwords do not match or are empty.", file=sys.stderr)
            sys.exit(1)
        hash_val = generate_scrypt_hash(pwd1)
        print("\nGenerated scrypt password hash configuration:")
        print(hash_val)
        sys.exit(0)


if __name__ == "__main__":
    main()
