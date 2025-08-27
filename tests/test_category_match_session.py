from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import quicken_helper.controllers.category_match_session as cms
from quicken_helper.controllers.category_match_session import CategoryMatchSession

# ------------------------------ auto_match ------------------------------------

def test_auto_match_uses_fuzzy_autopairs_and_builds_mapping(monkeypatch):
    """auto_match: delegates to cms.fuzzy_autopairs with the given threshold and
    updates the session mapping from the returned (qif, excel, score) pairs.

    We monkeypatch cms.fuzzy_autopairs to a deterministic fake so the test
    inspects exactly what was passed and verifies the mapping produced.
    """
    # Arrange
    qif = ["Food:Groceries", "Food:Restaurants"]
    excel = ["Groceries", "Restaurants"]
    called = {}

    def fake_fuzzy_autopairs(qif_cats, excel_cats, threshold):
        # capture what was passed
        called["args"] = (tuple(qif_cats), tuple(excel_cats), threshold)
        # return deterministic pairs (qif, excel, score)
        return [
            ("Food:Groceries", "Groceries", 0.91),
            ("Food:Restaurants", "Restaurants", 0.89),
        ], [], []

    monkeypatch.setattr(cms, "fuzzy_autopairs", fake_fuzzy_autopairs)

    s = CategoryMatchSession(qif, excel)

    # Act
    s.auto_match(threshold=0.9)

    # Assert
    assert called["args"] == (tuple(qif), tuple(excel), 0.9)
    assert s.mapping == {
        "Groceries": "Food:Groceries",
        "Restaurants": "Food:Restaurants",
    }


def test_auto_match_threshold_controls_pairs(monkeypatch):
    """auto_match: passes the threshold through to cms.fuzzy_autopairs, and if
    no pairs are returned above that threshold, the mapping remains empty.
    """
    # Arrange
    s = CategoryMatchSession(["A"], ["a"])
    seen = {}
    def fake(q, e, t):
        seen["threshold"] = t
        return [], ["A"], ["a"]
    monkeypatch.setattr(cms, "fuzzy_autopairs", fake)

    # Act
    s.auto_match(threshold=0.95)

    # Assert
    assert seen["threshold"] == 0.95
    assert s.mapping == {}  # nothing added


# ----------------------------- manual_match -----------------------------------

def test_manual_match_accepts_valid_names_and_enforces_one_to_one():
    """manual_match: accepts valid Excel/QIF names and enforces a one-to-one
    mapping by removing any other Excel key previously mapped to the same QIF.
    """
    # Arrange
    s = CategoryMatchSession(
        qif_cats=["Food:Groceries", "Food:Restaurants"],
        excel_cats=["Groceries", "Market"],
    )
    ok, msg = s.manual_match("Groceries", "Food:Groceries")
    assert ok and msg == "Matched."
    # Act: re-map Food:Groceries to a different Excel name
    ok2, msg2 = s.manual_match("Market", "Food:Groceries")
    # Assert: one-to-one enforced → previous Excel mapping removed
    assert ok2 and msg2 == "Matched."
    assert "Groceries" not in s.mapping
    assert s.mapping == {"Market": "Food:Groceries"}


@pytest.mark.parametrize(
    "excel_name,qif_name,expect_ok,expect_msg",
    [
        ("NotInExcel", "Food:Groceries", False, "Excel category not in list."),
        ("Groceries", "NotInQIF", False, "QIF category not in list."),
    ],
)
def test_manual_match_rejects_unknown_names(excel_name, qif_name, expect_ok, expect_msg):
    """manual_match: rejects Excel/QIF names that are not present in the
    session's source lists and returns explanatory messages.
    """
    s = CategoryMatchSession(
        qif_cats=["Food:Groceries"],
        excel_cats=["Groceries"],
    )
    ok, msg = s.manual_match(excel_name, qif_name)
    assert (ok, msg) == (expect_ok, expect_msg)


# ---------------------------- manual_unmatch ----------------------------------

