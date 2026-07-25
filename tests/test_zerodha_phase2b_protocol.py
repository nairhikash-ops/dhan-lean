import hashlib
import json
import struct
import unittest
import uuid
from datetime import datetime, timedelta, timezone

from dhan_lean.providers.zerodha.broker_protocol import (
    MAX_REQUEST_PAYLOAD,
    MAX_RESPONSE_BODY,
    MAX_RESPONSE_PAYLOAD,
    BrokerErrorCode,
    BrokerRequestValidationError,
    BrokerResponse,
    BrokerResponseValidationError,
    CandleRequest,
    FramingError,
    PROVIDER_ERROR_CODES,
    SessionState,
    TransportStatus,
    ZerodhaBrokerError,
    decode_request,
    decode_response,
    decode_json_frame,
    encode_request,
    encode_response,
    error_policy,
)
from dhan_lean.providers.zerodha.fake_broker import (
    DeterministicFakeBroker,
    FakeBrokerSequenceExhausted,
    FakeBrokerUnexpectedRequest,
)


REQUEST_ID = "12345678-1234-4678-8123-123456789abc"
BROKER_ID = "87654321-4321-4876-8123-cba987654321"
IST = timezone(timedelta(hours=5, minutes=30))
CAPTURED = datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc)


def request(**changes):
    values = {
        "protocol_version": 1,
        "request_id": REQUEST_ID,
        "instrument_token": "123456",
        "interval": "minute",
        "from_timestamp": datetime(2026, 7, 20, 9, 15, tzinfo=IST),
        "to_timestamp": datetime(2026, 7, 20, 15, 30, tzinfo=IST),
        "continuous": False,
        "oi": False,
    }
    values.update(changes)
    return CandleRequest(**values)


def provider_response(body=b'{"status":"success"}', status=200, **changes):
    values = dict(
        request_id=REQUEST_ID,
        broker_request_id=BROKER_ID,
        captured_at=CAPTURED,
        status=status,
        body=body,
    )
    values.update(changes)
    return BrokerResponse.for_provider(**values)


