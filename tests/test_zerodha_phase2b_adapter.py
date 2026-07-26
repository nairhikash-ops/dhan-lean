"""Focused offline Phase 2B.5 provider-adapter coverage."""

import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from dhan_lean.data.models import DataWorkItem, TimeWindow
from dhan_lean.data.request_budget import RequestBudget
from dhan_lean.data.validator import validate_normalized_bars
from dhan_lean.providers.zerodha import (
    BrokerErrorCode,
    BrokerResponse,
    DeterministicFakeBroker,
    RetryPolicy,
    SessionState,
    ZerodhaAdapterStatus,
    ZerodhaHistoricalAdapter,
    ZerodhaHistoricalAdapterInput,
)
from dhan_lean.providers.zerodha.instruments import parse_instrument_snapshot
from dhan_lean.providers.zerodha import ZerodhaBrokerError


ROOT = Path(__file__).parent
FIXTURES = ROOT / "fixtures" / "zerodha"
ID_A = "12345678-1234-4678-8123-123456789abc"
ID_B = "87654321-4321-4876-8123-cba987654321"
CAPTURED = datetime(2026, 7, 20, 4, tzinfo=timezone.utc)


def work_item(symbol="ACME"):
    return DataWorkItem(symbol, "zerodha", "1m", date(2026, 7, 20),
                        TimeWindow(datetime(2026, 7, 20, 9, 15, tzinfo=timezone.utc),
                                   datetime(2026, 7, 20, 9, 17, tzinfo=timezone.utc)),
                        Path("ignored"), "work-1")


def response(request_id, body, *, status=200, error_code=None, session_state=SessionState.READY):
    return BrokerResponse.for_provider(request_id=request_id, broker_request_id=ID_B,
        captured_at=CAPTURED, status=status, body=body, error_code=error_code,
        session_state=session_state)


