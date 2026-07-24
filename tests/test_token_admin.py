import http.client
import logging
import io
import os
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path

from dhan_lean.services.token_admin import (
    TokenAdminServer,
    TokenAdminConfig,
    generate_scrypt_hash,
    parse_and_verify_scrypt_hash,
)


class TestTokenAdmin(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.env_file = self.dir_path / "dhan.env"
        self.plain_password = "test_secure_admin_password_123"
        self.scrypt_hash = generate_scrypt_hash(self.plain_password)

        self.config = TokenAdminConfig(
            host="127.0.0.1",
            port=0,
            admin_password_hash=self.scrypt_hash,
            env_path=self.env_file,
            session_ttl_seconds=2
        )

        self.server = TokenAdminServer(self.config)
        self.port = self.server.server_port
        self.server_thread = threading.Thread(target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
        self.temp_dir.cleanup()

    def _request(
        self,
        method: str,
        path: str,
        body: str = None,
        headers: dict = None
    ) -> tuple[int, dict, str]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = headers or {}
        if body and "Content-Type" not in headers:
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        resp_headers = {k: v for k, v in response.getheaders()}
        resp_body = response.read().decode("utf-8", errors="ignore")
        conn.close()
        return response.status, resp_headers, resp_body

    def test_scrypt_hash_generation_and_verification(self) -> None:
        pass_str = "MyComplexPassword#2026"
        hash_val = generate_scrypt_hash(pass_str)
        self.assertTrue(hash_val.startswith("scrypt$16384$8$1$"))

        # Valid password match
        self.assertTrue(parse_and_verify_scrypt_hash(pass_str, hash_val))

        # Invalid password mismatch
        self.assertFalse(parse_and_verify_scrypt_hash("WrongPassword", hash_val))

    def test_no_auth_secret_fails_closed_at_startup(self) -> None:
        invalid_config = TokenAdminConfig(
            host="127.0.0.1",
            port=0,
            admin_password_hash=None,
            env_path=self.env_file
        )
        with self.assertRaises(ValueError) as cm:
            TokenAdminServer(invalid_config)
        self.assertIn("requires a valid scrypt password hash", str(cm.exception))

    def test_malformed_and_legacy_sha256_scrypt_config_rejected(self) -> None:
        # Legacy plain SHA-256 hash
        sha256_hash = "ef92b778bafe771e89245b89ecbc08a44a4e166c06659911881f383d4473e94f"
        legacy_config = TokenAdminConfig(
            host="127.0.0.1",
            port=0,
            admin_password_hash=sha256_hash,
            env_path=self.env_file
        )
        with self.assertRaises(ValueError) as cm:
            TokenAdminServer(legacy_config)
        self.assertIn("rejects legacy or invalid password hash formats", str(cm.exception))

        # Malformed scrypt string
        bad_scrypt = "scrypt$16384$invalid$salt$key"
        bad_config = TokenAdminConfig(
            host="127.0.0.1",
            port=0,
            admin_password_hash=bad_scrypt,
            env_path=self.env_file
        )
        with self.assertRaises(ValueError):
            TokenAdminServer(bad_config)

    def test_zero_bind_rejected_by_default(self) -> None:
        unsafe_config = TokenAdminConfig(
            host="0.0.0.0",
            port=0,
            admin_password_hash=self.scrypt_hash,
            env_path=self.env_file,
            allow_unsafe_bind_all=False
        )
        with self.assertRaises(ValueError) as cm:
            TokenAdminServer(unsafe_config)
        self.assertIn("Binding to 0.0.0.0 is rejected", str(cm.exception))

    def test_tailscale_ip_binding_allowed(self) -> None:
        ts_config = TokenAdminConfig(
            host="100.121.84.8",
            port=0,
            admin_password_hash=self.scrypt_hash,
            env_path=self.env_file
        )
        self.assertEqual(ts_config.host, "100.121.84.8")

    def test_unauthenticated_request_redirected_to_login(self) -> None:
        status, headers, body = self._request("GET", "/")
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/login")

    def test_security_headers_present(self) -> None:
        status, headers, body = self._request("GET", "/login")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Cache-Control"), "no-store, no-cache, must-revalidate, max-age=0")
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")

    def test_scrypt_login_flow_and_session_creation(self) -> None:
        # Valid scrypt password
        payload = urllib.parse.urlencode({"password": self.plain_password})
        status, headers, body = self._request("POST", "/login", body=payload)
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/")

        cookie = headers.get("Set-Cookie", "")
        self.assertIn("session_id=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

        # Invalid password
        payload_bad = urllib.parse.urlencode({"password": "wrong_password"})
        status2, _, body2 = self._request("POST", "/login", body=payload_bad)
        self.assertEqual(status2, 401)
        self.assertIn("Invalid password", body2)

    def test_get_logout_does_not_invalidate_session(self) -> None:
        # 1. Login
        payload = urllib.parse.urlencode({"password": self.plain_password})
        _, headers, _ = self._request("POST", "/login", body=payload)
        cookie = headers.get("Set-Cookie").split(";")[0]

        # 2. GET /logout request
        status, _, _ = self._request("GET", "/logout", headers={"Cookie": cookie})
        self.assertEqual(status, 303)

        # 3. Verify session is STILL ACTIVE
        status, _, body = self._request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("Dhan Token Manager", body)

    def test_unauthenticated_post_logout_rejected(self) -> None:
        status, headers, _ = self._request("POST", "/logout")
        self.assertEqual(status, 303)
        self.assertEqual(headers.get("Location"), "/login")

    def test_post_logout_without_or_invalid_csrf_leaves_session_active(self) -> None:
        # 1. Login
        payload = urllib.parse.urlencode({"password": self.plain_password})
        _, headers, _ = self._request("POST", "/login", body=payload)
        cookie = headers.get("Set-Cookie").split(";")[0]

        # 2. POST /logout without CSRF (empty body)
        status, _, body = self._request("POST", "/logout", body="", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("Invalid logout request payload", body)

        # Session remains active
        status, _, _ = self._request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)

        # 3. POST /logout with bad CSRF
        payload_bad = urllib.parse.urlencode({"csrf_token": "invalid_csrf_token"})
        status, _, body = self._request("POST", "/logout", body=payload_bad, headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("CSRF verification failed", body)


        # Session remains active
        status, _, _ = self._request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)

    def test_valid_authenticated_post_logout_invalidates_session_and_clears_cookie(self) -> None:
        # 1. Login
        payload = urllib.parse.urlencode({"password": self.plain_password})
        _, headers, _ = self._request("POST", "/login", body=payload)
        cookie = headers.get("Set-Cookie").split(";")[0]

        # 2. GET admin page to extract CSRF token
        _, _, body = self._request("GET", "/", headers={"Cookie": cookie})
        csrf_token = body.split('name="csrf_token" value="')[1].split('"')[0]

        # 3. Valid POST /logout
        payload_logout = urllib.parse.urlencode({"csrf_token": csrf_token})
        status, headers2, _ = self._request("POST", "/logout", body=payload_logout, headers={"Cookie": cookie})

        self.assertEqual(status, 303)
        self.assertEqual(headers2.get("Location"), "/login")
        self.assertIn("Expires=Thu, 01 Jan 1970", headers2.get("Set-Cookie"))

        # 4. Access protected page again -> redirected
        status, _, _ = self._request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 303)

    def test_expired_session_rejected(self) -> None:
        payload = urllib.parse.urlencode({"password": self.plain_password})
        _, headers, _ = self._request("POST", "/login", body=payload)
        cookie = headers.get("Set-Cookie").split(";")[0]

        time.sleep(2.2)

        status, _, _ = self._request("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 303)

    def test_csrf_protection_blocks_token_submission(self) -> None:
        payload = urllib.parse.urlencode({"password": self.plain_password})
        _, headers, _ = self._request("POST", "/login", body=payload)
        cookie = headers.get("Set-Cookie").split(";")[0]

        payload_no_csrf = urllib.parse.urlencode({"token": "valid_dhan_token_12345"})
        status, _, body = self._request("POST", "/update-token", body=payload_no_csrf, headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("CSRF verification failed", body)

    def test_successful_token_update_via_post(self) -> None:
        payload = urllib.parse.urlencode({"password": self.plain_password})
        _, headers, _ = self._request("POST", "/login", body=payload)
        cookie = headers.get("Set-Cookie").split(";")[0]

        _, _, body = self._request("GET", "/", headers={"Cookie": cookie})
        csrf_token = body.split('name="csrf_token" value="')[1].split('"')[0]

        secret_token = "valid_secret_dhan_token_xyz"
        payload_update = urllib.parse.urlencode({"csrf_token": csrf_token, "token": secret_token})
        status, _, resp_body = self._request("POST", "/update-token", body=payload_update, headers={"Cookie": cookie})

        self.assertEqual(status, 200)
        self.assertIn("Dhan access token saved successfully", resp_body)

        self.assertTrue(self.env_file.exists())
        file_content = self.env_file.read_text(encoding="utf-8")
        self.assertIn(f"DHAN_ACCESS_TOKEN={secret_token}", file_content)
        self.assertNotIn(secret_token, resp_body)

    def test_submitted_passwords_and_hashes_never_appear_in_responses_or_logs(self) -> None:
        target_logger = logging.getLogger("dhan_lean.services.token_admin")
        log_capture = io.StringIO()
        handler = logging.StreamHandler(log_capture)
        target_logger.addHandler(handler)

        try:
            secret_token = "VERY_CONFIDENTIAL_TOKEN_ABC123"
            payload = urllib.parse.urlencode({"password": self.plain_password})
            status, headers, body1 = self._request("POST", "/login", body=payload)
            cookie = headers.get("Set-Cookie").split(";")[0]

            _, _, body2 = self._request("GET", "/", headers={"Cookie": cookie})
            csrf_token = body2.split('name="csrf_token" value="')[1].split('"')[0]

            payload_update = urllib.parse.urlencode({"csrf_token": csrf_token, "token": secret_token})
            status, _, body3 = self._request("POST", "/update-token", body=payload_update, headers={"Cookie": cookie})

            logs = log_capture.getvalue()
            responses = body1 + body2 + body3

            # Secrets check in responses & logs
            self.assertNotIn(self.plain_password, responses)
            self.assertNotIn(self.plain_password, logs)
            self.assertNotIn(self.scrypt_hash, responses)
            self.assertNotIn(self.scrypt_hash, logs)
            self.assertNotIn(secret_token, responses)
            self.assertNotIn(secret_token, logs)
        finally:
            target_logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