class TestCandleRequest(unittest.TestCase):
    def test_valid_request_normalizes_to_ist_and_preserves_instant(self):
        value = request(
            from_timestamp=datetime(2026, 7, 20, 3, 45, tzinfo=timezone.utc),
            to_timestamp=datetime(2026, 7, 20, 4, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(value.from_timestamp.hour, 9)
        self.assertEqual(value.from_timestamp.minute, 15)
        self.assertEqual(value.from_timestamp.astimezone(timezone.utc).hour, 3)

    def test_rejects_protocol_and_uuid_errors(self):
        for changes in (
            {"protocol_version": True},
            {"protocol_version": 2},
            {"request_id": REQUEST_ID.upper()},
            {"request_id": str(uuid.uuid4()).upper()},
            {"request_id": "not-a-uuid"},
        ):
            with self.subTest(changes=changes), self.assertRaises(BrokerRequestValidationError):
                request(**changes)

    def test_rejects_bad_instrument_tokens(self):
        for value in ("0", "-1", "+1", " 1", "1 ", "1.0", "1a", "١"):
            with self.subTest(value=value), self.assertRaises(BrokerRequestValidationError):
                request(instrument_token=value)

    def test_rejects_unsupported_options(self):
        with self.assertRaises(BrokerRequestValidationError):
            request(interval="5minute")
        with self.assertRaises(BrokerRequestValidationError):
            request(continuous=True)
        self.assertTrue(request(oi=True).oi)
        self.assertFalse(request(oi=False).oi)

    def test_rejects_timestamp_errors(self):
        cases = (
            {"from_timestamp": datetime(2026, 7, 20, 9, 15)},
            {"from_timestamp": datetime(2026, 7, 20, 9, 15, 0, 1, tzinfo=IST)},
            {"to_timestamp": datetime(2026, 7, 20, 9, 15, tzinfo=IST)},
            {"from_timestamp": datetime(2026, 7, 20, 15, 30, tzinfo=IST)},
            {"to_timestamp": datetime(2026, 7, 20, 9, 14, tzinfo=IST)},
            {"to_timestamp": datetime(2026, 7, 21, 9, 15, tzinfo=IST)},
            {"to_timestamp": datetime(2026, 7, 21, 9, 16, tzinfo=IST)},
        )
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(BrokerRequestValidationError):
                request(**changes)

    def test_from_mapping_rejects_unknown_fields_and_wrong_timestamp_types(self):
        mapping = request().to_mapping()
        mapping["url"] = "https://example.invalid"
        with self.assertRaises(BrokerRequestValidationError):
            CandleRequest.from_mapping(mapping)
        mapping = request().to_mapping()
        mapping["from_timestamp"] = True
        with self.assertRaises(BrokerRequestValidationError):
            CandleRequest.from_mapping(mapping)


class TestBrokerResponse(unittest.TestCase):
    def test_body_hash_length_and_exact_bytes_round_trip(self):
        body = b"\x00\xffprovider\n"
        response = provider_response(body)
        self.assertEqual(response.body, body)
        self.assertEqual(response.body_length, len(body))
        self.assertEqual(response.body_sha256, hashlib.sha256(body).hexdigest())
        self.assertEqual(decode_response(encode_response(response)).body, body)

    def test_rejects_body_metadata_and_truncation_errors(self):
        body = b"body"
        for changes in (
            {"body_length": 999},
            {"body_sha256": "0" * 64},
            {"truncated": True},
            {"body": b"x" * (MAX_RESPONSE_BODY + 1)},
        ):
            values = provider_response(body)
            with self.subTest(changes=changes), self.assertRaises(BrokerResponseValidationError):
                BrokerResponse(**{**values.__dict__, **changes})

    def test_provider_status_and_session_consistency(self):
        with self.assertRaises(BrokerResponseValidationError):
            BrokerResponse.for_provider(request_id=REQUEST_ID, broker_request_id=BROKER_ID, captured_at=CAPTURED, status=600, body=b"")
        with self.assertRaises(BrokerResponseValidationError):
            BrokerResponse.for_provider(request_id=REQUEST_ID, broker_request_id=BROKER_ID, captured_at=CAPTURED, status=403, body=b"x", error_code=BrokerErrorCode.PROVIDER_403)
        with self.assertRaises(BrokerResponseValidationError):
            BrokerResponse.for_provider(request_id=REQUEST_ID, broker_request_id=BROKER_ID, captured_at=CAPTURED, status=429, body=b"x")
        with self.assertRaises(BrokerResponseValidationError):
            BrokerResponse.for_provider(request_id=REQUEST_ID, broker_request_id=BROKER_ID, captured_at=CAPTURED, status=200, body=b"x", error_code=BrokerErrorCode.PROVIDER_400)
        self.assertEqual(provider_response(b"x", status=500, error_code=BrokerErrorCode.PROVIDER_5XX).error_code, BrokerErrorCode.PROVIDER_5XX)

    def test_each_provider_error_requires_matching_provider_response(self):
        statuses = {
            BrokerErrorCode.PROVIDER_400: 400,
            BrokerErrorCode.PROVIDER_403: 403,
            BrokerErrorCode.PROVIDER_404: 404,
            BrokerErrorCode.PROVIDER_429: 429,
            BrokerErrorCode.PROVIDER_5XX: 500,
        }
        self.assertEqual(set(statuses), set(PROVIDER_ERROR_CODES))
        for code, status in statuses.items():
            kwargs = {"error_code": code}
            if code is BrokerErrorCode.PROVIDER_403:
                kwargs["session_state"] = SessionState.INVALIDATED
            with self.subTest(code=code):
                response = provider_response(b"error", status=status, **kwargs)
                self.assertEqual(response.transport_status, TransportStatus.PROVIDER_RESPONSE)
                for local_status in (TransportStatus.BROKER_REJECTED, TransportStatus.BROKER_FAILURE, TransportStatus.SESSION_EXPIRED):
                    with self.assertRaises(BrokerResponseValidationError):
                        BrokerResponse(1, REQUEST_ID, BROKER_ID, local_status, None, SessionState.EXPIRED, CAPTURED, error_code=code)

        with self.assertRaises(BrokerResponseValidationError):
            provider_response(b"error", status=200, error_code=BrokerErrorCode.BROKER_UNAVAILABLE)
        local = BrokerResponse(
            1, REQUEST_ID, BROKER_ID, TransportStatus.BROKER_FAILURE, None,
            SessionState.READY, CAPTURED, error_code=BrokerErrorCode.BROKER_UNAVAILABLE,
        )
        self.assertIsNone(local.provider_http_status)
        self.assertEqual(local.body, b"")

    def test_capture_must_be_aware_utc(self):
        with self.assertRaises(BrokerResponseValidationError):
            provider_response(captured_at=datetime(2026, 7, 20, 4, 0))
        with self.assertRaises(BrokerResponseValidationError):
            provider_response(captured_at=datetime(2026, 7, 20, 9, 30, tzinfo=IST))

    def test_rejects_arbitrary_metadata(self):
        with self.assertRaises(BrokerResponseValidationError):
            provider_response(audit_metadata={"headers": "Authorization: secret"})

    def test_provider_error_can_preserve_raw_bytes(self):
        response = provider_response(b'{"status":"error"}', status=429, error_code=BrokerErrorCode.PROVIDER_429)
        self.assertEqual(response.body, b'{"status":"error"}')
        self.assertIsNone(response.retry_after_seconds)
        self.assertEqual(provider_response(b"error", status=429, retry_after_seconds=3, error_code=BrokerErrorCode.PROVIDER_429).retry_after_seconds, 3)
        for value in (True, -1, 1.5, 3601):
            with self.subTest(value=value), self.assertRaises(BrokerResponseValidationError):
                provider_response(b"error", status=429, retry_after_seconds=value, error_code=BrokerErrorCode.PROVIDER_429)
        with self.assertRaises(BrokerResponseValidationError):
            BrokerResponse(1, REQUEST_ID, BROKER_ID, TransportStatus.BROKER_FAILURE, None, SessionState.READY, CAPTURED, retry_after_seconds=1, error_code=BrokerErrorCode.BROKER_UNAVAILABLE)


class TestFraming(unittest.TestCase):
    def test_request_round_trip(self):
        self.assertEqual(decode_request(encode_request(request())), request())

    def test_rejects_empty_truncated_and_oversized_frames(self):
        valid = encode_request(request())
        for frame in (b"", valid[:2], valid[:-1]):
            with self.subTest(frame=frame), self.assertRaises(FramingError):
                decode_request(frame)
        oversized = struct.pack(">I", 16 * 1024 + 1)
        with self.assertRaises(FramingError):
            decode_request(oversized)

    def test_rejects_encoding_json_and_duplicate_key_errors(self):
        for payload in (b"\xff", b"not-json", b'{"a":1,"a":2}', b"NaN"):
            frame = struct.pack(">I", len(payload)) + payload
            with self.subTest(payload=payload), self.assertRaises(FramingError):
                decode_request(frame)

    def test_nested_duplicate_keys_are_rejected(self):
        payload = b'{"outer":{"a":1,"a":2}}'
        frame = struct.pack(">I", len(payload)) + payload
        with self.assertRaises(FramingError):
            decode_json_frame(frame)

    def test_request_payload_exact_boundary_and_trailing_data(self):
        prefix = b'{"x":"'
        suffix = b'"}'
        payload = prefix + b"a" * (MAX_REQUEST_PAYLOAD - len(prefix) - len(suffix)) + suffix
        frame = struct.pack(">I", len(payload)) + payload
        self.assertEqual(decode_json_frame(frame)["x"], "a" * (MAX_REQUEST_PAYLOAD - len(prefix) - len(suffix)))
        too_large = prefix + b"a" * (MAX_REQUEST_PAYLOAD - len(prefix) - len(suffix) + 1) + suffix
        oversized = struct.pack(">I", len(too_large)) + too_large
        with self.assertRaises(FramingError):
            decode_json_frame(oversized)
        with self.assertRaises(FramingError):
            decode_request(encode_request(request()) + b"trailing")

    def test_response_trailing_data_is_rejected(self):
        with self.assertRaises(ZerodhaBrokerError):
            decode_response(encode_response(provider_response()) + b"trailing")

    def test_exact_provider_body_boundary(self):
        exact = provider_response(b"x" * MAX_RESPONSE_BODY)
        self.assertEqual(exact.body_length, MAX_RESPONSE_BODY)
        with self.assertRaises(BrokerResponseValidationError):
            provider_response(b"x" * (MAX_RESPONSE_BODY + 1))

    def test_non_string_captured_at_forms_are_typed_errors(self):
        frame = encode_response(provider_response())
        for value in (123, True, None, [], {}):
            with self.subTest(value=value):
                mapping = json.loads(frame[4:])
                mapping["captured_at"] = value
                payload = json.dumps(mapping, separators=(",", ":")).encode()
                with self.assertRaises(BrokerResponseValidationError) as context:
                    decode_response(struct.pack(">I", len(payload)) + payload)
                self.assertEqual(context.exception.code, BrokerErrorCode.MALFORMED_PROVIDER_RESPONSE)
                self.assertNotIn("captured_at", str(context.exception))

    def test_rejects_unknown_request_fields_and_credential_like_input(self):
        mapping = request().to_mapping()
        mapping["access_token"] = "secret-value"
        with self.assertRaises(BrokerRequestValidationError):
            CandleRequest.from_mapping(mapping)
        mapping = request().to_mapping()
        mapping["headers"] = {"Authorization": "secret-value"}
        with self.assertRaises(BrokerRequestValidationError):
            CandleRequest.from_mapping(mapping)

    def test_response_base64_and_body_consistency_are_strict(self):
        frame = encode_response(provider_response(b"raw\x00bytes"))
        self.assertEqual(decode_response(frame).body, b"raw\x00bytes")
        value = json.loads(frame[4:])
        value["body_base64"] = "%%%"
        payload = json.dumps(value, separators=(",", ":")).encode()
        with self.assertRaises(BrokerResponseValidationError):
            decode_response(struct.pack(">I", len(payload)) + payload)
        value = json.loads(frame[4:])
        value["body_length"] += 1
        payload = json.dumps(value, separators=(",", ":")).encode()
        with self.assertRaises(BrokerResponseValidationError):
            decode_response(struct.pack(">I", len(payload)) + payload)

    def test_response_frame_limit_is_bounded(self):
        self.assertGreater(MAX_RESPONSE_PAYLOAD, MAX_RESPONSE_BODY)
        self.assertLess(MAX_RESPONSE_PAYLOAD, 32 * 1024 * 1024)

    def test_hostile_json_parser_failures_are_typed(self):
        huge_integer = b"{" + b'"n":' + b"9" * 5000 + b"}"
        frame = struct.pack(">I", len(huge_integer)) + huge_integer
        with self.assertRaises(FramingError) as context:
            decode_json_frame(frame)
        self.assertEqual(context.exception.code, BrokerErrorCode.MALFORMED_CLIENT_REQUEST)

        nested = b"[" * 2000 + b"]" * 2000
        frame = struct.pack(">I", len(nested)) + nested
        with self.assertRaises(FramingError) as context:
            decode_json_frame(frame)
        self.assertEqual(context.exception.code, BrokerErrorCode.MALFORMED_CLIENT_REQUEST)


class TestErrorPolicy(unittest.TestCase):
    def test_all_required_codes_have_safe_policy(self):
        expected = {
            "PROTOCOL_VERSION_MISMATCH", "MALFORMED_CLIENT_REQUEST", "UNAUTHORIZED_CALLER", "UNSUPPORTED_INTERVAL", "INVALID_DATE_WINDOW",
            "SESSION_FILE_MISSING", "SESSION_FILE_UNREADABLE", "MALFORMED_SESSION_FILE", "SESSION_EXPIRED", "SESSION_INVALIDATED",
            "BROKER_UNAVAILABLE", "BROKER_TIMEOUT", "PROVIDER_400", "PROVIDER_403", "PROVIDER_404", "PROVIDER_429", "PROVIDER_5XX",
            "NETWORK_TIMEOUT", "DNS_TLS_CONNECTION_FAILURE", "OVERSIZED_PROVIDER_RESPONSE", "MALFORMED_PROVIDER_RESPONSE", "INTERNAL_BROKER_FAILURE",
        }
        self.assertEqual({code.value for code in BrokerErrorCode}, expected)
        for code in BrokerErrorCode:
            policy = error_policy(code)
            self.assertTrue(policy.safe_message)

    def test_retry_and_reauthentication_policy(self):
        self.assertTrue(error_policy(BrokerErrorCode.PROVIDER_429).retryable)
        self.assertTrue(error_policy(BrokerErrorCode.PROVIDER_5XX).retryable)
        self.assertFalse(error_policy(BrokerErrorCode.PROVIDER_400).retryable)
        self.assertTrue(error_policy(BrokerErrorCode.PROVIDER_403).reauthentication_required)
        self.assertFalse(error_policy(BrokerErrorCode.PROVIDER_403).retryable)

    def test_exception_text_and_repr_are_safe(self):
        error = ZerodhaBrokerError(BrokerErrorCode.PROVIDER_403)
        self.assertNotIn("access_token", str(error))
        self.assertNotIn("raw-provider-body", repr(error))
        self.assertNotIn("raw-provider-body", str(error))


class TestFakeBroker(unittest.TestCase):
    def test_scripted_success_capture_and_deterministic_identity(self):
        body = b"fixture-bytes"
        fake = DeterministicFakeBroker([provider_response(body)])
        result = fake.fetch_candles(request())
        self.assertEqual(result.body, body)
        self.assertEqual(result.request_id, REQUEST_ID)
        self.assertEqual(result.broker_request_id, "c1ed4c34-af1b-5bbb-8151-c5e8962ca3b5")
        self.assertEqual(fake.requests, [request()])

    def test_scripted_typed_failure_and_sequence_exhaustion(self):
        fake = DeterministicFakeBroker([ZerodhaBrokerError(BrokerErrorCode.BROKER_TIMEOUT)])
        with self.assertRaises(ZerodhaBrokerError):
            fake.fetch_candles(request())
        with self.assertRaises(FakeBrokerSequenceExhausted):
            fake.fetch_candles(request())

    def test_unexpected_request_is_rejected_without_credentials_or_io(self):
        fake = DeterministicFakeBroker([])
        with self.assertRaises(FakeBrokerUnexpectedRequest):
            fake.fetch_candles(request())
        self.assertEqual(fake.call_count, 1)

    def test_callable_script_is_deterministic(self):
        seen = []

        def step(value, index):
            seen.append((value.request_id, index))
            return provider_response(b"callable")

        fake = DeterministicFakeBroker([step])
        self.assertEqual(fake.fetch_candles(request()).body, b"callable")
        self.assertEqual(seen, [(REQUEST_ID, 0)])


if __name__ == "__main__":
    unittest.main()
