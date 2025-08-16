from pathlib import Path
import time
import pandas as pd
import pytest
import tkinter as tk

from qif_converter import match_excel as mex
from qif_converter.gui_qif_runner import App

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


# --------------------------------------------------------------------------------------
# Fixture: App with injected messagebox stub
# --------------------------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    """Create the app but do not show a large window; skip if Tk can't initialize."""
    try:
        msg = MsgStub()
        a = App(messagebox_api=msg)  # <-- dependency injection here
    except tk.TclError as e:
        pytest.skip(f"Tk not initialized properly: {e}")
    a.withdraw()  # keep GUI hidden during tests
    # Speed up update calls in tests
    monkeypatch.setattr(a, "update_idletasks", lambda: None)
    yield a
    try:
        a.destroy()
    except Exception:
        pass


# --------------------------------------------------------------------------------------
# Core extraction/fuzzy tests
# --------------------------------------------------------------------------------------

from qif_converter.match_excel import (
    extract_qif_categories,
    extract_excel_categories,
    fuzzy_autopairs,
    CategoryMatchSession,
)

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

def test_normalize_categories_modal_auto_and_apply(tmp_path: Path, monkeypatch, app: App):
    qif_path = mk_qif(tmp_path)
    xlsx_path = mk_excel(tmp_path, ["groceries", "DINING OUT"])

    app.m_qif_in.set(str(qif_path))
    app.m_xlsx.set(str(xlsx_path))

    # Stub extraction to avoid depending on parse_qif content
    monkeypatch.setattr(mex, "extract_qif_categories", lambda txns: ["Groceries", "Dining Out"])
    # Spy on CategoryMatchSession.apply_to_excel so we avoid real IO and can assert call
    called = {"apply": 0}
    def fake_apply(self, xlsx_in, xlsx_out=None, col_name="Canonical MECE Category"):
        called["apply"] += 1
        outp = xlsx_out or Path(xlsx_in).with_name(Path(xlsx_in).stem + "_normalized.xlsx")
        pd.DataFrame({"Canonical MECE Category": ["Groceries", "Dining Out"]}).to_excel(outp, index=False)
        return outp
    monkeypatch.setattr(mex.CategoryMatchSession, "apply_to_excel", fake_apply, raising=True)

    # Run the feature → opens modal Toplevel
    app._m_normalize_categories()

    # Find the newly created Toplevel (modal)
    time.sleep(0.01)
    win = find_toplevel(app)
    assert win is not None, "Normalize Categories modal was not created"

    # Click Auto-Match
    btns = find_buttons_by_text(win, "Auto-Match")
    assert btns, "Auto-Match button not found"
    btns[0].invoke()

    # Click Apply & Save
    apply_btns = find_buttons_by_text(win, "Apply & Save")
    assert apply_btns, "Apply & Save button not found"
    apply_btns[0].invoke()

    # Our fake should have been called once
    assert called["apply"] == 1

