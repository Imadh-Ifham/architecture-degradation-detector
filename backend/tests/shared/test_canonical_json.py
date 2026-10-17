"""Canonical JSON: one byte sequence per value, so equal content always has an equal hash."""

import re
from enum import StrEnum

import pytest

from app.shared.canonical_json import canonical_json, content_hash


class Colour(StrEnum):
    RED = "red"


def test_keys_are_sorted_and_whitespace_is_removed() -> None:
    assert (
        canonical_json({"b": 1, "a": {"d": None, "c": True}}) == '{"a":{"c":true,"d":null},"b":1}'
    )


def test_key_order_does_not_change_the_hash() -> None:
    assert content_hash({"a": 1, "b": [1, 2]}) == content_hash({"b": [1, 2], "a": 1})


def test_list_order_does_change_the_hash() -> None:
    assert content_hash([1, 2]) != content_hash([2, 1])


def test_tuples_and_lists_are_the_same_array() -> None:
    assert canonical_json((1, 2)) == canonical_json([1, 2]) == "[1,2]"


def test_float_noise_below_the_fixed_digits_is_removed() -> None:
    assert canonical_json(0.1 + 0.2) == canonical_json(0.3) == "0.3"


def test_small_floats_keep_their_significant_digits() -> None:
    assert canonical_json(1.5e-15) != canonical_json(2.5e-15)


def test_negative_zero_is_zero() -> None:
    assert canonical_json(-0.0) == canonical_json(0.0) == "0.0"


def test_non_ascii_text_is_kept_as_is() -> None:
    assert canonical_json({"name": "café"}) == '{"name":"café"}'


def test_str_enum_is_written_as_its_value() -> None:
    assert canonical_json({"colour": Colour.RED}) == '{"colour":"red"}'


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_are_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="canonical"):
        canonical_json({"x": value})


def test_unsupported_types_are_rejected() -> None:
    with pytest.raises(TypeError, match="set"):
        canonical_json({"x": {1, 2}})


def test_non_string_keys_are_rejected() -> None:
    with pytest.raises(TypeError, match="key"):
        canonical_json({1: "a"})


def test_hash_has_the_contract_format() -> None:
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", content_hash({"a": 1}))


def test_hash_of_a_known_value() -> None:
    # sha256 of the two bytes "{}"
    expected = "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"

    assert content_hash({}) == expected
