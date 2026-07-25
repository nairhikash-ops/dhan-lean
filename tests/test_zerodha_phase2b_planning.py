import hashlib
import json
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from dhan_lean.data.models import DataWorkItem, TimeWindow
from dhan_lean.providers.zerodha import (
    BrokerErrorCode,
    DeterministicFakeBroker,
    InstrumentQuery,
    InstrumentSnapshot,
    PlanningErrorCode,
    ZerodhaPlanningError,
    ZerodhaPlanningInput,
    parse_instrument_snapshot,
    plan_historical_candles,
    resolve_instrument,
)
from dhan_lean.providers.zerodha.broker_protocol import BrokerResponse
from dhan_lean.providers.zerodha.planning import _canonical_decimal, _fingerprint


FIXTURES = Path(__file__).parent / "fixtures" / "zerodha"
IST = ZoneInfo("Asia/Kolkata")
SNAPSHOT_DATE = date(2026, 7, 20)
REQUEST_ID_A = "12345678-1234-4678-8123-123456789abc"
REQUEST_ID_B = "87654321-4321-4876-8123-cba987654321"


def load_snapshot() -> InstrumentSnapshot:
    return parse_instrument_snapshot((FIXTURES / "instrument_master.csv").read_bytes(), SNAPSHOT_DATE)


SNAPSHOT = load_snapshot()
EQUITY = resolve_instrument(SNAPSHOT, InstrumentQuery("NSE", "ACME", "EQ"))
FUTURE = resolve_instrument(SNAPSHOT, InstrumentQuery("NFO", "NIFTY26JULFUT", "FUT", date(2026, 7, 30)))
OPTION = resolve_instrument(SNAPSHOT, InstrumentQuery("NFO", "NIFTY26JUL25000CE", "CE", date(2026, 7, 30), Decimal("25000")))


def work_item(*, symbol="ACME", source_id="zerodha", bar_size="1m", start=None, end=None, session_date=SNAPSHOT_DATE):
    start = start or datetime(2026, 7, 20, 9, 15, tzinfo=IST)
    end = end or datetime(2026, 7, 20, 15, 30, tzinfo=IST)
    return DataWorkItem(symbol, source_id, bar_size, session_date, TimeWindow(start, end), Path("output"), "work-item")


def planning_input(*, item=None, instrument=EQUITY, snapshot=SNAPSHOT, exchange="NSE", oi=False, continuous=False):
    return ZerodhaPlanningInput(item or work_item(symbol=instrument.tradingsymbol), instrument, snapshot, exchange, oi=oi, continuous=continuous)


def fixed_request_id(value=REQUEST_ID_A):
    return lambda: value


def invalid_window(start, end):
    value = object.__new__(TimeWindow)
    object.__setattr__(value, "start", start)
    object.__setattr__(value, "end", end)
    object.__setattr__(value, "interval_minutes", 1)
    return value


