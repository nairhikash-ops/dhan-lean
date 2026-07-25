"""Deterministic offline broker fake for Zerodha protocol tests."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Sequence

from dhan_lean.providers.zerodha.broker_protocol import (
    BrokerResponse,
    CandleRequest,
    HistoricalBroker,
    ZerodhaBrokerError,
)


FakeStep = BrokerResponse | ZerodhaBrokerError | Callable[[CandleRequest, int], BrokerResponse | ZerodhaBrokerError]


class FakeBrokerSequenceExhausted(ZerodhaBrokerError):
    """Raised when a scripted fake has no response for a call."""

    def __init__(self) -> None:
        from dhan_lean.providers.zerodha.broker_protocol import BrokerErrorCode
        super().__init__(BrokerErrorCode.INTERNAL_BROKER_FAILURE)


class FakeBrokerUnexpectedRequest(ZerodhaBrokerError):
    """Raised when an unexpected call is made to a strict fake."""

    def __init__(self) -> None:
        from dhan_lean.providers.zerodha.broker_protocol import BrokerErrorCode
        super().__init__(BrokerErrorCode.INTERNAL_BROKER_FAILURE)


class DeterministicFakeBroker(HistoricalBroker):
    def __init__(self, steps: Sequence[FakeStep], *, clock: Callable[[], datetime] | None = None, allow_unexpected: bool = False) -> None:
        self._steps = tuple(steps)
        self._clock = clock or (lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
        self._allow_unexpected = allow_unexpected
        self._index = 0
        self.requests: list[CandleRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    def fetch_candles(self, request: CandleRequest) -> BrokerResponse:
        if not isinstance(request, CandleRequest):
            raise FakeBrokerUnexpectedRequest()
        self.requests.append(request)
        if self._index >= len(self._steps):
            if not self._allow_unexpected:
                raise FakeBrokerUnexpectedRequest() if not self._steps else FakeBrokerSequenceExhausted()
            step: FakeStep = BrokerResponse.for_provider(
                request_id=request.request_id,
                broker_request_id=self._broker_id(self._index),
                captured_at=self._clock(),
                status=200,
                body=b'{"status":"success","data":{"candles":[]}}',
            )
        else:
            step = self._steps[self._index]
        index = self._index
        self._index += 1
        if callable(step):
            step = step(request, index)
        if isinstance(step, ZerodhaBrokerError):
            raise step
        if not isinstance(step, BrokerResponse):
            raise FakeBrokerUnexpectedRequest()
        return replace(step, request_id=request.request_id, broker_request_id=self._broker_id(index))

    @staticmethod
    def _broker_id(index: int) -> str:
        return str(uuid.uuid5(uuid.UUID("3f1b4c32-2e24-4f94-8fd5-43e1d6f76c0c"), f"fake-broker:{index}"))
