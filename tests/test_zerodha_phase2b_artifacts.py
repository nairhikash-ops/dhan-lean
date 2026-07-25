"""Offline Phase 2B.4 raw-artifact, replay, and redaction coverage."""

import hashlib
import json
import os
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from dhan_lean.data.request_budget import RequestBudget
from dhan_lean.providers.zerodha import (
    ArtifactCollisionError,
    BrokerErrorCode,
    BrokerResponse,
    DeterministicFakeBroker,
    IncompleteArtifactError,
    InvalidArtifactInputError,
    ResponseBodyHashMismatchError,
    RetryPolicy,
    SessionState,
    UnsafeMetadataError,
    ZerodhaArtifactInput,
    ZerodhaArtifactError,
    execute_and_publish,
    plan_historical_candles,
    publish_budgeted_result,
)
from dhan_lean.providers.zerodha.broker_protocol import TransportStatus
from dhan_lean.providers.zerodha.retry import AttemptRecord
from dhan_lean.providers.zerodha.retry import AttemptObserverError, run_planned_request
from tests.test_zerodha_phase2b_planning import planning_input


ID_A = "12345678-1234-4678-8123-123456789abc"
ID_B = "87654321-4321-4876-8123-cba987654321"
CAPTURED = datetime(2026, 7, 20, 4, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "zerodha"


def provider_response(request_id, body, *, status=200, error_code=None, session_state=SessionState.READY):
    return BrokerResponse.for_provider(request_id=request_id, broker_request_id=ID_B, captured_at=CAPTURED,
        status=status, body=body, error_code=error_code, session_state=session_state)


class TestZerodhaPhase2BArtifacts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.planned = plan_historical_candles(planning_input(), request_id_factory=lambda: ID_A)

    def tearDown(self):
        self.temp.cleanup()

    def run_flow(self, steps, allowance=5, ids=(ID_A, ID_B)):
        budget = RequestBudget(self.root / "budget.sqlite")
        budget.configure("artifact-test", "window", allowance)
        return execute_and_publish(self.planned, DeterministicFakeBroker(steps), budget,
            RetryPolicy(budget_scope="artifact-test", budget_window_id="window"), storage_root=self.root,
            run_id="20260720T040000Z", request_id_factory=iter(ids).__next__)

    def test_success_publishes_exact_body_parser_and_validation(self):
        body = (FIXTURES / "historical_valid.json").read_bytes()
        result, artifacts = self.run_flow([lambda request, _: provider_response(request.request_id, body)])
        self.assertTrue(result.succeeded)
        artifact = artifacts[0]
        self.assertEqual((artifact.publication_status, artifact.parser_outcome, artifact.validation_outcome), ("PUBLISHED", "SUCCESS", "SUCCESS"))
        directory = self.root / artifact.artifact_relative_path
        self.assertEqual((directory / "response-body.bin").read_bytes(), body)
        request_metadata = json.loads((directory / "request-metadata.json").read_text())
        self.assertIn("provider_instrument_id", request_metadata)
        self.assertNotIn("instrument_token", request_metadata)

    def test_empty_response_is_preserved_but_validation_is_empty(self):
        body = (FIXTURES / "historical_empty.json").read_bytes()
        _, artifacts = self.run_flow([lambda request, _: provider_response(request.request_id, body)])
        self.assertEqual(artifacts[0].parser_outcome, "SUCCESS")
        self.assertEqual(artifacts[0].validation_outcome, "EMPTY_BARS")
        self.assertEqual((self.root / artifacts[0].artifact_relative_path / "response-body.bin").read_bytes(), body)

    def test_retry_responses_are_separate_and_share_fingerprint(self):
        limited = lambda request, _: provider_response(request.request_id, b'{"error":"limited"}', status=429, error_code=BrokerErrorCode.PROVIDER_429)
        success = lambda request, _: provider_response(request.request_id, (FIXTURES / "historical_valid.json").read_bytes())
        result, artifacts = self.run_flow([limited, success])
        self.assertTrue(result.succeeded)
        self.assertEqual([item.attempt_number for item in artifacts], [1, 2])
        self.assertNotEqual(artifacts[0].artifact_relative_path, artifacts[1].artifact_relative_path)
        self.assertEqual({item.request_fingerprint for item in artifacts}, {self.planned.fingerprint})
        self.assertEqual((self.root / artifacts[0].artifact_relative_path / "response-body.bin").read_bytes(), b'{"error":"limited"}')

    def test_provider_errors_malformed_json_and_binary_are_preserved(self):
        cases = (
            (400, BrokerErrorCode.PROVIDER_400, b'{"error":"bad request"}', "NOT_ATTEMPTED"),
            (403, BrokerErrorCode.PROVIDER_403, "forbidden—é".encode("utf-8"), "NOT_ATTEMPTED"),
            (500, BrokerErrorCode.PROVIDER_5XX, b"server failure", "NOT_ATTEMPTED"),
            (200, None, b"not-json\x00\xff", "FAILURE"),
            (200, None, b"{\"status\":\"success\"}\n  ", "FAILURE"),
        )
        for status, code, body, parser_outcome in cases:
            with self.subTest(status=status):
                self.temp.cleanup()
                self.temp = tempfile.TemporaryDirectory()
                self.root = Path(self.temp.name)
                session = SessionState.INVALIDATED if status == 403 else SessionState.READY
                _, artifacts = self.run_flow([lambda request, _, s=status, c=code, b=body, ss=session: provider_response(request.request_id, b, status=s, error_code=c, session_state=ss)])
                self.assertEqual(artifacts[0].parser_outcome, parser_outcome)
                self.assertEqual((self.root / artifacts[0].artifact_relative_path / "response-body.bin").read_bytes(), body)

    def test_timeout_and_budget_exhaustion_publish_metadata_without_body(self):
        timeout = __import__("dhan_lean.providers.zerodha", fromlist=["ZerodhaBrokerError"]).ZerodhaBrokerError(BrokerErrorCode.BROKER_TIMEOUT)
        result, artifacts = self.run_flow([timeout, lambda request, _: provider_response(request.request_id, b"unused")], allowance=1)
        self.assertTrue(result.budget_exhausted)
        self.assertEqual(len(artifacts), 2)
        for artifact in artifacts:
            self.assertFalse((self.root / artifact.artifact_relative_path / "response-body.bin").exists())

    def test_duplicate_publication_reuses_and_conflicts_fail_closed(self):
        body = (FIXTURES / "historical_valid.json").read_bytes()
        budget = RequestBudget(self.root / "budget.sqlite")
        budget.configure("replay", "w", 2)
        observed = {}
        result, artifacts = execute_and_publish(self.planned, DeterministicFakeBroker([lambda request, _: provider_response(request.request_id, body)]), budget,
            RetryPolicy(budget_scope="replay", budget_window_id="w"), storage_root=self.root, run_id="20260720T040000Z", request_id_factory=lambda: ID_A)
        directory = self.root / artifacts[0].artifact_relative_path
        response = result.final_response
        replay_input = ZerodhaArtifactInput(self.planned, result, self.root, "20260720T040000Z", self.planned.instrument_snapshot_sha256, {1: response})
        replay = publish_budgeted_result(replay_input)
        self.assertTrue(replay[0].idempotent_replay)
        (directory / "response-metadata.json").write_bytes(b'{"changed":true}\n')
        with self.assertRaises(ArtifactCollisionError):
            publish_budgeted_result(ZerodhaArtifactInput(self.planned, result, self.root, "20260720T040000Z", self.planned.instrument_snapshot_sha256, {1: response}))
        self.assertEqual((directory / "response-body.bin").read_bytes(), body)

    def test_incomplete_set_and_unsafe_metadata_fail_before_or_during_publication(self):
        body = b'{"status":"success","data":{"candles":[]}}'
        result, artifacts = self.run_flow([lambda request, _: provider_response(request.request_id, body)])
        directory = self.root / artifacts[0].artifact_relative_path
        (directory / "manifest.json").unlink()
        with self.assertRaises(IncompleteArtifactError):
            self.run_flow([lambda request, _: provider_response(request.request_id, body)])
        for key in ("API_KEY", "Authorization", "Cookie", "set-cookie", "password", "session_token", "request-token"):
            with self.subTest(key=key):
                bad = object.__new__(type(self.planned))
                for field in self.planned.__dataclass_fields__:
                    object.__setattr__(bad, field, getattr(self.planned, field))
                object.__setattr__(bad, "canonical_metadata", {key: "fake", "provider_instrument_id": "1001"})
                with self.assertRaises(UnsafeMetadataError):
                    publish_budgeted_result(ZerodhaArtifactInput(bad, result, self.root, "20260720T040000Z", self.planned.instrument_snapshot_sha256, {1: result.final_response}))

    def test_result_and_errors_never_include_body_bytes(self):
        body = b"secret-provider-body"
        _, artifacts = self.run_flow([lambda request, _: provider_response(request.request_id, body, status=400, error_code=BrokerErrorCode.PROVIDER_400)])
        self.assertNotIn(body.decode(), repr(artifacts[0]))
        self.assertNotIn(body.decode(), str(ArtifactCollisionError()))

    def test_response_hash_mismatch_is_rejected_before_publication(self):
        body = b'{"status":"success","data":{"candles":[]}}'
        result, _ = self.run_flow([lambda request, _: provider_response(request.request_id, body)])
        tampered = result.final_response
        object.__setattr__(tampered, "body_sha256", "0" * 64)
        with self.assertRaises(ResponseBodyHashMismatchError):
            publish_budgeted_result(ZerodhaArtifactInput(self.planned, result, self.root, "20260720T040000Z", self.planned.instrument_snapshot_sha256, {1: tampered}))

    def test_writer_bundle_is_hash_manifested_and_no_network_is_needed(self):
        body = b"{}\r\n"
        _, artifacts = self.run_flow([lambda request, _: provider_response(request.request_id, body, status=400, error_code=BrokerErrorCode.PROVIDER_400)])
        directory = self.root / artifacts[0].artifact_relative_path
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["files"]["response-body.bin"]["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(manifest["files"]["response-body.bin"]["length"], len(body))

    def test_replay_rejects_contamination_and_missing_response_evidence(self):
        body = (FIXTURES / "historical_valid.json").read_bytes()
        result, artifacts = self.run_flow([lambda request, _: provider_response(request.request_id, body)])
        directory = self.root / artifacts[0].artifact_relative_path
        with self.assertRaises(InvalidArtifactInputError):
            publish_budgeted_result(ZerodhaArtifactInput(self.planned, result, self.root, "20260720T040000Z", self.planned.instrument_snapshot_sha256, {}))
        (directory / "unexpected").mkdir()
        with self.assertRaises(ArtifactCollisionError):
            publish_budgeted_result(ZerodhaArtifactInput(self.planned, result, self.root, "20260720T040000Z", self.planned.instrument_snapshot_sha256, {1: result.final_response}))

    def test_replay_rejects_symlink_when_supported(self):
        body = (FIXTURES / "historical_valid.json").read_bytes()
        result, artifacts = self.run_flow([lambda request, _: provider_response(request.request_id, body)])
        directory = self.root / artifacts[0].artifact_relative_path
        link = directory / "link"
        try:
            os.symlink(directory / "response-body.bin", link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable in this environment")
        with self.assertRaises(ArtifactCollisionError):
            publish_budgeted_result(ZerodhaArtifactInput(self.planned, result, self.root, "20260720T040000Z", self.planned.instrument_snapshot_sha256, {1: result.final_response}))

    def test_observer_failure_is_safe_and_does_not_retry_or_double_consume(self):
        budget = RequestBudget(self.root / "observer.sqlite")
        budget.configure("observer", "w", 2)
        fake = DeterministicFakeBroker([lambda request, _: provider_response(request.request_id, b'{"status":"success","data":{"candles":[]}}')])
        with self.assertRaises(AttemptObserverError) as context:
            run_planned_request(self.planned, fake, budget, RetryPolicy(budget_scope="observer", budget_window_id="w"), request_id_factory=lambda: ID_A, attempt_observer=lambda attempt, response: (_ for _ in ()).throw(RuntimeError("raw-body-must-not-leak")))
        self.assertNotIn("raw-body", str(context.exception))
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(budget.snapshot("observer", "w").consumed, 1)

    def test_budget_exhaustion_does_not_observe_a_nonexistent_call(self):
        budget = RequestBudget(self.root / "zero.sqlite")
        budget.configure("zero", "w", 0)
        seen = []
        fake = DeterministicFakeBroker([])
        result = run_planned_request(self.planned, fake, budget, RetryPolicy(budget_scope="zero", budget_window_id="w"), request_id_factory=lambda: ID_A, attempt_observer=lambda attempt, response: seen.append((attempt, response)))
        self.assertTrue(result.budget_exhausted)
        self.assertEqual(fake.call_count, 0)
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