class TestZerodhaPlanning(unittest.TestCase):
    def test_valid_equity_future_option_and_oi_requests(self):
        equity = plan_historical_candles(planning_input(), request_id_factory=fixed_request_id())
        future = plan_historical_candles(planning_input(item=work_item(symbol=FUTURE.tradingsymbol), instrument=FUTURE, exchange="NFO"), request_id_factory=fixed_request_id())
        option = plan_historical_candles(planning_input(item=work_item(symbol=OPTION.tradingsymbol), instrument=OPTION, exchange="NFO", oi=True), request_id_factory=fixed_request_id())
        self.assertEqual((equity.provider_instrument_id, future.provider_instrument_id, option.provider_instrument_id), ("1001", "2001", "3001"))
        self.assertEqual(future.expiry, date(2026, 7, 30))
        self.assertEqual(option.strike, Decimal("25000"))
        self.assertFalse(equity.candle_request.oi)
        self.assertTrue(option.candle_request.oi)

    def test_request_window_normalizes_offsets_and_preserves_instants(self):
        utc_item = work_item(
            start=datetime(2026, 7, 20, 3, 45, tzinfo=timezone.utc),
            end=datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc),
        )
        ist_item = work_item(
            start=datetime(2026, 7, 20, 9, 15, tzinfo=IST),
            end=datetime(2026, 7, 20, 9, 30, tzinfo=IST),
        )
        first = plan_historical_candles(planning_input(item=utc_item), request_id_factory=fixed_request_id())
        second = plan_historical_candles(planning_input(item=ist_item), request_id_factory=fixed_request_id())
        self.assertEqual(first.candle_request.from_timestamp, second.candle_request.from_timestamp)
        self.assertEqual(first.candle_request.to_timestamp, second.candle_request.to_timestamp)
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_repeated_planning_is_deterministic_except_request_uuid(self):
        first = plan_historical_candles(planning_input(), request_id_factory=fixed_request_id(REQUEST_ID_A))
        second = plan_historical_candles(planning_input(), request_id_factory=fixed_request_id(REQUEST_ID_B))
        self.assertNotEqual(first.candle_request.request_id, second.candle_request.request_id)
        self.assertEqual(first.canonical_metadata, second.canonical_metadata)
        self.assertEqual(first.fingerprint, second.fingerprint)

    def test_rejects_invalid_identity_and_modes(self):
        cases = (
            (planning_input(item=work_item(source_id="dhan")), PlanningErrorCode.UNSUPPORTED_SOURCE),
            (planning_input(item=work_item(bar_size="5m")), PlanningErrorCode.UNSUPPORTED_RESOLUTION),
            (planning_input(item=work_item(symbol="OTHER")), PlanningErrorCode.SYMBOL_MISMATCH),
            (planning_input(exchange="NFO"), PlanningErrorCode.EXCHANGE_MISMATCH),
            (planning_input(continuous=True), PlanningErrorCode.UNSUPPORTED_CONTINUOUS_MODE),
            (planning_input(instrument=replace(EQUITY, instrument_type="BAD")), PlanningErrorCode.UNSUPPORTED_INSTRUMENT_TYPE),
        )
        for value, code in cases:
            with self.subTest(code=code), self.assertRaises(ZerodhaPlanningError) as context:
                plan_historical_candles(value)
            self.assertEqual(context.exception.code, code)

    def test_invalid_resolved_identity_is_checked_before_mismatch(self):
        for value in (None, 123, "", " "):
            with self.subTest(value=value), self.assertRaises(ZerodhaPlanningError) as context:
                plan_historical_candles(planning_input(instrument=replace(EQUITY, exchange=value)))
            self.assertEqual(context.exception.code, PlanningErrorCode.INVALID_RESOLVED_INSTRUMENT)
        with self.assertRaises(ZerodhaPlanningError) as context:
            plan_historical_candles(planning_input(exchange="BSE"))
        self.assertEqual(context.exception.code, PlanningErrorCode.EXCHANGE_MISMATCH)
        with self.assertRaises(ZerodhaPlanningError) as context:
            plan_historical_candles(planning_input(instrument=replace(EQUITY, tradingsymbol="")))
        self.assertEqual(context.exception.code, PlanningErrorCode.INVALID_RESOLVED_INSTRUMENT)

    def test_rejects_missing_or_invalid_instrument_token(self):
        for token in ("", "0", "-1", "+1", "1.0", " 1001", "1001 ", "abc"):
            with self.subTest(token=token), self.assertRaises(ZerodhaPlanningError) as context:
                plan_historical_candles(planning_input(instrument=replace(EQUITY, instrument_token=token)))
            self.assertEqual(context.exception.code, PlanningErrorCode.INVALID_RESOLVED_INSTRUMENT)

    def test_rejects_invalid_snapshot_hash(self):
        for value in ("", "A" * 64, "0" * 63, "g" * 64, "hash"):
            bad_snapshot = replace(SNAPSHOT, content_sha256=value)
            with self.subTest(value=value), self.assertRaises(ZerodhaPlanningError) as context:
                plan_historical_candles(planning_input(snapshot=bad_snapshot))
            self.assertEqual(context.exception.code, PlanningErrorCode.INVALID_SNAPSHOT_HASH)

    def test_rejects_window_errors(self):
        cases = (
            (replace(work_item(), window=invalid_window(datetime(2026, 7, 20, 9, 15), datetime(2026, 7, 20, 9, 30, tzinfo=IST))), PlanningErrorCode.INVALID_WORK_ITEM_WINDOW),
            (work_item(start=datetime(2026, 7, 20, 9, 15, 30, tzinfo=IST)), PlanningErrorCode.NON_MINUTE_ALIGNED_WINDOW),
            (replace(work_item(), window=invalid_window(datetime(2026, 7, 20, 9, 30, tzinfo=IST), datetime(2026, 7, 20, 9, 15, tzinfo=IST))), PlanningErrorCode.INVALID_WORK_ITEM_WINDOW),
            (work_item(start=datetime(2026, 7, 20, 9, 15, tzinfo=IST), end=datetime(2026, 7, 21, 9, 15, tzinfo=IST)), PlanningErrorCode.CROSS_SESSION_WINDOW),
            (work_item(start=datetime(2026, 7, 19, 9, 15, tzinfo=IST), end=datetime(2026, 7, 19, 9, 30, tzinfo=IST)), PlanningErrorCode.SESSION_DATE_MISMATCH),
            (work_item(start=datetime(2026, 7, 20, 9, 0, tzinfo=IST), end=datetime(2026, 7, 20, 9, 30, tzinfo=IST)), PlanningErrorCode.WINDOW_OUTSIDE_SESSION),
            (work_item(start=datetime(2026, 7, 20, 15, 15, tzinfo=IST), end=datetime(2026, 7, 20, 15, 31, tzinfo=IST)), PlanningErrorCode.WINDOW_OUTSIDE_SESSION),
            (replace(work_item(), window=invalid_window(datetime(2026, 7, 20, 9, 15, tzinfo=IST), datetime(2026, 7, 20, 9, 15, tzinfo=IST))), PlanningErrorCode.INVALID_WORK_ITEM_WINDOW),
        )
        for item, code in cases:
            with self.subTest(code=code), self.assertRaises(ZerodhaPlanningError) as context:
                plan_historical_candles(planning_input(item=item))
            self.assertEqual(context.exception.code, code)

    def test_rejects_naive_and_invalid_derivative_identity(self):
        naive = replace(work_item(), window=invalid_window(datetime(2026, 7, 20, 9, 15), datetime(2026, 7, 20, 9, 30, tzinfo=IST)))
        with self.assertRaises(ZerodhaPlanningError):
            plan_historical_candles(planning_input(item=naive))
        bad_future = replace(FUTURE, expiry=None)
        with self.assertRaises(ZerodhaPlanningError) as context:
            plan_historical_candles(planning_input(item=work_item(symbol=FUTURE.tradingsymbol), instrument=bad_future, exchange="NFO"))
        self.assertEqual(context.exception.code, PlanningErrorCode.INVALID_DERIVATIVE_IDENTITY)
        bad_option = replace(OPTION, strike=Decimal("NaN"))
        with self.assertRaises(ZerodhaPlanningError):
            plan_historical_candles(planning_input(item=work_item(symbol=OPTION.tradingsymbol), instrument=bad_option, exchange="NFO"))

    def test_derivative_session_date_must_not_be_after_expiry(self):
        before = plan_historical_candles(planning_input(item=work_item(symbol=FUTURE.tradingsymbol, session_date=date(2026, 7, 29), start=datetime(2026, 7, 29, 9, 15, tzinfo=IST), end=datetime(2026, 7, 29, 9, 30, tzinfo=IST)), instrument=FUTURE, exchange="NFO"), request_id_factory=fixed_request_id())
        on_expiry = plan_historical_candles(planning_input(item=work_item(symbol=FUTURE.tradingsymbol, session_date=date(2026, 7, 30), start=datetime(2026, 7, 30, 9, 15, tzinfo=IST), end=datetime(2026, 7, 30, 9, 30, tzinfo=IST)), instrument=FUTURE, exchange="NFO"), request_id_factory=fixed_request_id())
        self.assertEqual(before.session_date, date(2026, 7, 29))
        self.assertEqual(on_expiry.session_date, date(2026, 7, 30))
        after_item = work_item(symbol=FUTURE.tradingsymbol, session_date=date(2026, 7, 31), start=datetime(2026, 7, 31, 9, 15, tzinfo=IST), end=datetime(2026, 7, 31, 9, 30, tzinfo=IST))
        with self.assertRaises(ZerodhaPlanningError) as context:
            plan_historical_candles(planning_input(item=after_item, instrument=FUTURE, exchange="NFO"))
        self.assertEqual(context.exception.code, PlanningErrorCode.INVALID_DERIVATIVE_IDENTITY)
        equity = plan_historical_candles(planning_input(item=work_item(session_date=date(2027, 1, 1), start=datetime(2027, 1, 1, 9, 15, tzinfo=IST), end=datetime(2027, 1, 1, 9, 30, tzinfo=IST))), request_id_factory=fixed_request_id())
        self.assertEqual(equity.session_date, date(2027, 1, 1))

    def test_session_boundaries_are_half_open_and_exact(self):
        for start, end in (
            (datetime(2026, 7, 20, 9, 15, tzinfo=IST), datetime(2026, 7, 20, 9, 30, tzinfo=IST)),
            (datetime(2026, 7, 20, 15, 29, tzinfo=IST), datetime(2026, 7, 20, 15, 30, tzinfo=IST)),
            (datetime(2026, 7, 20, 10, 0, tzinfo=IST), datetime(2026, 7, 20, 11, 0, tzinfo=IST)),
        ):
            with self.subTest(start=start, end=end):
                planned = plan_historical_candles(planning_input(item=work_item(start=start, end=end)), request_id_factory=fixed_request_id())
                self.assertEqual(planned.candle_request.from_timestamp, start)
                self.assertEqual(planned.candle_request.to_timestamp, end)


