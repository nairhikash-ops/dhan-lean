# LEAN Minute Data Converter

`convert_minute_bars_to_lean` accepts an ordered sequence of provider-neutral `NormalizedBar` values and writes LEAN India-equity minute CSV-in-ZIP data.

Adapters are responsible for parsing provider payloads, choosing a timezone-aware timestamp convention, and constructing `Decimal` OHLC prices. The converter validates OHLCV invariants, normalizes timestamps to `Asia/Kolkata`, scales prices by 10,000, and publishes a deterministic ZIP member through exclusive filesystem linking. Existing output paths fail closed.

The converter is offline only; it performs no network requests and has no provider credential dependency.