class TestZerodhaPhase2BAdapter(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = parse_instrument_snapshot(
            (FIXTURES / "instrument_master.csv").read_bytes(), date(2026, 7, 20))
        self.body = (FIXTURES / "historical_valid.json").read_bytes()
        self._adapter_counter = 0

    def tearDown(self):
        self.temp.cleanup()

    def adapter(self, broker, *, allowance=5, maximum_attempts=3, ids=(ID_A, ID_B), symbol="ACME", exchange="NSE", instrument_type="EQ"):
        self._adapter_counter += 1
        budget = RequestBudget(self.root / f"budget-{self._adapter_counter}.sqlite")
        budget.configure("adapter", "window", allowance)
        policy = RetryPolicy(maximum_attempts=maximum_attempts, budget_scope="adapter", budget_window_id="window")
        return ZerodhaHistoricalAdapter(ZerodhaHistoricalAdapterInput(
            self.snapshot, exchange, instrument_type=instrument_type, storage_root=self.root, run_id="20260720T040000Z",
            retry_policy=policy, request_budget=budget, broker=broker,
            request_id_factory=iter(ids).__next__, planning_request_id_factory=lambda: ID_A)), budget

    def test_success_resolves_plans_publishes_and_validates(self):
        fake = DeterministicFakeBroker([lambda request, _: response(request.request_id, self.body)])
        adapter, budget = self.adapter(fake)
        result = adapter.run(work_item())
        self.assertEqual(result.status, ZerodhaAdapterStatus.SUCCESS)
        self.assertEqual(len(result.bars), 2)
        self.assertTrue(result.validation.is_valid)
        self.assertEqual(len(result.artifact_publications), 1)
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(budget.snapshot("adapter", "window").consumed, 1)
        self.assertEqual(result.request_fingerprint, result.attempt_history[0].planned_fingerprint)
        artifact = self.root / result.artifact_publications[0].artifact_relative_path
        self.assertEqual((artifact / "response-body.bin").read_bytes(), self.body)

    def test_retry_keeps_fingerprint_and_publishes_each_attempt(self):
        limited = lambda request, _: response(request.request_id, b'{"error":"limited"}', status=429,
                                               error_code=BrokerErrorCode.PROVIDER_429)
        success = lambda request, _: response(request.request_id, self.body)
        fake = DeterministicFakeBroker([limited, success])
        adapter, budget = self.adapter(fake)
        result = adapter.run(work_item())
        self.assertEqual(result.status, ZerodhaAdapterStatus.SUCCESS)
        self.assertEqual(len(result.attempt_history), 2)
        self.assertEqual(len(result.artifact_publications), 2)
        self.assertEqual({a.planned_fingerprint for a in result.attempt_history}, {result.request_fingerprint})
        self.assertNotEqual(result.attempt_history[0].request_id, result.attempt_history[1].request_id)
        self.assertEqual(budget.snapshot("adapter", "window").consumed, 2)
        self.assertEqual(result.bars, result.parsed.bars)

    def test_provider_failures_are_typed_and_evidence_is_published(self):
        cases = ((400, BrokerErrorCode.PROVIDER_400, ZerodhaAdapterStatus.PROVIDER_FAILURE, False),
                 (403, BrokerErrorCode.PROVIDER_403, ZerodhaAdapterStatus.REAUTHENTICATION_REQUIRED, True))
        for status, code, expected, reauth in cases:
            with self.subTest(status=status):
                self.temp.cleanup()
                self.temp = tempfile.TemporaryDirectory()
                self.root = Path(self.temp.name)
                fake = DeterministicFakeBroker([lambda request, _, s=status, c=code:
                    response(request.request_id, b"provider-body", status=s, error_code=c,
                             session_state=SessionState.INVALIDATED if s == 403 else SessionState.READY)])
                adapter, _ = self.adapter(fake)
                result = adapter.run(work_item())
                self.assertEqual(result.status, expected)
                self.assertEqual(result.reauthentication_required, reauth)
                self.assertFalse(result.bars)
                self.assertEqual(len(result.artifact_publications), 1)
                artifact = self.root / result.artifact_publications[0].artifact_relative_path
                self.assertEqual((artifact / "response-body.bin").read_bytes(), b"provider-body")

    def test_malformed_and_empty_responses_do_not_return_bars(self):
        for body, expected in ((b"not-json", ZerodhaAdapterStatus.MALFORMED_PROVIDER_RESPONSE),
                               ((FIXTURES / "historical_empty.json").read_bytes(), ZerodhaAdapterStatus.EMPTY_RESPONSE)):
            with self.subTest(expected=expected):
                self.temp.cleanup()
                self.temp = tempfile.TemporaryDirectory()
                self.root = Path(self.temp.name)
                fake = DeterministicFakeBroker([lambda request, _, b=body: response(request.request_id, b)])
                adapter, _ = self.adapter(fake)
                result = adapter.run(work_item())
                self.assertEqual(result.status, expected)
                self.assertFalse(result.bars)
                self.assertEqual(len(result.artifact_publications), 1)

    def test_parser_success_followed_by_validation_failure_returns_no_bars(self):
        fake = DeterministicFakeBroker([lambda request, _: response(request.request_id, self.body)])
        adapter, _ = self.adapter(fake)
        with patch("dhan_lean.providers.zerodha.adapter.validate_normalized_bars",
                   return_value=validate_normalized_bars([])):
            result = adapter.run(work_item())
        self.assertEqual(result.status, ZerodhaAdapterStatus.EMPTY_RESPONSE)
        self.assertIsNotNone(result.parsed)
        self.assertIsNotNone(result.validation)
        self.assertFalse(result.bars)

    def test_local_budget_and_retry_limit_outcomes(self):
        timeout = ZerodhaBrokerError(BrokerErrorCode.BROKER_TIMEOUT)
        fake = DeterministicFakeBroker([timeout])
        adapter, budget = self.adapter(fake, allowance=0)
        result = adapter.run(work_item())
        self.assertEqual(result.status, ZerodhaAdapterStatus.BUDGET_EXHAUSTED)
        self.assertEqual(fake.call_count, 0)
        self.assertEqual(budget.snapshot("adapter", "window").consumed, 0)

        self.temp.cleanup()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        fake = DeterministicFakeBroker([timeout, timeout])
        adapter, budget = self.adapter(fake, allowance=2, maximum_attempts=2, ids=(ID_A, ID_B))
        result = adapter.run(work_item())
        self.assertEqual(result.status, ZerodhaAdapterStatus.RETRY_LIMIT_EXHAUSTED)
        self.assertEqual(len(result.artifact_publications), 2)
        self.assertEqual(budget.snapshot("adapter", "window").consumed, 2)

    def test_resolution_and_planning_fail_before_budget_or_broker(self):
        fake = DeterministicFakeBroker([])
        adapter, budget = self.adapter(fake, symbol="MISSING")
        result = adapter.run(work_item("MISSING"))
        self.assertEqual(result.status, ZerodhaAdapterStatus.RESOLUTION_FAILURE)
        self.assertIsNone(result.request_fingerprint)
        self.assertFalse(result.attempt_history)
        self.assertEqual(fake.call_count, 0)
        self.assertEqual(budget.snapshot("adapter", "window").consumed, 0)

        expired = DataWorkItem("OLD26JANFUT", "zerodha", "1m", date(2026, 7, 20),
                               TimeWindow(datetime(2026, 7, 20, 9, 15, tzinfo=timezone.utc),
                                          datetime(2026, 7, 20, 9, 16, tzinfo=timezone.utc)),
                               Path("ignored"), "expired")
        adapter, budget = self.adapter(fake, exchange="NFO", instrument_type="FUT")
        result = adapter.run(expired)
        self.assertEqual(result.status, ZerodhaAdapterStatus.RESOLUTION_FAILURE)
        self.assertEqual(budget.snapshot("adapter", "window").consumed, 0)

    def test_artifact_failure_does_not_retry_or_expose_body(self):
        fake = DeterministicFakeBroker([lambda request, _: response(request.request_id, b"secret-body")])
        adapter, budget = self.adapter(fake)
        with patch("dhan_lean.providers.zerodha.adapter.publish_budgeted_result", side_effect=RuntimeError("secret-body")):
            result = adapter.run(work_item())
        self.assertEqual(result.status, ZerodhaAdapterStatus.ARTIFACT_PUBLICATION_FAILURE)
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(budget.snapshot("adapter", "window").consumed, 1)
        self.assertNotIn("secret-body", repr(result))
        self.assertNotIn(str(self.root), repr(result))


if __name__ == "__main__":
    unittest.main()