class TestZerodhaFingerprints(unittest.TestCase):
    def test_digest_is_lowercase_sha256_and_metadata_is_safe(self):
        planned = plan_historical_candles(planning_input(), request_id_factory=fixed_request_id())
        self.assertRegex(planned.fingerprint, r"^[0-9a-f]{64}$")
        forbidden = ("api_secret", "access_token", "request_token", "authorization", "cookie", "http://", "https://", "output")
        serialized = json.dumps(dict(planned.canonical_metadata), separators=(",", ":"), sort_keys=False).lower()
        self.assertFalse(any(value in serialized for value in forbidden))
        self.assertNotIn("request_id", planned.canonical_metadata)
        self.assertNotIn("run_id", serialized)
        self.assertNotIn("attempt_number", serialized)

    def test_canonical_bytes_are_cross_platform_stable(self):
        planned = plan_historical_candles(planning_input(), request_id_factory=fixed_request_id())
        encoded = json.dumps(dict(planned.canonical_metadata), ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.assertEqual(planned.fingerprint, hashlib.sha256(encoded).hexdigest())

    def test_decimal_equivalence_and_meaningful_fields(self):
        first = plan_historical_candles(planning_input(item=work_item(symbol=OPTION.tradingsymbol), instrument=OPTION, exchange="NFO"), request_id_factory=fixed_request_id())
        equal_strike = replace(OPTION, strike=Decimal("25000.00"))
        second = plan_historical_candles(planning_input(item=work_item(symbol=OPTION.tradingsymbol), instrument=equal_strike, exchange="NFO"), request_id_factory=fixed_request_id())
        self.assertEqual(first.fingerprint, second.fingerprint)
        for key, value in (
            ("provider_instrument_id", "9999"),
            ("interval", "day"),
            ("from_timestamp", "2026-07-20T09:16:00+05:30"),
            ("oi", True),
            ("instrument_snapshot_sha256", "b" * 64),
            ("expiry", "2026-08-30"),
            ("strike", "25001"),
            ("exchange", "BSE"),
            ("tradingsymbol", "OTHER"),
        ):
            altered = dict(first.canonical_metadata)
            altered[key] = value
            self.assertNotEqual(first.fingerprint, _fingerprint(altered), key)

    def test_decimal_zero_and_scientific_values_are_canonical(self):
        self.assertEqual({_canonical_decimal(Decimal(value)) for value in ("0", "0.0", "0.00", "-0", "-0.0")}, {"0"})
        zero_positive = replace(OPTION, strike=Decimal("0.0"))
        zero_negative = replace(OPTION, strike=Decimal("-0.0"))
        first = plan_historical_candles(planning_input(item=work_item(symbol=OPTION.tradingsymbol), instrument=zero_positive, exchange="NFO"), request_id_factory=fixed_request_id())
        second = plan_historical_candles(planning_input(item=work_item(symbol=OPTION.tradingsymbol), instrument=zero_negative, exchange="NFO"), request_id_factory=fixed_request_id())
        self.assertEqual(first.canonical_metadata["strike"], "0")
        self.assertEqual(first.canonical_metadata, second.canonical_metadata)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(_canonical_decimal(Decimal("1E-7")), "0.0000001")
        self.assertEqual(_canonical_decimal(Decimal("100.00")), "100")

    def test_fingerprint_sorting_is_insertion_order_independent_including_nested_values(self):
        first = {"z": 1, "nested": {"b": 2, "a": 1}, "a": "value"}
        second = {"a": "value", "nested": {"a": 1, "b": 2}, "z": 1}
        self.assertEqual(_fingerprint(first), _fingerprint(second))
        self.assertRegex(_fingerprint(first), r"^[0-9a-f]{64}$")
        changed = dict(second)
        changed["nested"] = {"a": 1, "b": 3}
        self.assertNotEqual(_fingerprint(first), _fingerprint(changed))

    def test_fake_broker_accepts_planned_request_without_credentials(self):
        planned = plan_historical_candles(planning_input(), request_id_factory=fixed_request_id())
        body = b'{"status":"success","data":{"candles":[]}}'
        response = BrokerResponse.for_provider(request_id=REQUEST_ID_A, broker_request_id=REQUEST_ID_B, captured_at=datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc), status=200, body=body)
        fake = DeterministicFakeBroker([response])
        result = fake.fetch_candles(planned.candle_request)
        self.assertEqual(fake.requests, [planned.candle_request])
        self.assertEqual(result.request_id, planned.candle_request.request_id)
        self.assertEqual(result.body, body)

    def test_planning_errors_are_stable_and_safe(self):
        with self.assertRaises(ZerodhaPlanningError) as context:
            plan_historical_candles(planning_input(item=work_item(symbol="OTHER")))
        self.assertEqual(context.exception.code, PlanningErrorCode.SYMBOL_MISMATCH)
        self.assertNotIn("DataWorkItem", str(context.exception))
        self.assertNotIn("output", repr(context.exception))


if __name__ == "__main__":
    unittest.main()
