import gzip
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from dataclasses import FrozenInstanceError

from dhan_lean.providers.zerodha.historical import HistoricalCandleParseError, parse_historical_candles
from dhan_lean.providers.zerodha.instruments import (
    AmbiguousInstrumentError,
    InstrumentMasterParseError,
    InstrumentNotFoundError,
    InstrumentQuery,
    parse_instrument_snapshot,
    resolve_instrument,
)


FIXTURES = Path(__file__).parent / "fixtures" / "zerodha"
IST = ZoneInfo("Asia/Kolkata")


class TestZerodhaHistoricalParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        snapshot = parse_instrument_snapshot(
            gzip.compress((FIXTURES / "instrument_master.csv").read_bytes(), mtime=0), date(2026, 7, 20)
        )
        cls.instrument = resolve_instrument(snapshot, InstrumentQuery("NSE", "ACME", "EQ"))

    def parse(self, name):
        return parse_historical_candles((FIXTURES / name).read_bytes(), self.instrument)

    def test_six_field_response_uses_decimal_and_ist(self):
        result = self.parse("historical_valid.json")
        self.assertEqual(result.bars[0].open, Decimal("100.1"))
        self.assertEqual(result.bars[0].timestamp.tzinfo, IST)
        self.assertEqual(result.bars[0].volume, 1000)
        self.assertFalse(result.had_open_interest)

    def test_utc_instant_is_preserved_when_normalized(self):
        payload = {"status":"success","data":{"candles":[["2026-07-20T03:45:00+0000",100,101,99,100,1]]}}
        bar = parse_historical_candles(payload, self.instrument).bars[0]
        self.assertEqual(bar.timestamp, datetime(2026, 7, 20, 9, 15, tzinfo=IST))
        self.assertEqual(bar.timestamp.astimezone(timezone.utc).hour, 3)

    def test_oi_stays_outside_normalized_bar(self):
        result = self.parse("historical_oi.json")
        self.assertTrue(result.had_open_interest)
        self.assertEqual(result.open_interest, (Decimal("25000"),))
        self.assertFalse(hasattr(result.bars[0], "open_interest"))

    def test_empty_response_is_immutable(self):
        result = self.parse("historical_empty.json")
        self.assertEqual(result.bars, ())
        with self.assertRaises(FrozenInstanceError):
            result.bars += ()

    def test_rejects_malformed_cases_without_repair(self):
        for name in (
            "historical_malformed_envelope.json", "historical_invalid_timestamp.json",
            "historical_naive_timestamp.json", "historical_invalid_ohlc.json",
            "historical_invalid_price.json", "historical_fractional_volume.json",
            "historical_duplicate_timestamps.json", "historical_out_of_order.json",
        ):
            with self.subTest(name=name), self.assertRaises(HistoricalCandleParseError):
                self.parse(name)

    def test_rejects_all_malformed_envelopes(self):
        cases = [
            {},
            {"status": "error", "data": {"candles": []}},
            {"status": "success"},
            {"status": "success", "data": []},
            {"status": "success", "data": {}},
            {"status": "success", "data": {"candles": "not-a-list"}},
            b"not-json",
        ]
        for payload in cases:
            with self.subTest(payload=payload), self.assertRaises(HistoricalCandleParseError):
                parse_historical_candles(payload, self.instrument)

    def test_rejects_negative_zero_and_same_instant_duplicate(self):
        negative_zero = {"status":"success","data":{"candles":[["2026-07-20T09:15:00+0530",-0.0,101,99,100,1]]}}
        with self.assertRaises(HistoricalCandleParseError):
            parse_historical_candles(negative_zero, self.instrument)
        same_instant = {"status":"success","data":{"candles":[
            ["2026-07-20T09:15:00+0530",100,101,99,100,1],
            ["2026-07-20T03:45:00+0000",100,101,99,100,1],
        ]}}
        with self.assertRaises(HistoricalCandleParseError):
            parse_historical_candles(same_instant, self.instrument)

    def test_rejects_mixed_six_and_seven_field_schemas(self):
        mixed = {"status":"success","data":{"candles":[
            ["2026-07-20T09:15:00+0530",100,101,99,100,1],
            ["2026-07-20T09:16:00+0530",100,101,99,100,1,10],
        ]}}
        with self.assertRaises(HistoricalCandleParseError):
            parse_historical_candles(mixed, self.instrument)

    def test_rejects_null_non_finite_and_negative_values(self):
        for value in (None, "NaN", "Infinity", -1):
            payload = {"status":"success","data":{"candles":[["2026-07-20T09:15:00+0530",value,101,99,100,1]]}}
            with self.subTest(value=value), self.assertRaises(HistoricalCandleParseError):
                parse_historical_candles(payload, self.instrument)

    def test_rejects_boolean_numbers_and_malformed_row_length(self):
        for row in [["2026-07-20T09:15:00+0530", True, 1, 1, 1, 1], ["2026-07-20T09:15:00+0530", 1, 1, 1, 1, 1, 2, 3]]:
            with self.subTest(row=row), self.assertRaises(HistoricalCandleParseError):
                parse_historical_candles({"status":"success","data":{"candles":[row]}}, self.instrument)


