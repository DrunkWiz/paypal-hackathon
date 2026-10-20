"""Integer minor-unit conversion, and nothing else."""

from __future__ import annotations

import pytest

from backend.paypal.money import from_minor, parse_amount, to_minor


def test_to_minor_basic():
    assert to_minor("12.34") == 1234


def test_to_minor_whole_units():
    assert to_minor("12") == 1200


def test_to_minor_small_fraction():
    assert to_minor("0.05") == 5


def test_to_minor_one_decimal_place():
    assert to_minor("0.5") == 50


def test_to_minor_zero():
    assert to_minor("0.00") == 0


def test_to_minor_large():
    assert to_minor("1000.00") == 100000


def test_to_minor_none_is_zero():
    assert to_minor(None) == 0


def test_to_minor_returns_int_never_float():
    value = to_minor("19.99")
    assert isinstance(value, int)
    assert not isinstance(value, bool)


def test_to_minor_rejects_bool():
    with pytest.raises(ValueError):
        to_minor(True)


def test_from_minor_basic():
    assert from_minor(1234) == "12.34"


def test_from_minor_small():
    assert from_minor(5) == "0.05"


def test_from_minor_zero():
    assert from_minor(0) == "0.00"


def test_from_minor_large():
    assert from_minor(100000) == "1000.00"


def test_from_minor_rejects_float():
    with pytest.raises(TypeError):
        from_minor(12.34)


def test_round_trip_is_exact():
    for text in ("0.00", "0.05", "1.00", "12.34", "999.99", "100000.01"):
        assert from_minor(to_minor(text)) == text


def test_parse_amount_tuple():
    assert parse_amount({"currency_code": "USD", "value": "12.34"}) == (1234, "USD")


def test_parse_amount_empty():
    assert parse_amount({}) == (0, "")
