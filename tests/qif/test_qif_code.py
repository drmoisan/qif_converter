import pytest
from dataclasses import FrozenInstanceError

from qif_converter.qif.qif_code import QifCode


def test_qif_code_stores_fields_and_is_frozen():
    # Arrange
    c = QifCode(
        code="N",
        description="Name / Payee",
        used_in="Bank, Cash, CC",
        example="NStarbucks",
    )

    # Act
    # (No action; we’re just inspecting the created instance)

    # Assert
    assert c.code == "N"
    assert c.description == "Name / Payee"
    assert c.used_in == "Bank, Cash, CC"
    assert c.example == "NStarbucks"

    # Immutability / frozen dataclass behavior
    with pytest.raises(FrozenInstanceError):
        setattr(c, "code", "X")
    with pytest.raises(FrozenInstanceError):
        setattr(c, "description", "Changed")


def test_qif_code_equality_relies_on_code_only():
    # Arrange
    a = QifCode(code="D", description="Date", used_in="All", example="D01/02'25")
    b = QifCode(code="D", description="Different desc", used_in="Bank", example="D2025-01-02")
    c = QifCode(code="T", description="Amount", used_in="All", example="T-12.34")

    # Act
    # (No action; just comparisons)

    # Assert
    assert a == b, "Same code → equal, regardless of other fields."
    assert a != c, "Different code → not equal."


def test_qif_code_hash_uses_code_only_and_dedupes_in_sets_and_dicts():
    # Arrange
    a = QifCode(code="P", description="Payee", used_in="All", example="PCoffee Shop")
    b = QifCode(code="P", description="Different", used_in="Bank", example="PStore")
    c = QifCode(code="L", description="Category", used_in="All", example="LFood")

    # Act
    s = {a, b, c}  # should dedupe a & b by code
    d = {a: "first", c: "second", b: "overwrites_first"}

    # Assert
    assert a == b
    assert hash(a) == hash(b), "Equal objects must have equal hashes."
    assert len(s) == 2, "Set should dedupe by code (P, L)."
    assert d[a] == "overwrites_first"
    assert d[b] == "overwrites_first", "b should reference same dict key as a."


def test_qif_code_eq_with_non_qifcode_returns_false_not_error():
    # Arrange
    a = QifCode(code="M", description="Memo", used_in="All", example="MLatte")

    # Act / Assert
    assert not (a == "M"), "Comparing to non-QifCode should be False (NotImplemented path)."
    assert a != object(), "Different type → not equal."