def test_manual_unmatch_returns_true_when_present_false_when_absent():
    """manual_unmatch: returns True iff a mapping entry existed and was removed,
    otherwise False (idempotent on repeated calls).
    """
    s = CategoryMatchSession(["A"], ["a"])
    s.mapping["a"] = "A"
    assert s.manual_unmatch("a") is True
    assert s.manual_unmatch("a") is False  # already removed


# ------------------------------ unmatched -------------------------------------

def test_unmatched_returns_items_not_in_mapping():
    """unmatched: returns the remaining QIF and Excel category names that have
    not yet been mapped, preserving input order."""
    s = CategoryMatchSession(qif_cats=["A", "B"], excel_cats=["x", "y"])
    s.mapping["x"] = "A"
    uq, ue = s.unmatched()
    assert uq == ["B"]
    assert ue == ["y"]


# --------------------------- apply_to_excel -----------------------------------

def test_apply_to_excel_replaces_cells_and_writes_default_output(monkeypatch, tmp_path):
    """apply_to_excel: reads an Excel file, replaces cells in the 'Canonical MECE Category'
    column using the session mapping, and writes to a default '*_normalized.xlsx' file.

    We monkeypatch pandas.read_excel to return an in-memory DataFrame and monkeypatch
    DataFrame.to_excel with a (*args, **kwargs) signature to avoid 'self' binding
    warnings and to capture the output path and mutated values.
    """
    # Arrange
    input_path = tmp_path / "cats.xlsx"
    df = pd.DataFrame({
        "Canonical MECE Category": ["Groceries", "Unmapped", "Restaurants"],
        "Other": [1, 2, 3],
    })

    # Monkeypatch pandas IO
    monkeypatch.setattr(pd, "read_excel", lambda p: df)
    captured = {}
    def fake_to_excel(self, out_path, index=False):
        captured["out_path"] = out_path
        captured["values"] = self["Canonical MECE Category"].tolist()
    monkeypatch.setattr(pd.DataFrame, "to_excel", fake_to_excel, raising=False)

    s = CategoryMatchSession(
        qif_cats=["Food:Groceries", "Food:Restaurants"],
        excel_cats=["Groceries", "Restaurants", "Unmapped"],
    )
    s.mapping = {
        "Groceries": "Food:Groceries",
        "Restaurants": "Food:Restaurants",
    }

    # Act
    out_path = s.apply_to_excel(input_path)

    # Assert
    assert Path(out_path).name == "cats_normalized.xlsx"
    assert Path(captured["out_path"]).name == "cats_normalized.xlsx"
    assert captured["values"] == ["Food:Groceries", "Unmapped", "Food:Restaurants"]


def test_apply_to_excel_raises_if_column_missing(monkeypatch, tmp_path):
    """apply_to_excel: raises ValueError when the expected 'Canonical MECE Category'
    column is missing in the input Excel sheet."""
    # Arrange
    input_path = tmp_path / "cats.xlsx"
    df = pd.DataFrame({"Wrong Column": ["x"]})
    monkeypatch.setattr(pd, "read_excel", lambda p: df)

    s = CategoryMatchSession(qif_cats=["A"], excel_cats=["a"])

    # Act / Assert
    with pytest.raises(ValueError) as ei:
        s.apply_to_excel(input_path)
    assert "Canonical MECE Category" in str(ei.value)


def test_apply_to_excel_respects_explicit_output_path(monkeypatch, tmp_path):
    """apply_to_excel: honors an explicit output path if provided and writes there
    instead of using the default '*_normalized.xlsx' filename."""
    # Arrange
    input_path = tmp_path / "cats.xlsx"
    explicit = tmp_path / "out.xlsx"
    df = pd.DataFrame({"Canonical MECE Category": ["A"]})
    monkeypatch.setattr(pd, "read_excel", lambda p: df)
    captured = {}
    def fake_to_excel(self, out_path, index=False):
        captured["out_path"] = out_path
    monkeypatch.setattr(pd.DataFrame, "to_excel", fake_to_excel, raising=False)

    s = CategoryMatchSession(["A"], ["A"])

    # Act
    out_path = s.apply_to_excel(input_path, xlsx_out=explicit)

    # Assert
    assert out_path == explicit
    assert captured["out_path"] == explicit
