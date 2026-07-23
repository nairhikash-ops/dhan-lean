import json
import tempfile
import unittest
from datetime import datetime, date, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dhan_lean.data.models import HttpResponse, DownloadResult, ValidationResult
from dhan_lean.data.transport import DhanHttpTransport, TransportError
from dhan_lean.data.downloader import (
    build_intraday_payload,
    generate_utc_run_id,
    DhanIntradayDownloader,
)

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


class TestDownloader(unittest.TestCase):

    def _valid_synthetic_body(self, count=5, base_ts=1784691900):
        data = {
            "open": [100.0 + i for i in range(count)],
            "high": [105.0 + i for i in range(count)],
            "low": [95.0 + i for i in range(count)],
            "close": [102.0 + i for i in range(count)],
            "volume": [1000 + i * 10 for i in range(count)],
            "timestamp": [base_ts + i * 60 for i in range(count)],
        }
        return json.dumps(data).encode("utf-8")

    def test_build_intraday_payload_hdfcbank_full_session(self):
        """Test build_intraday_payload produces exact key order and HDFCBANK bounds."""
        start = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
        end = datetime(2026, 7, 22, 15, 30, 0, tzinfo=IST)

        payload_bytes = build_intraday_payload(
            security_id="1333",
            exchange_segment="NSE_EQ",
            instrument="EQUITY",
            start_time=start,
            end_time=end,
            include_oi=False
        )

        expected_json = (
            '{"securityId":"1333",'
            '"exchangeSegment":"NSE_EQ",'
            '"instrument":"EQUITY",'
            '"interval":"1",'
            '"oi":false,'
            '"fromDate":"2026-07-22 09:14:00",'
            '"toDate":"2026-07-22 15:30:00"}'
        )

        self.assertEqual(payload_bytes.decode("utf-8"), expected_json)

    def test_payload_restrictions(self):
        """Test rejection of non-digit security_id, wrong exchange_segment/instrument, and non-bool include_oi."""
        start = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
        end = datetime(2026, 7, 22, 15, 30, 0, tzinfo=IST)

        with self.assertRaises(ValueError):
            build_intraday_payload("1333A", "NSE_EQ", "EQUITY", start, end)

        with self.assertRaises(ValueError):
            build_intraday_payload("1333", "nse_eq", "EQUITY", start, end)

        with self.assertRaises(ValueError):
            build_intraday_payload("1333", "NSE_EQ", "equity", start, end)

        with self.assertRaises(TypeError):
            build_intraday_payload("1333", "NSE_EQ", "EQUITY", start, end, include_oi=1)

    def test_generate_utc_run_id(self):
        """Test generate_utc_run_id with default and injected aware/naive clocks."""
        fixed_dt = datetime(2026, 7, 23, 14, 15, 6, tzinfo=UTC)
        run_id = generate_utc_run_id(clock=lambda: fixed_dt)
        self.assertEqual(run_id, "20260723T141506Z")

        # Injected naive clock raises ValueError
        naive_dt = datetime(2026, 7, 23, 14, 15, 6)
        with self.assertRaises(ValueError):
            generate_utc_run_id(clock=lambda: naive_dt)

    def test_cross_midnight_downloader_rejection(self):
        """Test start_time and end_time crossing IST midnight are rejected."""
        start = datetime(2026, 7, 22, 23, 0, 0, tzinfo=IST)
        end = datetime(2026, 7, 23, 1, 0, 0, tzinfo=IST)

        transport = DhanHttpTransport("test_token")
        downloader = DhanIntradayDownloader(transport=transport, storage_root="/tmp/data")

        with self.assertRaises(ValueError):
            downloader.download_intraday("HDFCBANK", "1333", "NSE_EQ", "EQUITY", start, end)

    def test_successful_downloader_execution(self):
        """Test full successful download flow creates 6 artifacts and token is absent."""
        token = "MY_SECRET_DHAN_TOKEN_999"

        def mock_executor(req, timeout):
            return HttpResponse(status_code=200, body=self._valid_synthetic_body(), headers=b"x-dhan: ok\r\n")

        transport = DhanHttpTransport(token, executor=mock_executor)

        with tempfile.TemporaryDirectory() as tmp_dir:
            downloader = DhanIntradayDownloader(transport=transport, storage_root=tmp_dir)

            start = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
            end = datetime(2026, 7, 22, 15, 30, 0, tzinfo=IST)

            res = downloader.download_intraday(
                symbol="HDFCBANK",
                security_id="1333",
                exchange_segment="NSE_EQ",
                instrument="EQUITY",
                start_time=start,
                end_time=end,
                run_id="20260722T141506Z"
            )

            self.assertTrue(res.success)
            self.assertEqual(res.status_code, 200)
            self.assertEqual(len(res.artifact_paths), 6)
            self.assertTrue(res.output_directory.exists())

            # Verify derived IST date in path
            expected_path_part = Path("raw/dhan/nse_eq/equity/HDFCBANK/1333/1m/2026/07/22")
            self.assertIn(str(expected_path_part), str(res.output_directory))

            # Verify token absence across all written files
            for p in res.artifact_paths.values():
                content = p.read_bytes()
                self.assertNotIn(token.encode("utf-8"), content)

            # Test artifact_paths mapping immutability
            with self.assertRaises(TypeError):
                res.artifact_paths["new"] = Path("/tmp")

    def test_http_non_200_and_dhan_error_payloads(self):
        """Test non-200 and Dhan error payloads write artifacts and return success=False."""
        def error_payload_executor(req, timeout):
            body = b'{"errorCode": "RS-9001", "errorMessage": "Invalid Session"}'
            return HttpResponse(status_code=200, body=body, headers=b"")

        transport = DhanHttpTransport("token", executor=error_payload_executor)

        with tempfile.TemporaryDirectory() as tmp_dir:
            downloader = DhanIntradayDownloader(transport=transport, storage_root=tmp_dir)
            start = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
            end = datetime(2026, 7, 22, 15, 30, 0, tzinfo=IST)

            res = downloader.download_intraday("HDFCBANK", "1333", "NSE_EQ", "EQUITY", start, end, run_id="20260722T141506Z")

            self.assertFalse(res.success)
            self.assertEqual(res.error_code, "RS-9001")
            self.assertEqual(res.error_message, "Invalid Session")
            self.assertEqual(len(res.artifact_paths), 6)

    def test_non_object_json_response(self):
        """Test response JSON that is an array returns success=False."""
        def array_json_executor(req, timeout):
            return HttpResponse(status_code=200, body=b'[1, 2, 3]', headers=b"")

        transport = DhanHttpTransport("token", executor=array_json_executor)

        with tempfile.TemporaryDirectory() as tmp_dir:
            downloader = DhanIntradayDownloader(transport=transport, storage_root=tmp_dir)
            start = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
            end = datetime(2026, 7, 22, 15, 30, 0, tzinfo=IST)

            res = downloader.download_intraday("HDFCBANK", "1333", "NSE_EQ", "EQUITY", start, end, run_id="20260722T141506Z")

            self.assertFalse(res.success)
            self.assertIn("Response JSON is not an object", res.validation_result.errors[0])

    def test_network_transport_error_propagates_without_writing_artifacts(self):
        """Test TransportError propagates and writes no artifacts."""
        def network_failing_executor(req, timeout):
            raise Exception("Network Timeout")

        transport = DhanHttpTransport("token", executor=network_failing_executor)

        with tempfile.TemporaryDirectory() as tmp_dir:
            downloader = DhanIntradayDownloader(transport=transport, storage_root=tmp_dir)
            start = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
            end = datetime(2026, 7, 22, 15, 30, 0, tzinfo=IST)

            with self.assertRaises(TransportError):
                downloader.download_intraday("HDFCBANK", "1333", "NSE_EQ", "EQUITY", start, end, run_id="20260722T141506Z")

    def test_downloader_preflight_collision_prevents_transport_call(self):
        """Test downloader preflight check fails before making transport call if target file exists."""
        call_count = 0

        def mock_executor(req, timeout):
            nonlocal call_count
            call_count += 1
            return HttpResponse(status_code=200, body=self._valid_synthetic_body(), headers=b"")

        transport = DhanHttpTransport("token", executor=mock_executor)

        with tempfile.TemporaryDirectory() as tmp_dir:
            downloader = DhanIntradayDownloader(transport=transport, storage_root=tmp_dir)
            start = datetime(2026, 7, 22, 9, 15, 0, tzinfo=IST)
            end = datetime(2026, 7, 22, 15, 30, 0, tzinfo=IST)
            run_id = "20260722T141506Z"

            # Execute first download successfully
            res1 = downloader.download_intraday("HDFCBANK", "1333", "NSE_EQ", "EQUITY", start, end, run_id=run_id)
            self.assertTrue(res1.success)
            self.assertEqual(call_count, 1)

            # Second download with same run_id must raise FileExistsError BEFORE executing transport call
            with self.assertRaises(FileExistsError):
                downloader.download_intraday("HDFCBANK", "1333", "NSE_EQ", "EQUITY", start, end, run_id=run_id)

            # Transport call count MUST remain 1 (0 calls executed on collision)
            self.assertEqual(call_count, 1)


if __name__ == "__main__":
    unittest.main()
