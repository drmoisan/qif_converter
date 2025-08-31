# tests/test_qif_writer_filters.py
from __future__ import annotations

import pytest

import quicken_helper.legacy.qif_writer as qw

# ------------------------------ _match_one ------------------------------------


def test__match_one_basic_modes_and_case():
    """_match_one: supports contains/exact/startswith/endswith with case handling.

    Verifies:
      • contains is case-insensitive by default
      • exact requires full equality
      • startswith/endswith work as expected
      • case_sensitive=True changes the behavior
    """
    payee = "Acme Market Inc"

    # contains (default: case-insensitive)
    assert qw._match_one(payee, "market", mode="contains", case_sensitive=False)
    assert not qw._match_one(payee, "xmarketx", mode="contains", case_sensitive=False)

    # exact
    assert qw._match_one(payee, "Acme Market Inc", mode="exact", case_sensitive=True)
    assert not qw._match_one(
        payee, "acme market inc", mode="exact", case_sensitive=True
    )

    # startswith / endswith
    assert qw._match_one(payee, "Acme", mode="startswith", case_sensitive=True)
    assert qw._match_one(payee, "inc", mode="endswith", case_sensitive=False)
    assert not qw._match_one(payee, "INC", mode="endswith", case_sensitive=True)


def test__match_one_regex_and_glob_modes():
    """_match_one: supports regex and glob, honoring case sensitivity.

    Verifies:
      • regex uses IGNORECASE when case_sensitive=False
      • glob uses fnmatchcase when case_sensitive=True
    """
    payee = "Acme Market Inc"

    # regex (case-insensitive)
    assert qw._match_one(payee, r"acme\s+market", mode="regex", case_sensitive=False)
    # regex (case-sensitive)
    assert not qw._match_one(payee, r"acme\s+market", mode="regex", case_sensitive=True)
    assert qw._match_one(payee, r"Acme\s+Market", mode="regex", case_sensitive=True)

    # glob (case-insensitive path: pattern is compared lower-cased)
    assert qw._match_one(payee, "acme*inc", mode="glob", case_sensitive=False)
    # glob (case-sensitive path)
    assert qw._match_one(payee, "Acme*Inc", mode="glob", case_sensitive=True)
    assert not qw._match_one(payee, "ACME*INC", mode="glob", case_sensitive=True)


def test__match_one_raises_on_unknown_mode():
    """_match_one: raises ValueError for unsupported match mode."""
    with pytest.raises(ValueError):
        qw._match_one("Payee", "x", mode="nope", case_sensitive=False)


# ---------------------------- filter_by_payee ---------------------------------


def test_filter_by_payee_single_query_all_modes_basic():
    """filter_by_payee: filters transactions by a single query using the specified mode.

    We verify:
      • contains returns all partial matches
      • exact returns only full matches
      • startswith/endswith select the proper subset
    """
    txns = [
        {"payee": "Acme Market Inc"},
        {"payee": "Acme Bistro"},
        {"payee": "Other"},
    ]

    out = qw.filter_by_payee(txns, "Acme", mode="contains")
    assert [t["payee"] for t in out] == ["Acme Market Inc", "Acme Bistro"]

    out = qw.filter_by_payee(txns, "Acme Bistro", mode="exact")
    assert [t["payee"] for t in out] == ["Acme Bistro"]

    out = qw.filter_by_payee(txns, "Acme", mode="startswith")
    assert [t["payee"] for t in out] == ["Acme Market Inc", "Acme Bistro"]

    out = qw.filter_by_payee(txns, "Inc", mode="endswith", case_sensitive=False)
    assert [t["payee"] for t in out] == ["Acme Market Inc"]


# --------------------------- filter_by_payees ---------------------------------


def test_filter_by_payees_any_vs_all_combines_queries():
    """filter_by_payees: supports OR ('any') and AND ('all') combination across queries.

    Setup includes:
      • 'Acme Market Inc' (matches 'acme')
      • 'Acme Bistro' (matches both 'acme' and 'bistro')
      • 'Other' (matches neither)
    """
    txns = [
        {"payee": "Acme Market Inc"},
        {"payee": "Acme Bistro"},
        {"payee": "Other"},
    ]
    queries = ["acme", "bistro"]

    out_any = qw.filter_by_payees(
        txns, queries, mode="contains", case_sensitive=False, combine="any"
    )
    assert [t["payee"] for t in out_any] == ["Acme Market Inc", "Acme Bistro"]

    out_all = qw.filter_by_payees(
        txns, queries, mode="contains", case_sensitive=False, combine="all"
    )
    assert [t["payee"] for t in out_all] == ["Acme Bistro"]


def test_filter_by_payees_regex_and_glob_modes():
    """filter_by_payees: works with regex and glob modes across multiple queries.

    We use:
      • regex to match 'Acme' followed by a word
      • glob to catch 'Other*Co'
    """
    txns = [
        {"payee": "Acme Market Inc"},
        {"payee": "Acme Bistro"},
        {"payee": "Other Co"},
    ]

    out_regex = qw.filter_by_payees(
        txns, [r"Acme\s+\w+"], mode="regex", case_sensitive=False, combine="any"
    )
    assert [t["payee"] for t in out_regex] == ["Acme Market Inc", "Acme Bistro"]

    out_glob = qw.filter_by_payees(
        txns, ["Other*Co"], mode="glob", case_sensitive=True, combine="any"
    )
    assert [t["payee"] for t in out_glob] == ["Other Co"]


# ------------------------- filter_by_date_range --------------------------------


def test_filter_by_date_range_inclusive_and_formats():
    """filter_by_date_range: includes boundary dates and supports multiple formats.

    Dates in txns:
      • "01/02/2025"
      • "2025-01-03"
      • "01/03'25" (QIF classic two-digit year with apostrophe)
      • "01/04/2025"
      • "bad" (ignored)
    Window: from "2025-01-02" to "01/03/2025" (inclusive)
    Expected: keep the first three, drop the 01/04 and bad entry.
    """
    txns = [
        {"date": "01/02/2025", "payee": "A"},
        {"date": "2025-01-03", "payee": "B"},
        {"date": "01/03'25", "payee": "B2"},
        {"date": "01/04/2025", "payee": "C"},
        {"date": "bad", "payee": "D"},
    ]
    out = qw.filter_by_date_range(txns, date_from="2025-01-02", date_to="01/03/2025")
    assert [t["payee"] for t in out] == ["A", "B", "B2"]


def test_filter_by_date_range_open_ended_from_and_to():
    """filter_by_date_range: supports open-ended windows (only from, only to).

    Verify:
      • Only 'date_from' keeps entries >= start
      • Only 'date_to' keeps entries <= end
      • Unparseable dates are skipped silently
    """
    txns = [
        {"date": "2025-01-01", "payee": "A"},
        {"date": "2025-01-02", "payee": "B"},
        {"date": "bad", "payee": "X"},
        {"date": "2025-01-03", "payee": "C"},
    ]

    out_from = qw.filter_by_date_range(txns, date_from="2025-01-02", date_to=None)
    assert [t["payee"] for t in out_from] == ["B", "C"]

    out_to = qw.filter_by_date_range(txns, date_from=None, date_to="2025-01-02")
    assert [t["payee"] for t in out_to] == ["A", "B"]
