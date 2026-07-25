"""Tests for storage path validation, artifact path building, and ArtifactWriter."""

import os
import tempfile
import threading
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from dhan_lean.data.models import ValidationResult
from dhan_lean.data.storage import (
    ArtifactWriter,
    _validate_path_component,
    _validate_bundle_filename,
    build_raw_artifact_dir,
    build_raw_artifact_path,
)


class TestStorage(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.storage_root = Path(self.tmp.name).resolve()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_validate_path_component_valid_cases(self) -> None:
        self.assertEqual(_validate_path_component("test_id", "name"), "test_id")
        self.assertEqual(_validate_path_component("  spaced  ", "name"), "spaced")

    def test_validate_path_component_rejection_cases(self) -> None:
        with self.assertRaises(ValueError):
            _validate_path_component(123, "name")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            _validate_path_component("", "name")
        with self.assertRaises(ValueError):
            _validate_path_component("   ", "name")
        with self.assertRaises(ValueError):
            _validate_path_component(".", "name")
        with self.assertRaises(ValueError):
            _validate_path_component("..", "name")
        with self.assertRaises(ValueError):
            _validate_path_component("foo/bar", "name")
        with self.assertRaises(ValueError):
            _validate_path_component("foo\\bar", "name")
        with self.assertRaises(ValueError):
            _validate_path_component("foo:bar", "name")
        with self.assertRaises(ValueError):
            _validate_path_component("foo*bar", "name")

    def test_build_raw_artifact_path_lexical_and_casing(self) -> None:
        path = build_raw_artifact_path(
            storage_root=self.storage_root,
            source_id="MySource",
            venue="NSE",
            data_kind="BARS",
            symbol="hdfcbank",
            instrument_id="1333",
            resolution="1M",
            session_date=date(2026, 7, 20),
        )

        expected_rel = Path("raw/mysource/nse/bars/HDFCBANK/1333/1m/2026/07/20")
        self.assertEqual(path, self.storage_root / expected_rel)

    def test_build_raw_artifact_path_requires_exact_date(self) -> None:
        with self.assertRaises(TypeError):
            build_raw_artifact_path(
                storage_root=self.storage_root,
                source_id="source",
                venue="venue",
                data_kind="kind",
                symbol="HDFCBANK",
                instrument_id="1333",
                resolution="1m",
                session_date="2026-07-20",  # type: ignore[arg-type]
            )

    def test_build_raw_artifact_dir_resolution_and_escape_rejection(self) -> None:
        resolved = build_raw_artifact_dir(
            storage_root=self.storage_root,
            source_id="source",
            venue="venue",
            data_kind="kind",
            symbol="HDFCBANK",
            instrument_id="1333",
            resolution="1m",
            session_date=date(2026, 7, 20),
        )
        self.assertTrue(resolved.is_absolute())
        self.assertTrue(resolved.is_relative_to(self.storage_root))

    def test_artifact_writer_run_id_validation(self) -> None:
        writer = ArtifactWriter()
        writer._verify_valid_run_id("20260720T091500Z")

        with self.assertRaises(ValueError):
            writer._verify_valid_run_id("invalid-run-id")
        with self.assertRaises(ValueError):
            writer._verify_valid_run_id("20260230T091500Z")  # Invalid Feb 30 date

    def test_artifact_writer_credential_key_scanning(self) -> None:
        writer = ArtifactWriter()
        writer._verify_no_credentials(b"clean content", "test")

        for key in ["client-id", "password", "secret", "token"]:
            payload = f'{{"{key}": "12345"}}'.encode("utf-8")
            with self.assertRaises(ValueError) as ctx:
                writer._verify_no_credentials(payload, "test_payload")
            self.assertIn("Credential key", str(ctx.exception))


    def test_artifact_writer_build_artifact_paths(self) -> None:
        writer = ArtifactWriter()
        out_dir = self.storage_root / "output"
        paths = writer.build_artifact_paths(out_dir, "20260720T091500Z")
        self.assertEqual(len(paths), 6)
        self.assertIn("request", paths)
        self.assertIn("response", paths)
        self.assertIn("headers", paths)
        self.assertIn("status", paths)
        self.assertIn("validation", paths)
        self.assertIn("sha256", paths)

    def test_artifact_writer_ensure_targets_available_collision(self) -> None:
        writer = ArtifactWriter()
        out_dir = self.storage_root / "output"
        out_dir.mkdir(parents=True)
        paths = writer.build_artifact_paths(out_dir, "20260720T091500Z")

        paths["request"].write_bytes(b"data")

        with self.assertRaises(FileExistsError):
            writer.ensure_targets_available(out_dir, "20260720T091500Z")

    def test_artifact_writer_write_source_artifacts_success_and_sha256(self) -> None:
        writer = ArtifactWriter()
        out_dir = self.storage_root / "output"
        run_id = "20260720T091500Z"
        val_res = ValidationResult(
            is_valid=True,
            errors=(),
            bar_count=5,
            timestamps_strictly_increasing=True,
            duplicate_timestamp_count=0,
            non_increasing_timestamp_count=0,
            invalid_ohlc_count=0,
            non_positive_price_count=0,
            negative_volume_count=0,
            timestamp_delta_distribution={60: 4},
        )

        written = writer.write_source_artifacts(
            output_dir=out_dir,
            run_id=run_id,
            request_bytes=b'{"req": 1}',
            response_bytes=b'{"res": 1}',
            headers_bytes=b"HTTP/1.1 200 OK\r\n",
            http_status=200,
            validation_result=val_res,
        )

        self.assertEqual(len(written), 6)
        for name, path in written.items():
            self.assertTrue(path.exists())

        sha_content = written["sha256"].read_text(encoding="utf-8")
        self.assertIn("request-20260720T091500Z.json", sha_content)
        self.assertIn("response-20260720T091500Z.json", sha_content)

    def test_artifact_writer_partial_write_cleanup_on_failure(self) -> None:
        writer = ArtifactWriter()
        out_dir = self.storage_root / "output"
        run_id = "20260720T091500Z"
        val_res = ValidationResult(
            is_valid=True,
            errors=(),
            bar_count=1,
            timestamps_strictly_increasing=True,
            duplicate_timestamp_count=0,
            non_increasing_timestamp_count=0,
            invalid_ohlc_count=0,
            non_positive_price_count=0,
            negative_volume_count=0,
            timestamp_delta_distribution={},
        )

        real_open = open
        count = [0]

        def mock_open(*args, **kwargs):
            count[0] += 1
            if count[0] == 2:
                raise IOError("Disk full")
            return real_open(*args, **kwargs)

        with patch("builtins.open", side_effect=mock_open):
            with self.assertRaises(IOError):
                writer.write_source_artifacts(
                    output_dir=out_dir,
                    run_id=run_id,
                    request_bytes=b'{"req": 1}',
                    response_bytes=b'{"res": 1}',
                    headers_bytes=b"headers",
                    http_status=200,
                    validation_result=val_res,
                )

        # Confirm partial file was unlinked
        self.assertFalse((out_dir / "request-20260720T091500Z.json").exists())

    def test_bundle_filenames_reject_cross_platform_escape_and_devices(self) -> None:
        for name in ("", ".", "..", "../escape", "..\\escape", "/absolute", "C:\\escape", "\\\\server\\share", "CON", "con.txt", "NUL.json", "name.", "name ", "bad\x00name"):
            with self.subTest(name=repr(name)), self.assertRaises(ValueError):
                _validate_bundle_filename(name)
        self.assertEqual(_validate_bundle_filename("response-body.bin"), "response-body.bin")

    def test_bundle_stages_failures_without_incomplete_final_directory(self) -> None:
        writer = ArtifactWriter()
        target = self.storage_root / "bundle"
        for stage in ("after_staging_directory", "after_first_payload", "before_manifest", "after_manifest", "before_final_rename"):
            with self.subTest(stage=stage):
                with self.assertRaises(RuntimeError):
                    writer.write_immutable_bundle(target, {"one.json": b"{}", "two.bin": b"x"}, _failure_injector=lambda actual, expected=stage: (_ for _ in ()).throw(RuntimeError("injected")) if actual == expected else None)
                self.assertFalse(target.exists())
        written = writer.write_immutable_bundle(target, {"one.json": b"{}", "two.bin": b"x"})
        self.assertTrue(written["manifest.json"].exists())
        self.assertFalse(any(path.name.startswith(".tmp-") for path in target.parent.iterdir()))

    def test_bundle_concurrent_publishers_leave_one_complete_final_bundle(self) -> None:
        writer = ArtifactWriter()
        target = self.storage_root / "concurrent"
        barrier = threading.Barrier(2)
        outcomes = []
        def publish() -> None:
            try:
                writer.write_immutable_bundle(target, {"payload.bin": b"same"}, _failure_injector=lambda stage: barrier.wait(timeout=5) if stage == "after_manifest" else None)
                outcomes.append("published")
            except FileExistsError:
                outcomes.append("exists")
        threads = [threading.Thread(target=publish) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(10)
        self.assertEqual(sorted(outcomes), ["exists", "published"])
        self.assertTrue((target / "manifest.json").is_file())
        self.assertFalse(any(path.name.startswith(".tmp-") for path in target.parent.iterdir()))

    def test_bundle_conflicting_publishers_never_overwrite_winner(self) -> None:
        writer = ArtifactWriter()
        target = self.storage_root / "conflicting"
        barrier = threading.Barrier(2)
        outcomes = []
        def publish(body: bytes) -> None:
            try:
                writer.write_immutable_bundle(target, {"payload.bin": body}, _failure_injector=lambda stage: barrier.wait(timeout=5) if stage == "after_manifest" else None)
                outcomes.append(("published", body))
            except FileExistsError:
                outcomes.append(("exists", body))
        threads = [threading.Thread(target=publish, args=(body,)) for body in (b"first", b"second")]
        for thread in threads: thread.start()
        for thread in threads: thread.join(10)
        self.assertEqual(sorted(item[0] for item in outcomes), ["exists", "published"])
        winner = next(body for state, body in outcomes if state == "published")
        self.assertEqual((target / "payload.bin").read_bytes(), winner)



if __name__ == "__main__":
    unittest.main()
