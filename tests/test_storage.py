import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from dhan_lean.data.storage import build_raw_artifact_dir, ArtifactWriter
from dhan_lean.data.models import ValidationResult


class TestStorage(unittest.TestCase):

    def test_safe_deterministic_path(self):
        """Test build_raw_artifact_dir generates deterministic paths with proper casing."""
        path = build_raw_artifact_dir(
            storage_root="/srv/market-data",
            provider="DHAN",
            exchange_segment="NSE_EQ",
            instrument="EQUITY",
            symbol="hdfcbank",
            security_id="1333",
            resolution="1M",
            session_date=date(2026, 7, 22)
        )

        expected = Path("/srv/market-data/raw/dhan/nse_eq/equity/HDFCBANK/1333/1m/2026/07/22").resolve()
        self.assertEqual(path, expected)

    def test_unsafe_component_rejection(self):
        """Test rejection of empty, separator, null byte, and dot components."""
        with self.assertRaises(ValueError):
            build_raw_artifact_dir("/root", "", "NSE_EQ", "EQUITY", "HDFCBANK", "1333", "1m", date(2026, 7, 22))

        with self.assertRaises(ValueError):
            build_raw_artifact_dir("/root", "dhan", "NSE/EQ", "EQUITY", "HDFCBANK", "1333", "1m", date(2026, 7, 22))

        with self.assertRaises(ValueError):
            build_raw_artifact_dir("/root", "dhan", "NSE_EQ", "EQUITY", "..", "1333", "1m", date(2026, 7, 22))

    def test_path_traversal_rejection(self):
        """Test path traversal component is rejected."""
        with self.assertRaises(ValueError):
            build_raw_artifact_dir("/root", "dhan", "NSE_EQ", "EQUITY", "../../../etc", "1333", "1m", date(2026, 7, 22))

    def test_artifact_writer_success_and_modes(self):
        """Test ArtifactWriter writes 6 files with exclusive mode and sha256 manifest."""
        writer = ArtifactWriter()
        val_res = ValidationResult(
            is_valid=True,
            errors=[],
            candle_count=5,
            array_lengths={"open": 5},
            arrays_equal_length=True,
            timestamps_strictly_increasing=True,
            duplicate_timestamp_count=0,
            non_increasing_timestamp_count=0,
            invalid_ohlc_count=0,
            non_positive_price_count=0,
            negative_volume_count=0,
            zero_volume_count=0,
            timestamp_delta_distribution={60: 4},
            missing_gap_count=0,
            largest_actual_interval_seconds=60,
            largest_excess_gap_seconds=0,
            first_timestamp_utc="2026-07-22 03:45:00 UTC",
            last_timestamp_utc="2026-07-22 03:49:00 UTC",
            first_timestamp_ist="2026-07-22 09:15:00 IST",
            last_timestamp_ist="2026-07-22 09:19:00 IST",
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "test_run"
            run_id = "20260723T141506Z"

            res_paths = writer.write_pilot_artifacts(
                output_dir=out_dir,
                run_id=run_id,
                request_bytes=b'{"securityId": "1333"}',
                response_bytes=b'{"open": [100]}',
                headers_bytes=b'HTTP/1.1 200 OK\r\n',
                http_status=200,
                validation_result=val_res
            )

            self.assertEqual(len(res_paths), 6)
            for key, p in res_paths.items():
                self.assertTrue(p.exists())
                if os.name == 'posix':
                    stat = p.stat()
                    # mode 0600 on posix (-rw-------)
                    self.assertEqual(stat.st_mode & 0o777, 0o600)

            if os.name == 'posix':
                self.assertEqual(out_dir.stat().st_mode & 0o777, 0o700)

            # Check sha256 manifest
            sha_file = res_paths["sha256"]
            content = sha_file.read_text()
            self.assertIn("request-20260723T141506Z.json", content)
            self.assertNotIn("sha256-20260723T141506Z.txt", content)  # Must not contain itself

    def test_no_overwrite_behavior(self):
        """Test exclusive creation prevents overwriting existing files."""
        writer = ArtifactWriter()
        val_res = ValidationResult(
            is_valid=True, errors=[], candle_count=1, array_lengths={}, arrays_equal_length=True,
            timestamps_strictly_increasing=True, duplicate_timestamp_count=0, non_increasing_timestamp_count=0,
            invalid_ohlc_count=0, non_positive_price_count=0, negative_volume_count=0, zero_volume_count=0,
            timestamp_delta_distribution={}, missing_gap_count=0, largest_actual_interval_seconds=0,
            largest_excess_gap_seconds=0, first_timestamp_utc=None, last_timestamp_utc=None,
            first_timestamp_ist=None, last_timestamp_ist=None
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "test_run"
            run_id = "20260723T141506Z"

            writer.write_pilot_artifacts(out_dir, run_id, b'{}', b'{}', b'{}', 200, val_res)

            # Attempting second write with same run_id must fail with FileExistsError
            with self.assertRaises(FileExistsError):
                writer.write_pilot_artifacts(out_dir, run_id, b'{}', b'{}', b'{}', 200, val_res)

    def test_strict_date_type_enforcement(self):
        """Test build_raw_artifact_dir requires exact datetime.date and rejects datetime.datetime or strings."""
        from datetime import datetime
        with self.assertRaises(TypeError):
            build_raw_artifact_dir("/root", "dhan", "NSE_EQ", "EQUITY", "HDFCBANK", "1333", "1m", datetime(2026, 7, 22, 9, 15))

        with self.assertRaises(TypeError):
            build_raw_artifact_dir("/root", "dhan", "NSE_EQ", "EQUITY", "HDFCBANK", "1333", "1m", "2026-07-22")

        # Exact datetime.date instance succeeds
        res = build_raw_artifact_dir("/root", "dhan", "NSE_EQ", "EQUITY", "HDFCBANK", "1333", "1m", date(2026, 7, 22))
        self.assertIsNotNone(res)

    def test_run_id_calendar_validation(self):
        """Test run_id validation accepts valid UTC IDs and leap days, but rejects malformed or invalid calendar dates."""
        writer = ArtifactWriter()
        val_res = ValidationResult(
            is_valid=True, errors=[], candle_count=1, array_lengths={}, arrays_equal_length=True,
            timestamps_strictly_increasing=True, duplicate_timestamp_count=0, non_increasing_timestamp_count=0,
            invalid_ohlc_count=0, non_positive_price_count=0, negative_volume_count=0, zero_volume_count=0,
            timestamp_delta_distribution={}, missing_gap_count=0, largest_actual_interval_seconds=0,
            largest_excess_gap_seconds=0, first_timestamp_utc=None, last_timestamp_utc=None,
            first_timestamp_ist=None, last_timestamp_ist=None
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            out = Path(tmp_dir)

            # Valid run ID
            res = writer.write_pilot_artifacts(out / "run1", "20260723T141506Z", b'{}', b'{}', b'{}', 200, val_res)
            self.assertTrue(res["request"].exists())

            # Valid Leap Day (2024-02-29)
            res_leap = writer.write_pilot_artifacts(out / "run_leap", "20240229T120000Z", b'{}', b'{}', b'{}', 200, val_res)
            self.assertTrue(res_leap["request"].exists())

            # Invalid Feb 31
            with self.assertRaises(ValueError):
                writer.write_pilot_artifacts(out / "run_invalid_feb", "20260231T141506Z", b'{}', b'{}', b'{}', 200, val_res)

            # Invalid Month 13
            with self.assertRaises(ValueError):
                writer.write_pilot_artifacts(out / "run_invalid_month", "20261301T141506Z", b'{}', b'{}', b'{}', 200, val_res)

            # Invalid Hour 25
            with self.assertRaises(ValueError):
                writer.write_pilot_artifacts(out / "run_invalid_hour", "20260723T251506Z", b'{}', b'{}', b'{}', 200, val_res)

            # Missing Z
            with self.assertRaises(ValueError):
                writer.write_pilot_artifacts(out / "run_no_z", "20260723T141506", b'{}', b'{}', b'{}', 200, val_res)

            # Extra characters
            with self.assertRaises(ValueError):
                writer.write_pilot_artifacts(out / "run_extra", "20260723T141506Z_EXTRA", b'{}', b'{}', b'{}', 200, val_res)

    def test_validation_report_typo_fix_in_output(self):
        """Test output validation report contains TIMESTAMPS_STRICTLY_INCREASING and not misspelled key."""
        writer = ArtifactWriter()
        val_res = ValidationResult(
            is_valid=True, errors=[], candle_count=1, array_lengths={}, arrays_equal_length=True,
            timestamps_strictly_increasing=True, duplicate_timestamp_count=0, non_increasing_timestamp_count=0,
            invalid_ohlc_count=0, non_positive_price_count=0, negative_volume_count=0, zero_volume_count=0,
            timestamp_delta_distribution={}, missing_gap_count=0, largest_actual_interval_seconds=0,
            largest_excess_gap_seconds=0, first_timestamp_utc=None, last_timestamp_utc=None,
            first_timestamp_ist=None, last_timestamp_ist=None
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "test_report"
            res_paths = writer.write_pilot_artifacts(out_dir, "20260723T141506Z", b'{}', b'{}', b'{}', 200, val_res)
            val_text = res_paths["validation"].read_text()

            self.assertIn("TIMESTAMPS_STRICTLY_INCREASING=True", val_text)
            self.assertNotIn("TIMESTAMPS_STRRICTLY_INCREASING", val_text)

    def test_build_artifact_paths_and_ensure_targets(self):
        """Test build_artifact_paths returns 6 immutable targets and ensure_targets_available handles preflight checks."""
        writer = ArtifactWriter()
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "test_paths"
            run_id = "20260723T141506Z"

            paths = writer.build_artifact_paths(out_dir, run_id)
            self.assertEqual(len(paths), 6)
            self.assertIn("request", paths)
            self.assertIn("response", paths)
            self.assertIn("headers", paths)
            self.assertIn("status", paths)
            self.assertIn("validation", paths)
            self.assertIn("sha256", paths)

            # Mapping is immutable
            with self.assertRaises(TypeError):
                paths["request"] = Path("/tmp/other")

            # Directory is NOT created by build_artifact_paths
            self.assertFalse(out_dir.exists())

            # ensure_targets_available succeeds when no files exist
            available_paths = writer.ensure_targets_available(out_dir, run_id)
            self.assertEqual(len(available_paths), 6)

            # Create output dir and one file
            out_dir.mkdir(parents=True, exist_ok=True)
            existing_file = paths["status"]
            existing_file.write_text("200\n")

            # ensure_targets_available fails with FileExistsError when target exists
            with self.assertRaises(FileExistsError) as ctx:
                writer.ensure_targets_available(out_dir, run_id)
            self.assertIn(str(existing_file), str(ctx.exception))

            # File content was not altered
            self.assertEqual(existing_file.read_text(), "200\n")


if __name__ == "__main__":
    unittest.main()