class TestZerodhaInstrumentResolver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (FIXTURES / "instrument_master.csv").read_bytes()
        cls.snapshot = parse_instrument_snapshot(gzip.compress(cls.raw, mtime=0), date(2026, 7, 20))

    def test_snapshot_hash_is_deterministic_and_dated(self):
        compressed = gzip.compress(self.raw, mtime=0)
        a = parse_instrument_snapshot(compressed, date(2026, 7, 20))
        b = parse_instrument_snapshot(compressed, date(2026, 7, 20))
        self.assertEqual(a.content_sha256, b.content_sha256)
        self.assertEqual(a.snapshot_date, date(2026, 7, 20))

        different_gzip_header = gzip.compress(self.raw, mtime=1)
        self.assertNotEqual(compressed, different_gzip_header)
        c = parse_instrument_snapshot(different_gzip_header, date(2026, 7, 20))
        self.assertNotEqual(a.content_sha256, c.content_sha256)

    def test_exact_equity_future_option_and_expired_future_resolution(self):
        self.assertEqual(resolve_instrument(self.snapshot, InstrumentQuery("NSE", "ACME", "EQ")).instrument_token, "1001")
        self.assertEqual(resolve_instrument(self.snapshot, InstrumentQuery("NFO", "NIFTY26JULFUT", "FUT", date(2026, 7, 30))).instrument_token, "2001")
        self.assertEqual(resolve_instrument(self.snapshot, InstrumentQuery("NFO", "NIFTY26JUL25000CE", "CE", date(2026, 7, 30), Decimal("25000"))).instrument_token, "3001")
        self.assertEqual(resolve_instrument(self.snapshot, InstrumentQuery("NFO", "NIFTY26JUL25000CE", "CE", date(2026, 7, 30), Decimal("25000.0"))).instrument_token, "3001")
        self.assertEqual(resolve_instrument(self.snapshot, InstrumentQuery("NFO", "OLD26JANFUT", "FUT", date(2026, 1, 29))).instrument_token, "4001")

    def test_query_contract_rejects_float_integer_and_datetime_strikes_or_expiries(self):
        with self.assertRaises(TypeError):
            InstrumentQuery("NFO", "NIFTY26JUL25000CE", "CE", date(2026, 7, 30), 25000.0)
        with self.assertRaises(TypeError):
            InstrumentQuery("NFO", "NIFTY26JUL25000CE", "CE", date(2026, 7, 30), 25000)
        with self.assertRaises(TypeError):
            InstrumentQuery("NFO", "NIFTY26JUL25000CE", "CE", datetime(2026, 7, 30), Decimal("25000"))

    def test_query_contract_invalid_combinations_raise(self):
        invalid = [
            ("NSE", "ACME", "EQ", date(2026, 7, 30), None),
            ("NFO", "NIFTY26JULFUT", "FUT", None, None),
            ("NFO", "NIFTY26JULFUT", "FUT", date(2026, 7, 30), Decimal("1")),
            ("NFO", "NIFTY26JUL25000CE", "CE", date(2026, 7, 30), None),
            ("NFO", "UNKNOWN", "BAD", None, None),
        ]
        for args in invalid:
            with self.subTest(args=args), self.assertRaises((TypeError, ValueError)):
                InstrumentQuery(*args)

    def _snapshot_for_row(self, row: str):
        header = self.raw.splitlines()[0].decode("utf-8") + "\n"
        return parse_instrument_snapshot(gzip.compress((header + row + "\n").encode("utf-8"), mtime=0), date(2026, 7, 20))

    def test_row_semantics_reject_blank_identity_unsupported_type_and_bad_derivative_fields(self):
        rows = [
            ",501,ACME,Acme,100.5,,,0.05,1,EQ,NSE,NSE",
            "1001,501, ACME,Acme,100.5,,,0.05,1,EQ,NSE,NSE",
            "abc,501,ACME,Acme,100.5,,,0.05,1,EQ,NSE,NSE",
            "1001,501,ACME,Acme,100.5,,,0.05,1,UNKNOWN,NSE,NSE",
            "1001,501,ACME,Acme,100.5,2026-07-30,,0.05,1,EQ,NSE,NSE",
            "1001,501,ACME,Acme,100.5,,,1,0.05,1,EQ,NSE,NSE",
            "2001,601,FUT,Future,100,,,0.05,1,FUT,NFO-FUT,NFO",
            "2001,601,FUT,Future,100,2026-07-30,1,0.05,1,FUT,NFO-FUT,NFO",
            "3001,701,OPT,Option,100,,25000,0.05,1,CE,NFO-OPT,NFO",
            "3001,701,OPT,Option,100,2026-07-30,,0.05,1,CE,NFO-OPT,NFO",
        ]
        for row in rows:
            with self.subTest(row=row), self.assertRaises(InstrumentMasterParseError):
                self._snapshot_for_row(row)

    def test_missing_and_ambiguous_matches_are_typed(self):
        with self.assertRaises(InstrumentNotFoundError):
            resolve_instrument(self.snapshot, InstrumentQuery("NSE", "ACME", "FUT", date(2026, 7, 30)))
        records = self.snapshot.instruments + (self.snapshot.instruments[0],)
        ambiguous = type(self.snapshot)(self.snapshot.snapshot_date, self.snapshot.content_sha256, records)
        with self.assertRaises(AmbiguousInstrumentError):
            resolve_instrument(ambiguous, InstrumentQuery("NSE", "ACME", "EQ"))

    def test_malformed_csv_row_is_rejected(self):
        bad = self.raw + b"1002,502,TOO,FEW\n"
        with self.assertRaises(InstrumentMasterParseError):
            parse_instrument_snapshot(gzip.compress(bad, mtime=0), date(2026, 7, 20))

        quoted = self.raw.splitlines()[0] + b"\n1002,502,AC\"ME,Name,1,,,,1,EQ,NSE,NSE\n"
        with self.assertRaises(InstrumentMasterParseError):
            parse_instrument_snapshot(gzip.compress(quoted, mtime=0), date(2026, 7, 20))

    def test_no_credential_fields_in_fixture_or_errors(self):
        forbidden = ("api_secret", "access_token", "Authorization", "request_token")
        for path in FIXTURES.iterdir():
            self.assertFalse(any(word.encode() in path.read_bytes() for word in forbidden))
        with self.assertRaises(InstrumentNotFoundError) as ctx:
            resolve_instrument(self.snapshot, InstrumentQuery("NSE", "MISSING", "EQ"))
        self.assertFalse(any(word in str(ctx.exception) for word in forbidden))


if __name__ == "__main__":
    unittest.main()
