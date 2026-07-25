import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dhan_lean.data.request_budget import RequestBudget
from dhan_lean.providers.zerodha import (
    BrokerErrorCode,
    BrokerResponse,
    BudgetedBrokerResult,
    DeterministicFakeBroker,
    DuplicateRequestIdError,
    InconsistentBrokerResponseError,
    InvalidRequestIdError,
    POLICY_RETRYABLE_CODES,
    RETRYABLE_CODES,
    RetryPolicy,
    SessionState,
    ZerodhaBrokerError,
    UnexpectedBrokerException,
    calculate_retry_delay,
    run_planned_request,
)
from tests.test_zerodha_phase2b_planning import plan_historical_candles, planning_input


CAPTURED = datetime(2026, 7, 20, 4, tzinfo=timezone.utc)
ID_A = "12345678-1234-4678-8123-123456789abc"
ID_B = "87654321-4321-4876-8123-cba987654321"


def response(request_id=ID_A, status=200, body=b'{"status":"success"}', **kwargs):
    return BrokerResponse.for_provider(
        request_id=request_id,
        broker_request_id=ID_B,
        captured_at=CAPTURED,
        status=status,
        body=body,
        **kwargs,
    )


class TestZerodhaRetry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.budget = RequestBudget(Path(self.temp.name) / "budget.sqlite")
        self.budget.configure("zerodha-test", "window-a", 5)
        self.planned = plan_historical_candles(planning_input(), request_id_factory=lambda: ID_A)
        self.policy = RetryPolicy(budget_scope="zerodha-test", budget_window_id="window-a")
        self.ids = iter((ID_A, ID_B))

    def tearDown(self):
        self.temp.cleanup()

    def run_request(self, steps, **kwargs):
        return run_planned_request(
            self.planned,
            DeterministicFakeBroker(steps),
            self.budget,
            self.policy,
            request_id_factory=lambda: next(self.ids),
            **kwargs,
        )

    def test_success_consumes_exactly_one_and_empty_body_is_success(self):
        result = self.run_request([response(body=b"")])
        self.assertTrue(result.succeeded)
        self.assertEqual(result.total_budget_units_consumed, 1)
        self.assertEqual(result.attempt_history[0].body_sha256, __import__("hashlib").sha256(b"").hexdigest())

    def test_retry_consumes_same_window_and_keeps_fingerprint(self):
        result = self.run_request([
            response(status=429, body=b"limited", error_code=BrokerErrorCode.PROVIDER_429, retry_after_seconds=3),
            response(),
        ])
        self.assertTrue(result.succeeded)
        self.assertEqual(result.total_budget_units_consumed, 2)
        self.assertEqual([item.request_id for item in result.attempt_history], [ID_A, ID_B])
        self.assertEqual({item.planned_fingerprint for item in result.attempt_history}, {self.planned.fingerprint})
        self.assertEqual(result.attempt_history[0].next_delay, timedelta(seconds=3))
        self.assertEqual(self.budget.snapshot("zerodha-test", "window-a").consumed, 2)

    def test_retryable_typed_failures_and_terminal_codes(self):
        for code in (BrokerErrorCode.BROKER_UNAVAILABLE, BrokerErrorCode.BROKER_TIMEOUT, BrokerErrorCode.NETWORK_TIMEOUT, BrokerErrorCode.DNS_TLS_CONNECTION_FAILURE):
            with self.subTest(code=code):
                self.budget.configure("scope-" + code.value, "w", 2)
                result = run_planned_request(self.planned, DeterministicFakeBroker([ZerodhaBrokerError(code), response()]), self.budget, RetryPolicy(budget_scope="scope-" + code.value, budget_window_id="w"), request_id_factory=iter((ID_A, ID_B)).__next__)
                self.assertTrue(result.succeeded)
                self.assertEqual(len(result.attempt_history), 2)
        self.budget.configure("terminal", "w", 2)
        result = run_planned_request(self.planned, DeterministicFakeBroker([ZerodhaBrokerError(BrokerErrorCode.SESSION_EXPIRED)]), self.budget, RetryPolicy(budget_scope="terminal", budget_window_id="w"), request_id_factory=lambda: ID_A)
        self.assertTrue(result.reauthentication_required)
        self.assertEqual(result.total_budget_units_consumed, 1)

    def test_provider_403_requires_reauthentication_without_retry(self):
        self.budget.configure("403", "w", 2)
        result = run_planned_request(self.planned, DeterministicFakeBroker([response(status=403, body=b"forbidden", session_state=SessionState.INVALIDATED, error_code=BrokerErrorCode.PROVIDER_403)]), self.budget, RetryPolicy(budget_scope="403", budget_window_id="w"), request_id_factory=lambda: ID_A)
        self.assertFalse(result.succeeded)
        self.assertTrue(result.reauthentication_required)
        self.assertEqual(len(result.attempt_history), 1)

    def test_provider_client_and_response_errors_are_terminal(self):
        for code in (BrokerErrorCode.PROVIDER_400, BrokerErrorCode.PROVIDER_404, BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE, BrokerErrorCode.OVERSIZED_PROVIDER_RESPONSE):
            with self.subTest(code=code):
                scope = "terminal-" + code.value
                self.budget.configure(scope, "w", 3)
                result = run_planned_request(self.planned, DeterministicFakeBroker([ZerodhaBrokerError(code), response()]), self.budget, RetryPolicy(budget_scope=scope, budget_window_id="w"), request_id_factory=lambda: ID_A)
                self.assertEqual(result.final_outcome, code.value)
                self.assertEqual(len(result.attempt_history), 1)

    def test_policy_retry_set_matches_protocol_metadata(self):
        expected = frozenset(code for code in BrokerErrorCode if __import__("dhan_lean.providers.zerodha", fromlist=["error_policy"]).error_policy(code).retryable)
        self.assertEqual(RETRYABLE_CODES, expected)
        self.assertEqual(POLICY_RETRYABLE_CODES, RETRYABLE_CODES)

    def test_three_retryable_failures_preserve_code_and_mark_attempt_limit(self):
        scope = "three-429"
        self.budget.configure(scope, "w", 3)
        fake = DeterministicFakeBroker([response(status=429, body=b"x", error_code=BrokerErrorCode.PROVIDER_429)] * 3)
        result = run_planned_request(self.planned, fake, self.budget, RetryPolicy(budget_scope=scope, budget_window_id="w"), request_id_factory=iter((ID_A, ID_B, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")).__next__)
        self.assertEqual(result.final_outcome, BrokerErrorCode.PROVIDER_429.value)
        self.assertTrue(result.attempt_limit_exhausted)
        self.assertEqual(len(result.attempt_history), 3)
        self.assertEqual(result.total_budget_units_consumed, 3)
        self.assertIsNone(result.next_recommended_delay)

    def test_single_attempt_retryable_failure_marks_limit(self):
        scope = "one-attempt"
        self.budget.configure(scope, "w", 2)
        fake = DeterministicFakeBroker([ZerodhaBrokerError(BrokerErrorCode.BROKER_TIMEOUT)])
        result = run_planned_request(self.planned, fake, self.budget, RetryPolicy(maximum_attempts=1, budget_scope=scope, budget_window_id="w"), request_id_factory=lambda: ID_A)
        self.assertTrue(result.attempt_limit_exhausted)
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(result.total_budget_units_consumed, 1)
        self.assertIsNone(result.next_recommended_delay)

    def test_response_mismatch_and_unexpected_exception_are_safe(self):
        scope = "mismatch"
        self.budget.configure(scope, "w", 2)
        mismatched = response(body=b"raw-secret").with_request("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", ID_B)
        class MismatchedBroker:
            def fetch_candles(self, request):
                return mismatched
        with self.assertRaises(InconsistentBrokerResponseError) as context:
            run_planned_request(self.planned, MismatchedBroker(), self.budget, RetryPolicy(budget_scope=scope, budget_window_id="w"), request_id_factory=lambda: ID_A)
        self.assertNotIn("raw-secret", str(context.exception))
        self.assertEqual(self.budget.snapshot(scope, "w").consumed, 1)
        scope = "unexpected"
        self.budget.configure(scope, "w", 2)
        class ExplodingBroker:
            def fetch_candles(self, request):
                raise RuntimeError("raw credentials and body")
        with self.assertRaises(UnexpectedBrokerException) as context:
            run_planned_request(self.planned, ExplodingBroker(), self.budget, RetryPolicy(budget_scope=scope, budget_window_id="w"), request_id_factory=lambda: ID_A)
        self.assertNotIn("raw credentials", str(context.exception))
        self.assertEqual(self.budget.snapshot(scope, "w").consumed, 1)

    def test_result_model_rejects_contradictory_flags(self):
        kwargs = dict(attempt_history=(), final_outcome="SUCCESS", final_response=None, request_fingerprint=self.planned.fingerprint, total_budget_units_consumed=0, budget_exhausted=False, attempt_limit_exhausted=False, reauthentication_required=False, succeeded=True)
        with self.assertRaises(ValueError):
            BudgetedBrokerResult(**{**kwargs, "attempt_limit_exhausted": True})
        with self.assertRaises(ValueError):
            BudgetedBrokerResult(**{**kwargs, "budget_exhausted": True})
        with self.assertRaises(ValueError):
            BudgetedBrokerResult(**{**kwargs, "succeeded": False, "attempt_limit_exhausted": True})

    def test_fake_sequence_exhaustion_is_admitted_and_classified(self):
        scope = "sequence"
        self.budget.configure(scope, "w", 2)
        fake = DeterministicFakeBroker([ZerodhaBrokerError(BrokerErrorCode.BROKER_TIMEOUT)])
        result = run_planned_request(self.planned, fake, self.budget, RetryPolicy(budget_scope=scope, budget_window_id="w"), request_id_factory=iter((ID_A, ID_B)).__next__)
        self.assertEqual(result.final_outcome, BrokerErrorCode.INTERNAL_BROKER_FAILURE.value)
        self.assertEqual(fake.call_count, 2)
        self.assertEqual(result.total_budget_units_consumed, 2)

    def test_budget_exhaustion_prevents_broker_call_and_does_not_refund(self):
        self.budget.configure("zero", "w", 0)
        fake = DeterministicFakeBroker([response()])
        result = run_planned_request(self.planned, fake, self.budget, RetryPolicy(budget_scope="zero", budget_window_id="w"), request_id_factory=lambda: ID_A)
        self.assertTrue(result.budget_exhausted)
        self.assertEqual(fake.call_count, 0)
        self.assertEqual(result.total_budget_units_consumed, 0)

    def test_budget_exhaustion_before_retry_stops_without_call(self):
        self.budget.configure("one", "w", 1)
        fake = DeterministicFakeBroker([ZerodhaBrokerError(BrokerErrorCode.BROKER_TIMEOUT), response()])
        result = run_planned_request(self.planned, fake, self.budget, RetryPolicy(budget_scope="one", budget_window_id="w"), request_id_factory=iter((ID_A, ID_B)).__next__)
        self.assertTrue(result.budget_exhausted)
        self.assertEqual(fake.call_count, 1)
        self.assertEqual(result.total_budget_units_consumed, 1)

    def test_max_attempts_and_no_extra_consumption_after_terminal(self):
        self.budget.configure("max", "w", 5)
        result = run_planned_request(self.planned, DeterministicFakeBroker([response(status=500, body=b"x", error_code=BrokerErrorCode.PROVIDER_5XX)] * 3), self.budget, RetryPolicy(maximum_attempts=3, budget_scope="max", budget_window_id="w"), request_id_factory=iter((ID_A, ID_B, str(__import__("uuid").uuid4()))).__next__)
        self.assertEqual(len(result.attempt_history), 3)
        self.assertEqual(self.budget.snapshot("max", "w").consumed, 3)

    def test_backoff_formula_cap_jitter_and_retry_after(self):
        policy = RetryPolicy(backoff_base=timedelta(seconds=1), backoff_cap=timedelta(seconds=3), jitter_max=timedelta(milliseconds=250), budget_scope="s", budget_window_id="w")
        self.assertEqual(calculate_retry_delay(policy, 1), timedelta(seconds=1))
        self.assertEqual(calculate_retry_delay(policy, 2, jitter_source=lambda _: timedelta(milliseconds=250)), timedelta(seconds=2, milliseconds=250))
        self.assertEqual(calculate_retry_delay(policy, 5), timedelta(seconds=3))
        self.assertEqual(calculate_retry_delay(policy, 1, retry_after_seconds=60), timedelta(seconds=60))

    def test_retry_policy_rejects_boolean_integer_and_invalid_bounds(self):
        cases = (
            {"maximum_attempts": True},
            {"maximum_attempts": 0},
            {"backoff_base": timedelta(seconds=-1)},
            {"backoff_cap": timedelta(seconds=1), "backoff_base": timedelta(seconds=2)},
            {"budget_scope": "", "budget_window_id": "w"},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(Exception):
                RetryPolicy(budget_scope="s", budget_window_id="w", **changes)

    def test_ids_are_valid_unique_and_planning_is_unchanged(self):
        before = self.planned
        with self.assertRaises(InvalidRequestIdError):
            run_planned_request(self.planned, DeterministicFakeBroker([response()]), self.budget, self.policy, request_id_factory=lambda: "bad")
        self.assertEqual(self.budget.snapshot("zerodha-test", "window-a").consumed, 0)
        with self.assertRaises(DuplicateRequestIdError):
            run_planned_request(self.planned, DeterministicFakeBroker([ZerodhaBrokerError(BrokerErrorCode.BROKER_TIMEOUT), response()]), self.budget, self.policy, request_id_factory=lambda: ID_A)
        self.assertEqual(self.budget.snapshot("zerodha-test", "window-a").consumed, 1)
        self.assertEqual(before, self.planned)

    def test_result_and_attempt_history_are_immutable_and_safe(self):
        result = self.run_request([response(status=429, body=b"secret raw body", error_code=BrokerErrorCode.PROVIDER_429)])
        with self.assertRaises(FrozenInstanceError):
            result.attempt_history[0].request_id = ID_B
        self.assertNotIn("secret raw body", repr(result))
        self.assertNotIn("secret raw body", repr(result.attempt_history[0]))
        self.assertNotIn("access_token", repr(result))

    def test_budget_identity_is_shared_and_durable_after_reopen(self):
        self.budget.configure("shared", "w", 2)
        policy = RetryPolicy(budget_scope="shared", budget_window_id="w")
        run_planned_request(self.planned, DeterministicFakeBroker([response()]), self.budget, policy, request_id_factory=lambda: ID_A)
        reopened = RequestBudget(Path(self.temp.name) / "budget.sqlite")
        result = run_planned_request(self.planned, DeterministicFakeBroker([response()]), reopened, policy, request_id_factory=lambda: ID_B)
        self.assertTrue(result.succeeded)
        self.assertEqual(reopened.snapshot("shared", "w").consumed, 2)

    def test_same_scope_different_windows_are_isolated(self):
        self.budget.configure("isolated", "window-a", 1)
        self.budget.configure("isolated", "window-b", 1)
        for window, request_id in (("window-a", ID_A), ("window-b", ID_B)):
            result = run_planned_request(self.planned, DeterministicFakeBroker([response()]), self.budget, RetryPolicy(budget_scope="isolated", budget_window_id=window), request_id_factory=lambda request_id=request_id: request_id)
            self.assertTrue(result.succeeded)
        self.assertEqual(self.budget.snapshot("isolated", "window-a").consumed, 1)
        self.assertEqual(self.budget.snapshot("isolated", "window-b").consumed, 1)


if __name__ == "__main__":
    unittest.main()
