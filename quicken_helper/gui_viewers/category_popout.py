# quicken_helper/gui_viewers/category_popout.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Set, Tuple

try:
    # Keep import local to the module for easy monkeypatching in tests
    from quicken_helper.controllers import merge_excel as mex
except Exception:  # pragma: no cover
    mex = None  # will raise at runtime if used without being available


@dataclass(frozen=True)
class _MB:
    """Minimal interface we expect from a messagebox-like object."""
    showinfo: callable
    showerror: callable


def compute_category_sets(session, xlsx_path: Path | str) -> Tuple[Set[str], Set[str]]:
    """
    Compute the set of QIF categories present in the *matched* transactions and the set
    of Excel categories present in the source spreadsheet.

    Relies on controllers.merge_excel helpers:
      - mex.build_matched_only_txns(session)
      - mex.extract_qif_categories(transactions)
      - mex.extract_excel_categories(xlsx_path)
    """
    if mex is None:
        raise RuntimeError("merge_excel module not available")

    matched_txns = mex.build_matched_only_txns(session)
    qif_cats: Set[str] = set(mex.extract_qif_categories(matched_txns) or set())
    excel_cats: Set[str] = set(mex.extract_excel_categories(xlsx_path) or set())
    return qif_cats, excel_cats


def open_normalize_modal(
    master,
    session,
    xlsx_path: Path | str,
    mb: Optional[_MB] = None,
    *,
    show_ui: bool = True,
):
    """
    Entry point for the 'Normalize Categories' flow.

    Returns:
        (qif_cats, excel_cats) so tests can assert without a GUI.

    Behavior:
      • Computes category sets via compute_category_sets(...)
      • If show_ui=False, only uses mb.showinfo (if provided) and returns.
      • If show_ui=True and a master is provided, you can expand this to build a Toplevel.
        (For now, to keep logic centralized and testable, we simply notify via mb.)
    """
    qif_cats, excel_cats = compute_category_sets(session, xlsx_path)

    if mb is not None:
        mb.showinfo(
            "Normalize Categories",
            (
                "Found categories:\n"
                f"• QIF (matched): {len(qif_cats)}\n"
                f"• Excel: {len(excel_cats)}"
            ),
        )

    # Optionally, you can create a Toplevel UI here if show_ui and master are provided.
    # Left intentionally simple to keep this module unit-test friendly.
    return qif_cats, excel_cats