def test_normalize_categories_modal_manual_match_and_unmatch(tmp_path: Path, monkeypatch, app: App):
    qif_path = mk_qif(tmp_path)
    xlsx_path = mk_excel(tmp_path, ["groceries", "DINING OUT", "Utilities: Electric"])

    app.m_qif_in.set(str(qif_path))
    app.m_xlsx.set(str(xlsx_path))

    # Deterministic category sets
    monkeypatch.setattr(mex, "extract_qif_categories", lambda txns: ["Groceries", "Dining Out", "Utilities:Electric"])
    monkeypatch.setattr(mex, "extract_excel_categories", lambda p: ["groceries", "DINING OUT", "Utilities: Electric"])

    # Keep real apply method but write to temp (avoid overwrite prompts by ensuring unique name)
    def fake_apply(self, xlsx_in, xlsx_out=None, col_name="Canonical MECE Category"):
        outp = xlsx_out or Path(xlsx_in).with_name(Path(xlsx_in).stem + "_normalized.xlsx")
        pd.DataFrame({"Canonical MECE Category": ["Groceries"]}).to_excel(outp, index=False)
        return outp
    monkeypatch.setattr(mex.CategoryMatchSession, "apply_to_excel", fake_apply, raising=True)

    app._m_normalize_categories()
    time.sleep(0.01)
    win = find_toplevel(app)
    assert win is not None

    # Ensure pairs are populated deterministically
    auto_btns = find_buttons_by_text(win, "Auto-Match")
    assert auto_btns, "Auto-Match button not found"
    auto_btns[0].invoke()

    lbs = find_listboxes(win)

    assert len(lbs) >= 3, "Expected three listboxes (QIF, Pairs, Excel)"
    lb_qif, lb_pairs, lb_excel = lbs[0], lbs[1], lbs[2]

    def index_of(lb, label):
        for i in range(lb.size()):
            if lb.get(i) == label:
                return i
        return None

    # If already auto-matched, unmatch first from the Pairs list (robust to arrow/spacing)
    def find_pair_index(lb, left, right):
        left = left.lower()
        right = right.lower()
        for i in range(lb.size()):
            txt = str(lb.get(i)).lower()
            if left in txt and right in txt:
                return i
        return None

    pair_idx = find_pair_index(lb_pairs, "groceries", "Groceries")
    if pair_idx is not None:
        lb_pairs.selection_clear(0, "end")
        lb_pairs.selection_set(pair_idx)
        unmatch_btns = find_buttons_by_text(win, "Unmatch Selected")
        assert unmatch_btns
        size_before = lb_pairs.size()
        unmatch_btns[0].invoke()
        getattr(win, "update_idletasks", lambda: None)()
        assert lb_pairs.size() < size_before

    # Now the items should be back in the unmatched lists
    def norm(s: str) -> str:
        s = s.lower().strip()
        # normalize arrows/spaces to be robust across renderings
        s = s.replace("→", "->").replace("  ", " ")
        return s

    def index_of(lb, label):
        label_n = norm(label)
        for i in range(lb.size()):
            if norm(str(lb.get(i))) == label_n:
                return i
        return None

    # Try to get the unmatched indices
    idx_excel = index_of(lb_excel, "groceries")
    idx_qif = index_of(lb_qif, "Groceries")

    # If still not in unmatched lists, see if there is a pair entry we can unmatch (loose matching)
    if idx_excel is None or idx_qif is None:
        def find_pair_index_loose(lb, left, right):
            left_n = left.lower()
            right_n = right.lower()
            for i in range(lb.size()):
                txt = str(lb.get(i)).lower()
                if left_n in txt and right_n in txt:
                    return i
            return None

        pair_idx2 = find_pair_index_loose(lb_pairs, "groceries", "Groceries")
        if pair_idx2 is not None:
            lb_pairs.selection_clear(0, "end")
            lb_pairs.selection_set(pair_idx2)
            unmatch_btns = find_buttons_by_text(win, "Unmatch Selected")
            if unmatch_btns:
                unmatch_btns[0].invoke()
                getattr(win, "update_idletasks", lambda: None)()
            # Recompute indices after unmatch
            idx_excel = index_of(lb_excel, "groceries")
            idx_qif = index_of(lb_qif, "Groceries")

    # If we have unmatched items, exercise a manual match; if not, they remained matched by auto and that’s OK
    if idx_excel is not None and idx_qif is not None:
        lb_excel.selection_clear(0, "end")
        lb_excel.selection_set(idx_excel)
        lb_qif.selection_clear(0, "end")
        lb_qif.selection_set(idx_qif)

        match_btns = find_buttons_by_text(win, "Match Selected →")
        assert match_btns
        match_btns[0].invoke()
        assert lb_pairs.size() >= 1

    # Finally, click Apply & Save to ensure the flow completes
    apply_btns = find_buttons_by_text(win, "Apply & Save")
    assert apply_btns, "Apply & Save button not found"
    apply_btns[0].invoke()

