import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from common import csv_row_to_power, safe_float


class TestCsvRowToPower:
    def test_power_1w_returns_high(self):
        result = csv_row_to_power("1")
        assert result is not None

    def test_power_5w_returns_high(self):
        result = csv_row_to_power("5")
        assert float(result) > 0

    def test_power_zero_uses_default(self):
        result = csv_row_to_power("0")
        assert float(result) > 0

    def test_power_negative_uses_default(self):
        result = csv_row_to_power("-1")
        assert float(result) > 0

    def test_power_empty_string_uses_default(self):
        result = csv_row_to_power("")
        assert float(result) > 0

    def test_power_none_uses_default(self):
        result = csv_row_to_power(None)
        assert float(result) > 0

    def test_power_invalid_uses_default(self):
        result = csv_row_to_power("abc")
        assert float(result) > 0

    def test_power_float_values(self):
        for val in ("0.5", "2.0", "3.5", "5.0"):
            result = csv_row_to_power(val)
            assert float(result) > 0, f"Failed for {val}"


class TestSafeFloat:
    def test_valid_float(self):
        assert safe_float("1.5") == 1.5

    def test_invalid_returns_default(self):
        assert safe_float("abc", 42.0) == 42.0

    def test_none_returns_default(self):
        assert safe_float(None, 0.0) == 0.0

    def test_integer(self):
        assert safe_float("42") == 42.0
