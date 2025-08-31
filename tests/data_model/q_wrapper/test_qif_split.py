# tests/test_qif_split.py
from decimal import Decimal

from quicken_helper.data_model.q_wrapper.q_split import QSplit


def test_equality_and_hash_are_consistent():
    # Arrange
    a1 = QSplit(category="Food:Coffee", amount=Decimal("-10.00"), memo="Latte", tag="")
    a2 = QSplit(
        category="Food:Coffee", amount=Decimal("-10.00"), memo="Latte", tag=""
    )  # identical
    b = QSplit(
        category="Food:Coffee", amount=Decimal("-10.00"), memo="Latte!", tag=""
    )  # memo differs

    # Act
    eq_same = a1 == a2
    eq_diff = a1 == b
    hash_same = hash(a1) == hash(a2)

    # Assert
    assert eq_same is True, "Identical field values must be equal."
    assert eq_diff is False, "A differing field should make instances not equal."
    assert (
        hash_same is True
    ), "Equal objects must have identical hashes for set/dict correctness."


def test_can_be_used_in_set_and_deduplicates_equal_items():
    # Arrange
    s1 = QSplit("Cat:A", Decimal("1.00"), "m", tag="")
    s2 = QSplit("Cat:A", Decimal("1.00"), "m", tag="")  # equal to s1
    s3 = QSplit("Cat:A", Decimal("1.00"), "m2", tag="")  # different memo

    # Act
    unique = {s1, s2, s3}

    # Assert
    assert len(unique) == 2, "Equal splits should deduplicate in a set."
    assert s1 in unique and s3 in unique


def test_can_be_used_as_dict_key():
    # Arrange
    k1 = QSplit("Cat:B", Decimal("-2.50"), "x", tag="T")
    k2 = QSplit("Cat:B", Decimal("-2.50"), "x", tag="T")  # equal key
    k3 = QSplit("Cat:B", Decimal("-2.50"), "y", tag="T")  # different memo

    d = {k1: "value1"}

    # Act
    v_same = d.get(k2)  # should find existing key
    v_miss = d.get(k3)  # different key

    # Assert
    assert v_same == "value1", "Equal key must retrieve the same dict entry."
    assert v_miss is None, "Different key must not collide."


def test_ordering_primary_category_then_tag_then_amount_then_memo():
    """
    Arrange different splits so that sorting must respect the strict precedence:
      1) category  2) tag  3) amount  4) memo
    """
    # Arrange
    s_catA_tagA_amt1_memoA = QSplit("A", Decimal("1.00"), "a", tag="A")
    s_catA_tagA_amt1_memoB = QSplit("A", Decimal("1.00"), "b", tag="A")
    s_catA_tagA_amt2_memoA = QSplit("A", Decimal("2.00"), "a", tag="A")
    s_catA_tagB_amt1_memoA = QSplit("A", Decimal("1.00"), "a", tag="B")
    s_catB_tagA_amt1_memoA = QSplit("B", Decimal("1.00"), "a", tag="A")

    scrambled = [
        s_catA_tagB_amt1_memoA,  # tag B should come after tag A (with same category)
        s_catB_tagA_amt1_memoA,  # category B should come after category A
        s_catA_tagA_amt2_memoA,  # higher amount should come after lower amount (same cat/tag)
        s_catA_tagA_amt1_memoB,  # memo 'b' should come after 'a' (same cat/tag/amount)
        s_catA_tagA_amt1_memoA,  # expected first
    ]

    # Act
    result = sorted(scrambled)

    # Assert (expected strict order by: category → tag → amount → memo)
    expected = [
        s_catA_tagA_amt1_memoA,
        s_catA_tagA_amt1_memoB,
        s_catA_tagA_amt2_memoA,
        s_catA_tagB_amt1_memoA,
        s_catB_tagA_amt1_memoA,
    ]
    assert (
        result == expected
    ), "Sorting must honor category → tag → amount → memo precedence."


def test_ordering_with_negative_and_positive_amounts():
    # Arrange: identical category/tag, amounts differ
    p = QSplit("Food", Decimal("5.00"), "m", tag="")
    n = QSplit("Food", Decimal("-5.00"), "m", tag="")

    # Act
    sorted_pair = sorted([p, n])

    # Assert: -5.00 should appear before +5.00 under same category/tag/memo
    assert sorted_pair == [n, p]


def test_ordering_uses_memo_as_tiebreaker_only():
    # Arrange: same category/tag/amount; memo decides order
    m1 = QSplit("X", Decimal("1.00"), "aaa", tag="T")
    m2 = QSplit("X", Decimal("1.00"), "bbb", tag="T")
    m3 = QSplit("X", Decimal("1.00"), "ccc", tag="T")

    # Act
    result = sorted([m3, m1, m2])

    # Assert
    assert result == [
        m1,
        m2,
        m3,
    ], "When category/tag/amount tie, memo lexicographic order should apply."
