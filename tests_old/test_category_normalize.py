from pathlib import Path
import time
import pandas as pd
import pytest
import tkinter as tk

from qif_converter.category_match_session import CategoryMatchSession
from qif_converter.match_excel import extract_qif_categories
from qif_converter import qif_to_csv as mod
from qif_converter.gui import App

# Skip entirely if tkinter isn’t importable (e.g., headless CI without Tk)
pytest.importorskip("tkinter")


# --------------------------------------------------------------------------------------
# Messagebox stub (dependency injection target)
# --------------------------------------------------------------------------------------

class MsgStub:
    """Stub for tkinter.messagebox to prevent real dialogs during tests."""
    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def showinfo(self, *a, **k):
        self.calls.append(("showinfo", a, k))
        return None

    def showerror(self, *a, **k):
        self.calls.append(("showerror", a, k))
        return None

    def askyesno(self, *a, **k):
        self.calls.append(("askyesno", a, k))
        # default True, can override via answers={"askyesno": False}
        return self.answers.get("askyesno", True)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _mk_tx(date="08/01/2025", amount="-1.00", payee="X", category="", splits=None, memo=""):
    return {
        "date": date,
        "amount": amount,
        "payee": payee,
        "category": category,
        "memo": memo,
        "splits": splits or [],
    }

def _mk_split(category="", memo="", amount="0.00"):
    return {"category": category, "memo": memo, "amount": amount}

def all_children(widget):
    """Recursively collect all Tk widgets under widget."""
    out = []
    stack = [widget]
    while stack:
        w = stack.pop()
        try:
            kids = w.winfo_children()
        except Exception:
            kids = []
        out.extend(kids)
        stack.extend(kids)
    return out

def find_buttons_by_text(root, label_text):
    matches = []
    for w in all_children(root):
        try:
            if w.winfo_class() in ("TButton", "Button"):
                if str(w.cget("text")) == label_text:
                    matches.append(w)
        except Exception:
            pass
    return matches

def find_listboxes(root):
    boxes = []
    for w in all_children(root):
        try:
            if w.winfo_class() == "Listbox":
                boxes.append(w)
        except Exception:
            pass
    return boxes

def find_toplevel(app: App):
    """Find the Normalize Categories modal Toplevel, even if not listed in direct children."""
    tops = [w for w in app.winfo_children() if str(w.winfo_class()).lower() == "toplevel"]
    if tops:
        return tops[-1]
    for w in all_children(app):
        if str(w.winfo_class()).lower() == "toplevel":
            return w
    return None


@pytest.fixture
def headless_normalize():
    """
    Returns a factory to open a headless normalization "modal" with the same
    surface as the GUI version (auto_match, do_match, do_unmatch, unmatched,
    pairs, apply_and_save) — but never touches Tk/TTK.
    """
    class Factory:
        def open(self, qif_in: Path, xlsx: Path):
            txns = mod.parse_qif(qif_in)
            qif_cats = extract_qif_categories(txns)
            excel_cats = extract_excel_categories(xlsx)
            sess = CategoryMatchSession(qif_cats, excel_cats)

            class HeadlessModal:
                def auto_match(self, threshold: float = 0.84):
                    sess.auto_match(threshold)

                def do_match(self, excel_name: str, qif_name: str):
                    return sess.manual_match(excel_name, qif_name)

                def do_unmatch(self, excel_name: str):
                    return sess.manual_unmatch(excel_name)

                def unmatched(self):
                    return sess.unmatched()

                def pairs(self):
                    return [
                        f"{e}  →  {q}"
                        for e, q in sorted(sess.mapping.items(), key=lambda kv: kv[0].lower())
                    ]

                def apply_and_save(self, out_path: Path | None = None):
                    outp = out_path or xlsx.with_name(xlsx.stem + "_normalized.xlsx")
                    return sess.apply_to_excel(xlsx, xlsx_out=outp)

            return HeadlessModal()
    return Factory()


# --------------------------------------------------------------------------------------
# Core extraction/fuzzy tests
# --------------------------------------------------------------------------------------



from qif_converter.match_excel import (
    extract_qif_categories,
    extract_excel_categories,
    fuzzy_autopairs,
)
from qif_converter.category_match_session import CategoryMatchSession


