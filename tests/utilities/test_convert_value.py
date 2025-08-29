# tests/utilities/test_convert_value.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Optional, Union

import pytest

# Unit under test
from quicken_helper.utilities.core_util import _convert_value


# -------------------------
# Scalar & simple conversions
# -------------------------

def test_convert_decimal_from_string():
    """Positive: Convert a numeric string to Decimal."""
    # Arrange
    target_type = Decimal
    value = "5.4567"
    # Act
    out = _convert_value(target_type, value)
    # Assert
    assert isinstance(out, Decimal)
    assert out == Decimal("5.4567")


@pytest.mark.parametrize(
    "target_type,value,expected",
    [
        (int, "42", 42),
        (float, "3.14", 3.14),
        (str, 123, "123"),
    ],
)
def test_convert_basic_scalars_from_strings(target_type, value, expected):
    """Positive: Convert strings to int/float and arbitrary to str."""
    # Act
    out = _convert_value(target_type, value)
    # Assert
    assert out == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("yes", True),
        ("Y", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("N", False),
    ],
)
def test_convert_bool_from_various_strings(value, expected):
    """Positive: Convert common boolean string forms to bool."""
    # Act
    out = _convert_value(bool, value)
    # Assert
    assert out is expected


def test_convert_path_from_string():
    """Positive: Convert a string path into a pathlib.Path."""
    # Arrange
    p = "some/where/file.txt"
    # Act
    out = _convert_value(Path, p)
    # Assert
    assert isinstance(out, Path)
    assert str(out).replace("\\", "/") == p


# -------------------------
# Enums
# -------------------------

class Color(Enum):
    RED = "red"
    BLUE = "blue"


def test_convert_enum_by_name():
    """Positive: Convert enum by name (e.g., 'RED')."""
    # Act
    out = _convert_value(Color, "RED")
    # Assert
    assert out is Color.RED


def test_convert_enum_by_value():
    """Positive: Convert enum by value (e.g., 'red')."""
    # Act
    out = _convert_value(Color, "red")
    # Assert
    assert out is Color.RED


# -------------------------
# Dates & datetimes
# -------------------------

def test_convert_date_from_iso_string():
    """Positive: Convert ISO date string to datetime.date."""
    # Act
    out = _convert_value(date, "2025-02-01")
    # Assert
    assert isinstance(out, date)
    assert out == date(2025, 2, 1)


def test_convert_date_from_datetime():
    """Positive: datetime -> date via .date()."""
    # Arrange
    dt = datetime(2025, 2, 1, 12, 30, 0)
    # Act
    out = _convert_value(date, dt)
    # Assert
    assert out == date(2025, 2, 1)


def test_convert_datetime_from_iso_string():
    """Positive: Convert ISO datetime string to datetime."""
    # Act
    out = _convert_value(datetime, "2025-02-01T12:00:00")
    # Assert
    assert isinstance(out, datetime)
    assert out == datetime(2025, 2, 1, 12, 0, 0)


def test_convert_date_invalid_input_raises():
    """Negative: Invalid date string raises ValueError."""
    # Assert
    with pytest.raises(ValueError):
        _convert_value(date, "not-a-date")


# -------------------------
# Optional/Union
# -------------------------

def test_convert_optional_accepts_none():
    """Edge: Optional[T] preserves None."""
    # Act
    out = _convert_value(Optional[int], None)
    # Assert
    assert out is None


def test_convert_union_picks_first_matching_type():
    """Positive: Union[int, str] with '10' should yield int 10 (first matching)."""
    # Act
    out = _convert_value(Union[int, str], "10")
    # Assert
    assert out == 10
    assert isinstance(out, int)


def test_convert_union_falls_back_to_second_type():
    """Positive: Union[int, str] with 'abc' should yield 'abc' (int fails, str works)."""
    # Act
    out = _convert_value(Union[int, str], "abc")
    # Assert
    assert out == "abc"
    assert isinstance(out, str)


# -------------------------
# Collections
# -------------------------

def test_convert_list_of_ints_from_strings():
    """Positive: list[int] converts each item."""
    # Act
    out = _convert_value(list[int], ["1", "2", "3"])
    # Assert
    assert out == [1, 2, 3]
    assert all(isinstance(x, int) for x in out)


def test_convert_set_of_decimals_from_strings():
    """Positive: set[Decimal] converts members."""
    # Act
    out = _convert_value(set[Decimal], ["1.0", "2.5"])
    # Assert
    assert out == {Decimal("1.0"), Decimal("2.5")}
    assert all(isinstance(x, Decimal) for x in out)


def test_convert_tuple_fixed_length_heterogeneous():
    """Positive: tuple[int, str] converts positionally."""
    # Act
    out = _convert_value(tuple[int, str], ["7", 8])
    # Assert
    assert out == (7, "8")
    assert isinstance(out[0], int) and isinstance(out[1], str)


def test_convert_tuple_variadic_single_type():
    """Positive: tuple[int, ...] converts all items to int."""
    # Act
    out = _convert_value(tuple[int, ...], ["1", "2", "3"])
    # Assert
    assert out == (1, 2, 3)
    assert all(isinstance(x, int) for x in out)


def test_convert_typed_dict_str_int():
    """Positive: dict[str, int] converts keys and values."""
    # Arrange
    src = {"a": "1", "b": "2"}
    # Act
    out = _convert_value(dict[str, int], src)
    # Assert
    assert out == {"a": 1, "b": 2}
    assert all(isinstance(k, str) for k in out.keys())
    assert all(isinstance(v, int) for v in out.values())


# -------------------------
# Dataclass delegation
# -------------------------

@dataclass
class Child:
    x: int
    y: Decimal = Decimal("0")


def test_convert_nested_dataclass_from_dict():
    """Positive: Converting dict -> dataclass (uses from_dict under the hood)."""
    # Arrange
    payload = {"x": "3", "y": "4.5"}
    # Act
    out = _convert_value(Child, payload)
    # Assert
    assert isinstance(out, Child)
    assert out.x == 3
    assert out.y == Decimal("4.5")


def test_convert_nested_dataclass_respects_defaults():
    """Edge: Missing optional field uses dataclass default (no override)."""
    # Arrange
    payload = {"x": "7"}  # omit 'y' -> default remains
    # Act
    out = _convert_value(Child, payload)
    # Assert
    assert isinstance(out, Child)
    assert out.x == 7
    assert out.y == Decimal("0")  # default preserved
