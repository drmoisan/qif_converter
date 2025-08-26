# tests/test_qif_enums.py
import pytest

from qif_converter.qif import EnumQifSections, EnumClearedStatus


# ---------- QifSections (IntFlag) ----------

def test_qifsections_bitwise_membership_and_combination():
    # Arrange
    flags = EnumQifSections.TAGS | EnumQifSections.CATEGORIES  # combine two flags

    # Act
    has_tags = (flags & EnumQifSections.TAGS) == EnumQifSections.TAGS
    has_categories = (flags & EnumQifSections.CATEGORIES) == EnumQifSections.CATEGORIES
    has_accounts = (flags & EnumQifSections.ACCOUNTS) == EnumQifSections.ACCOUNTS
    has_transactions = (flags & EnumQifSections.TRANSACTIONS) == EnumQifSections.TRANSACTIONS

    # Assert
    assert has_tags
    assert has_categories
    assert not has_accounts
    assert not has_transactions


def test_qifsections_add_and_remove_using_bit_ops_from_none():
    # Arrange
    flags = EnumQifSections.NONE

    # Act
    flags = flags | EnumQifSections.ACCOUNTS
    after_add_accounts = (flags & EnumQifSections.ACCOUNTS) == EnumQifSections.ACCOUNTS

    flags = flags | EnumQifSections.TRANSACTIONS
    after_add_txns = (flags & EnumQifSections.TRANSACTIONS) == EnumQifSections.TRANSACTIONS

    # remove ACCOUNTS
    flags = flags & ~EnumQifSections.ACCOUNTS
    after_remove_accounts = (flags & EnumQifSections.ACCOUNTS) == EnumQifSections.ACCOUNTS

    # Assert
    assert after_add_accounts
    assert after_add_txns
    assert not after_remove_accounts


def test_qifsections_unique_values_and_none_zero():
    # Arrange
    members = [EnumQifSections.NONE, EnumQifSections.TAGS, EnumQifSections.CATEGORIES,
               EnumQifSections.ACCOUNTS, EnumQifSections.TRANSACTIONS]

    # Act
    values = [m.value for m in members]

    # Assert
    assert EnumQifSections.NONE.value == 0
    assert len(set(values)) == len(values), "Each section flag should have a unique underlying value."


# ---------- ClearedStatus ----------

def test_clearedstatus_from_char_valid_and_invalid():
    # Arrange / Act
    cleared = EnumClearedStatus.from_char('*')
    not_cleared1 = EnumClearedStatus.from_char('N')
    not_cleared2 = EnumClearedStatus.from_char('  ')
    reconciled1 = EnumClearedStatus.from_char('R')
    reconciled2 = EnumClearedStatus.from_char('X')
    unknown = EnumClearedStatus.from_char('?')

    # Assert
    assert cleared is EnumClearedStatus.CLEARED
    assert not_cleared1 is EnumClearedStatus.NOT_CLEARED
    assert not_cleared2 is EnumClearedStatus.NOT_CLEARED
    assert reconciled1 is EnumClearedStatus.RECONCILED
    assert reconciled2 is EnumClearedStatus.RECONCILED
    assert unknown is EnumClearedStatus.UNKNOWN

    # Arrange / Act / Assert (invalid)
    with pytest.raises(ValueError):
        EnumClearedStatus.from_char('A')


# def test_clearedstatus_emit_qif_codes():
#     # Arrange / Act
#     s_cleared = ClearedStatus.CLEARED.emit_qif()
#     s_reconciled = ClearedStatus.RECONCILED.emit_qif()
#     s_not_cleared = ClearedStatus.NOT_CLEARED.emit_qif()
#     s_unknown = ClearedStatus.UNKNOWN.emit_qif()
#
#     # Assert
#     # For cleared/reconciled, emitter should prefix with the QIF "C" code.
#     assert s_cleared == "C*"
#     assert s_reconciled == "CR"
#
#     # For not cleared/unknown, emitter should be empty.
#     assert s_not_cleared == ""
#     assert s_unknown == ""


def test_clearedstatus_ordering_and_equality():
    # Arrange
    r = EnumClearedStatus.RECONCILED
    c = EnumClearedStatus.CLEARED
    n = EnumClearedStatus.NOT_CLEARED
    u = EnumClearedStatus.UNKNOWN

    # Act / Assert — ordering contract defined in __lt__:
    # RECONCILED < CLEARED < (NOT_CLEARED and UNKNOWN)
    assert r < c
    assert r < n
    assert r < u
    assert c < n
    assert c < u

    # Equality is by value
    assert EnumClearedStatus.CLEARED == c
    assert EnumClearedStatus.CLEARED is c
    assert EnumClearedStatus.RECONCILED != EnumClearedStatus.CLEARED

    # We intentionally do not assert a relative order between NOT_CLEARED and UNKNOWN,
    # because __lt__ returns NotImplemented/False for that comparison in both directions.