def test_extract_qif_categories_collects_txn_and_splits_and_sorts():
    txns = [
        _mk_tx(category="Food:Dining"),
        _mk_tx(category=""),
        _mk_tx(category="Utilities:Electric",
               splits=[_mk_split(category="Utilities:Water"), _mk_split(category="")]),
        _mk_tx(category="food:dining"),  # duplicate differing only by case
        _mk_tx(splits=[_mk_split(category="Groceries")]),
    ]
    cats = extract_qif_categories(txns)
    # Deduped (case-insensitive for sorting), blanks dropped, sorted alpha (case-insensitive)
    assert cats == ["Food:Dining", "Groceries", "Utilities:Electric", "Utilities:Water"]

def test_extract_excel_categories_dedupes_and_sorts(tmp_path: Path):
    df = pd.DataFrame({
        "Date": ["2025-08-01", "2025-08-02", "2025-08-03"],
        "Amount": [-1.0, -2.0, -3.0],
        "Item": ["a", "b", "c"],
        "Canonical MECE Category": ["Groceries", "groceries", " Utilities:Electric "],
        "Categorization Rationale": ["", "", ""],
    })
    xlsx = tmp_path / "cats.xlsx"
    df.to_excel(xlsx, index=False)
    cats = extract_excel_categories(xlsx)
    # trim, dedupe case-insensitively, sort (case-insensitive)
    assert cats == ["Groceries", "Utilities:Electric"]

def test_fuzzy_autopairs_threshold_and_one_to_one():
    qif_cats = ["Groceries", "Dining Out", "Utilities:Electric"]
    excel_cats = ["groceries", "DINING OUT", "Utilities: Electric"]

    # Default threshold: all three should match
    pairs, uq, ue = fuzzy_autopairs(qif_cats, excel_cats, threshold=0.84)
    mapped = {(q, e) for (q, e, s) in pairs}
    assert ("Groceries", "groceries") in mapped
    assert ("Dining Out", "DINING OUT") in mapped
    assert ("Utilities:Electric", "Utilities: Electric") in mapped
    assert not uq and not ue

def test_category_match_session_auto_manual_and_unmatch(tmp_path: Path):
    qif_cats = ["Groceries", "Dining Out", "Utilities:Electric"]
    excel_cats = ["groceries", "DINING OUT", "Utilities: Electric", "Groceries "]

    s = CategoryMatchSession(qif_cats, excel_cats)

    # Auto with default threshold: should match all three (case-insensitive close matches)
    s.auto_match()
    m = s.mapping
    assert m.get("groceries") == "Groceries"
    assert m.get("DINING OUT") == "Dining Out"
    assert m.get("Utilities: Electric") == "Utilities:Electric"

    # Now unmatch and confirm removal
    assert s.manual_unmatch("DINING OUT")
    assert "DINING OUT" not in s.mapping

    # Unmatched lists reflect state (Dining Out back to unmatched)
    uq, ue = s.unmatched()
    assert "Dining Out" in uq
    assert "DINING OUT" in ue

    # Apply to Excel: writes a new file and replaces mapped names only
    df = pd.DataFrame({
        "Date": ["2025-08-01", "2025-08-02", "2025-08-03", "2025-08-04"],
        "Amount": [-1, -2, -3, -4],
        "Item": ["a", "b", "c", "d"],
        "Canonical MECE Category": ["groceries", "DINING OUT", "Utilities: Electric", "Other"],
        "Categorization Rationale": ["", "", "", ""],
    })
    xlsx_in = tmp_path / "in.xlsx"
    df.to_excel(xlsx_in, index=False)

    out_path = s.apply_to_excel(xlsx_in)  # default *_normalized.xlsx
    assert out_path.exists()
    df2 = pd.read_excel(out_path)

    # groceries → Groceries; Utilities: Electric → Utilities:Electric; DINING OUT stayed as-is after unmatch
    assert list(df2["Canonical MECE Category"]) == ["Groceries", "DINING OUT", "Utilities:Electric", "Other"]

    # Now overwrite into a custom path and ensure it writes
    xlsx_out = tmp_path / "custom.xlsx"
    out2 = s.apply_to_excel(xlsx_in, xlsx_out=xlsx_out)
    assert out2 == xlsx_out and xlsx_out.exists()

@pytest.mark.parametrize("bad_col", ["MECE", "Category", "Canonical", ""])
def test_apply_to_excel_raises_if_missing_column(tmp_path: Path, bad_col: str):
    df = pd.DataFrame({
        "Date": ["2025-08-01"],
        "Amount": [-1.0],
        "Item": ["x"],
        (bad_col or "NotTheRightColumn"): ["Groceries"],
    })
    xlsx = tmp_path / "bad.xlsx"
    df.to_excel(xlsx, index=False)

    s = CategoryMatchSession(["Groceries"], ["Groceries"])
    with pytest.raises(ValueError):
        s.apply_to_excel(xlsx)  # missing "Canonical MECE Category"


