import unittest
from dhan_lean.data.validator import validate_dhan_response


class TestValidator(unittest.TestCase):

    def _create_synthetic_response(self, count=5, base_ts=1784691900):
        """Creates a valid synthetic 1-minute response."""
        return {
            "open": [100.0 + i for i in range(count)],
            "high": [105.0 + i for i in range(count)],
            "low": [95.0 + i for i in range(count)],
            "close": [102.0 + i for i in range(count)],
            "volume": [1000 + i * 10 for i in range(count)],
            "timestamp": [base_ts + i * 60 for i in range(count)],
        }

    def test_valid_synthetic_response(self):
        """Test a clean 5-bar synthetic response passes validation."""
        data = self._create_synthetic_response(count=5)
        res = validate_dhan_response(data)

        self.assertTrue(res.is_valid)
        self.assertEqual(res.candle_count, 5)
        self.assertTrue(res.arrays_equal_length)
        self.assertTrue(res.timestamps_strictly_increasing)
        self.assertEqual(res.duplicate_timestamp_count, 0)
        self.assertEqual(res.invalid_ohlc_count, 0)
        self.assertEqual(res.negative_volume_count, 0)
        self.assertEqual(res.missing_gap_count, 0)

    def test_start_time_key_alias(self):
        """Test start_Time key alias is recognized."""
        data = self._create_synthetic_response(count=3)
        data["start_Time"] = data.pop("timestamp")
        res = validate_dhan_response(data)

        self.assertTrue(res.is_valid)
        self.assertEqual(res.candle_count, 3)

    def test_missing_required_arrays(self):
        """Test missing required array returns is_valid=False."""
        data = self._create_synthetic_response()
        del data["volume"]
        res = validate_dhan_response(data)

        self.assertFalse(res.is_valid)
        self.assertIn("Missing required array keys", res.errors[0])

    def test_unequal_array_lengths(self):
        """Test unequal array lengths return is_valid=False."""
        data = self._create_synthetic_response()
        data["close"].pop()  # length 4 vs 5
        res = validate_dhan_response(data)

        self.assertFalse(res.is_valid)
        self.assertFalse(res.arrays_equal_length)

    def test_duplicate_timestamps(self):
        """Test duplicate timestamps are detected."""
        data = self._create_synthetic_response(count=4)
        data["timestamp"][2] = data["timestamp"][1]  # duplicate ts
        res = validate_dhan_response(data)

        self.assertFalse(res.is_valid)
        self.assertFalse(res.timestamps_strictly_increasing)
        self.assertEqual(res.duplicate_timestamp_count, 1)

    def test_descending_timestamps(self):
        """Test non-monotonic descending timestamps are detected."""
        data = self._create_synthetic_response(count=4)
        data["timestamp"] = [1000, 1060, 1030, 1120]  # 1030 < 1060
        res = validate_dhan_response(data)

        self.assertFalse(res.is_valid)
        self.assertFalse(res.timestamps_strictly_increasing)
        self.assertGreater(res.non_increasing_timestamp_count, 0)

    def test_invalid_ohlc(self):
        """Test low > open or high < close breaks OHLC relationship."""
        data = self._create_synthetic_response(count=3)
        data["high"][1] = 90.0  # high < low (95.0)
        res = validate_dhan_response(data)

        self.assertFalse(res.is_valid)
        self.assertEqual(res.invalid_ohlc_count, 1)

    def test_non_positive_prices(self):
        """Test zero or negative prices are flagged."""
        data = self._create_synthetic_response(count=3)
        data["low"][0] = 0.0
        res = validate_dhan_response(data)

        self.assertFalse(res.is_valid)
        self.assertEqual(res.non_positive_price_count, 1)

    def test_negative_and_zero_volumes(self):
        """Test negative volume flags error, zero volume is tracked."""
        data = self._create_synthetic_response(count=3)
        data["volume"][0] = -50
        data["volume"][1] = 0
        res = validate_dhan_response(data)

        self.assertFalse(res.is_valid)
        self.assertEqual(res.negative_volume_count, 1)
        self.assertEqual(res.zero_volume_count, 1)

    def test_missing_gaps(self):
        """Test gaps > expected interval are tracked."""
        data = self._create_synthetic_response(count=3, base_ts=1000)
        data["timestamp"] = [1000, 1060, 1200]  # 1200 - 1060 = 140s (80s excess gap)
        res = validate_dhan_response(data)

        self.assertEqual(res.missing_gap_count, 1)
        self.assertEqual(res.largest_actual_interval_seconds, 140)
        self.assertEqual(res.largest_excess_gap_seconds, 80)

    def test_boolean_and_non_numeric_rejection(self):
        """Test booleans and non-numeric values in arrays fail validation."""
        data = self._create_synthetic_response(count=3)
        data["close"][0] = True  # bool rejected
        res = validate_dhan_response(data)

        self.assertFalse(res.is_valid)
        self.assertGreater(res.non_positive_price_count, 0)

    def test_validation_result_immutability(self):
        """Test ValidationResult tuple and MappingProxyType attributes cannot be mutated."""
        data = self._create_synthetic_response(count=3)
        res = validate_dhan_response(data)

        # errors tuple cannot be appended to
        with self.assertRaises((TypeError, AttributeError)):
            res.errors.append("new_error")

        # array_lengths MappingProxyType cannot be assigned/modified
        with self.assertRaises(TypeError):
            res.array_lengths["open"] = 99

        # timestamp_delta_distribution MappingProxyType cannot be assigned/modified
        with self.assertRaises(TypeError):
            res.timestamp_delta_distribution[60] = 99

    def test_validation_result_defensive_copies(self):
        """Test mutating original source dictionary after construction does not mutate ValidationResult."""
        source_dict = {"open": [100.0], "high": [105.0], "low": [95.0], "close": [102.0], "volume": [1000], "timestamp": [1784691900]}
        res = validate_dhan_response(source_dict)

        original_open_length = res.array_lengths["open"]
        source_dict["open"].append(200.0)

        # Result's array_lengths snapshot remains unchanged
        self.assertEqual(res.array_lengths["open"], original_open_length)


if __name__ == "__main__":
    unittest.main()
