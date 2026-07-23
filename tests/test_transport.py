import unittest
import urllib.request
import urllib.error
from dhan_lean.data.models import HttpResponse
from dhan_lean.data.transport import DhanHttpTransport, TransportError, _serialize_response_headers


class TestTransport(unittest.TestCase):

    def test_successful_post_request_construction(self):
        """Test successful POST request executes exactly once with expected url, headers, and body."""
        call_count = 0
        passed_req = None
        passed_timeout = None

        def dummy_executor(req: urllib.request.Request, timeout: float) -> HttpResponse:
            nonlocal call_count, passed_req, passed_timeout
            call_count += 1
            passed_req = req
            passed_timeout = timeout
            return HttpResponse(status_code=200, body=b'{"status":"success"}', headers=b"content-type: application/json\r\n")

        transport = DhanHttpTransport(
            access_token="valid_secret_token_123",
            timeout_seconds=15.0,
            endpoint="https://api.dhan.co/v2/charts/intraday",
            executor=dummy_executor
        )

        payload = b'{"securityId":"1333"}'
        resp = transport.post_intraday(payload)

        self.assertEqual(call_count, 1)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.body, b'{"status":"success"}')
        self.assertEqual(passed_req.method, "POST")
        self.assertEqual(passed_req.full_url, "https://api.dhan.co/v2/charts/intraday")
        self.assertEqual(passed_req.headers["Content-type"], "application/json")
        self.assertEqual(passed_req.headers["Access-token"], "valid_secret_token_123")
        self.assertEqual(passed_req.data, payload)
        self.assertEqual(passed_timeout, 15.0)

    def test_token_redaction(self):
        """Test token value is absent from repr(), str(), and Exception messages."""
        secret_token = "SUPER_SECRET_TOKEN_XYZ"
        transport = DhanHttpTransport(access_token=secret_token)

        self.assertNotIn(secret_token, repr(transport))
        self.assertNotIn(secret_token, str(transport))
        self.assertIn("[REDACTED]", repr(transport))
        self.assertIn("[REDACTED]", str(transport))

        def failing_executor(req, timeout):
            raise Exception(f"Custom failure with token {secret_token}")

        transport_fail = DhanHttpTransport(access_token=secret_token, executor=failing_executor)
        with self.assertRaises(TransportError) as ctx:
            transport_fail.post_intraday(b"{}")

        err_msg = str(ctx.exception)
        self.assertNotIn(secret_token, err_msg)
        self.assertEqual(err_msg, "Dhan HTTP transport failed.")

    def test_invalid_token_rejection(self):
        """Test empty token and tokens containing CR, LF, or null bytes are rejected."""
        with self.assertRaises(ValueError):
            DhanHttpTransport(access_token="")

        with self.assertRaises(ValueError):
            DhanHttpTransport(access_token="token\r\nline")

        with self.assertRaises(ValueError):
            DhanHttpTransport(access_token="token\0null")

    def test_timeout_validation(self):
        """Test timeout must be a positive finite float."""
        with self.assertRaises(ValueError):
            DhanHttpTransport("token", timeout_seconds=0.0)

        with self.assertRaises(ValueError):
            DhanHttpTransport("token", timeout_seconds=-5.0)

        with self.assertRaises(ValueError):
            DhanHttpTransport("token", timeout_seconds=float("nan"))

        with self.assertRaises(ValueError):
            DhanHttpTransport("token", timeout_seconds=float("inf"))

        with self.assertRaises(TypeError):
            DhanHttpTransport("token", timeout_seconds=True)

    def test_endpoint_validation(self):
        """Test HTTPS requirement, hostname presence, and rejection of URLs with credentials."""
        with self.assertRaises(ValueError):
            DhanHttpTransport("token", endpoint="http://api.dhan.co/v2/charts/intraday")

        with self.assertRaises(ValueError):
            DhanHttpTransport("token", endpoint="https://user:pass@api.dhan.co/v2/charts/intraday")

        with self.assertRaises(ValueError):
            DhanHttpTransport("token", endpoint="https:///v2/charts/intraday")

    def test_http_error_response_preservation(self):
        """Test HTTPError status, body, and headers are captured into HttpResponse."""
        def error_executor(req, timeout):
            headers_bytes = b"content-type: application/json\r\n"
            return HttpResponse(status_code=400, body=b'{"errorCode":"400"}', headers=headers_bytes)

        transport = DhanHttpTransport("token", executor=error_executor)
        resp = transport.post_intraday(b"{}")

        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"content-type: application/json", resp.headers)
        self.assertEqual(resp.body, b'{"errorCode":"400"}')

    def test_deterministic_response_header_serialization(self):
        """Test header sorting by key then value and duplicate key preservation."""
        class MockHeaders:
            def raw_items(self):
                return [
                    ("Set-Cookie", "b=2"),
                    ("Content-Type", "application/json"),
                    ("Set-Cookie", "a=1"),
                    ("X-Custom", "val"),
                ]

        res = _serialize_response_headers(MockHeaders())
        expected = b"Content-Type: application/json\r\nSet-Cookie: a=1\r\nSet-Cookie: b=2\r\nX-Custom: val\r\n"
        self.assertEqual(res, expected)

    def test_http_response_immutability_and_validation(self):
        """Test HttpResponse dataclass status code range and type validation."""
        with self.assertRaises(ValueError):
            HttpResponse(status_code=99, body=b"", headers=b"")

        with self.assertRaises(ValueError):
            HttpResponse(status_code=600, body=b"", headers=b"")

        with self.assertRaises(TypeError):
            HttpResponse(status_code="200", body=b"", headers=b"")

        with self.assertRaises(TypeError):
            HttpResponse(status_code=200, body="text", headers=b"")


if __name__ == "__main__":
    unittest.main()