# --------------------------------------------------------------------------------------
# I/O helpers for GUI tests
# --------------------------------------------------------------------------------------

def mk_qif(tmp: Path) -> Path:
    """A tiny QIF; content doesn't matter because we monkeypatch category extraction."""
    text = """!Type:Bank
D08/01'25
T-10.00
PCoffee
LCoffee
^
"""
    p = tmp / "in.qif"
    p.write_text(text, encoding="utf-8")
    return p

def mk_excel(tmp: Path, cats):
    df = pd.DataFrame({
        "Date": ["2025-08-01"] * len(cats),
        "Amount": [-1.00] * len(cats),
        "Item": ["x"] * len(cats),
        "Canonical MECE Category": cats,
        "Categorization Rationale": ["" for _ in cats],
    })
    p = tmp / "in.xlsx"
    df.to_excel(p, index=False)
    return p


# --------------------------------------------------------------------------------------
# GUI tests
# --------------------------------------------------------------------------------------

def test_normalize_categories_modal_auto_and_apply(tmp_path, headless_normalize):
    # Arrange: build a minimal QIF and Excel with overlapping-ish categories
    qif_in = tmp_path / "in.qif"
    qif_in.write_text(
        "!Type:Bank\n"
        "D08/12'25\n"
        "PCoffee Shop\n"
        "T-12.34\n"
        "LFood:Coffee\n"
        "^\n",
        encoding="utf-8",
    )
    xlsx = tmp_path / "cats.xlsx"

    import pandas as pd
    pd.DataFrame(
        {
            "Date": ["2025-08-12"],
            "Amount": ["-12.34"],
            "Item": ["Morning coffee"],
            "Canonical MECE Category": ["Food : coffee"],  # intentionally different case/spacing
            "Categorization Rationale": ["matches QIF 'Food:Coffee'"],
        }
    ).to_excel(xlsx, index=False)

    # Act: open headless normalize, auto-match, save
    modal = headless_normalize.open(qif_in, xlsx)
    modal.auto_match()
    out_file = tmp_path / "cats_normalized.xlsx"
    modal.apply_and_save(out_file)

    # Assert: output exists and category got normalized to the QIF canonical form
    df_out = pd.read_excel(out_file)
    assert "Canonical MECE Category" in df_out.columns
    assert df_out["Canonical MECE Category"].iloc[0] == "Food:Coffee"
    # also ensure we exposed some pairs as the UI would
    pairs = modal.pairs()
    assert any("Food : coffee" in p and "Food:Coffee" in p for p in pairs)

def test_normalize_categories_modal_manual_match_and_unmatch(tmp_path, headless_normalize):
    # Arrange: QIF with canonical category A; Excel with categories B and C to be mapped manually
    qif_in = tmp_path / "in.qif"
    qif_in.write_text(
        "!Type:Bank\n"
        "D08/13'25\n"
        "PStore\n"
        "T-20.00\n"
        "LHousehold:Supplies\n"
        "^\n",
        encoding="utf-8",
    )
    xlsx = tmp_path / "cats.xlsx"

    import pandas as pd
    pd.DataFrame(
        {
            "Date": ["2025-08-13", "2025-08-13"],
            "Amount": ["-20.00", "-20.00"],
            "Item": ["Paper towels", "Soap"],
            "Canonical MECE Category": ["HH supplies", "Home supplies"],
            "Categorization Rationale": ["B", "C"],
        }
    ).to_excel(xlsx, index=False)

    modal = headless_normalize.open(qif_in, xlsx)

    # No auto-match: manual mapping
    ok, msg = modal.do_match("HH supplies", "Household:Supplies")
    assert ok, msg

    # Verify mapping shows up in "pairs"
    pairs = modal.pairs()
    assert any("HH supplies" in p and "Household:Supplies" in p for p in pairs)

    # Unmatch one and ensure it's gone
    assert modal.do_unmatch("HH supplies") is True
    pairs2 = modal.pairs()
    assert all("HH supplies" not in p for p in pairs2)

    # Apply with only remaining mapping (none left now)
    out_path = tmp_path / "cats_out.xlsx"
    modal.apply_and_save(out_path)
    df_out = pd.read_excel(out_path)
    # Unmatched values remain unchanged
    assert set(df_out["Canonical MECE Category"].astype(str)) == {"HH supplies", "Home supplies"}
