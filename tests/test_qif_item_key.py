# tests/test_qif_item_key.py
import pytest
from dataclasses import FrozenInstanceError

from qif_converter.qif_item_key import QIFItemKey


def test_is_split_false_for_whole_transaction():
    # Arrange
    key = QIFItemKey(txn_index=3, split_index=None)

    # Act
    result = key.is_split()

    # Assert
    assert result is False, "Whole-transaction key should report is_split() == False"


def test_is_split_true_for_split_transaction():
    # Arrange
    key = QIFItemKey(txn_index=3, split_index=0)

    # Act
    result = key.is_split()

    # Assert
    assert result is True, "Split key should report is_split() == True when split_index is not None"


def test_equality_and_hash_same_fields_are_equal():
    # Arrange
    a = QIFItemKey(5, None)
    b = QIFItemKey(5, None)
    c = QIFItemKey(5, 0)
    d = QIFItemKey(6, None)

    # Act / Assert
    assert a == b, "Keys with identical txn_index & split_index must be equal"
    assert hash(a) == hash(b), "Equal keys must have identical hashes"
    assert a != c, "Different split_index should make keys unequal"
    assert a != d, "Different txn_index should make keys unequal"


def test_hashable_and_usable_as_dict_key_and_set_member():
    # Arrange
    k1 = QIFItemKey(1, None)
    k2 = QIFItemKey(1, 0)
    k3 = QIFItemKey(2, 0)

    # Act
    d = {k1: "whole", k2: "split0"}
    s = {k1, k2, k3}

    # Assert
    assert d[k1] == "whole"
    assert d[k2] == "split0"
    assert k1 in s and k2 in s and k3 in s, "Keys should be usable in sets without collision"


def test_frozen_immutability():
    # Arrange
    key = QIFItemKey(10, None)

    # Act / Assert
    import pytest
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        setattr(key, "txn_index", 11)

    with pytest.raises(FrozenInstanceError):
        setattr(key, "split_index", 0)
