from __future__ import annotations

import io
import csv
from pathlib import Path

import pytest

import qif_converter.qif_writer as qw


# ----------------------- helpers (CSV capture w/ args) ------------------------

def _capture_csv_and_args(monkeypatch, call_fn, txns, *, newline=""):
    """Monkeypatch qw._open_for_write to an in-memory stream that captures
    both the written CSV text (on close) and the arguments passed to the
    open helper (e.g., newline). Returns (csv_text, open_args).
    """
    captured = {"newline": None, "text": ""}

    def fake_open(path, *, binary=False, newline=""):
        captured["newline"] = newline

        class CapturingStringIO(io.StringIO):
            def close(self):
                captured["text"] = self.getvalue()
                super().close()

        return CapturingStringIO()

    monkeypatch.setattr(qw, "_open_for_write", fake_open, raising=True)
    call_fn(txns, Path("dummy.csv"), newline=newline)
    return captured["text"], {"newline": captured["newline"]}


# put near your other helpers in tests/test_qif_writer_extra.py
def _capture_csv_text(monkeypatch, call_fn, txns):
    """Monkeypatch qw._open_for_write to an in-memory stream and return the
    final CSV text written by the function under test."""
    captured = {}

    import io
    def fake_open(path, *, binary=False, newline=""):
        class CapturingStringIO(io.StringIO):
            def close(self):
                captured["text"] = self.getvalue()
                super().close()
        # The implementation should now always pass newline=""
        # We don't assert it here; we verify the *content* instead.
        return CapturingStringIO()

    import qif_converter.qif_writer as qw
    monkeypatch.setattr(qw, "_open_for_write", fake_open, raising=True)

    from pathlib import Path
    call_fn(txns, Path("dummy.csv"))
    return captured["text"]



# ----------------------------- QIF extra coverage -----------------------------

def test_write_qif_empty_input_produces_empty_output():
    """write_qif: when given an empty list of transactions, writes nothing."""
    buf = io.StringIO()
    qw.write_qif([], out=buf)
    assert buf.getvalue() == ""


def test_write_qif_skips_optional_fields_when_missing():
    """write_qif: when memo/category/checknum/cleared/address/splits are absent,
    omits the corresponding lines (M/L/N/C/A/S/E/$). Only core D/T/P are present.

    Note: the account header uses 'N<account name>' too; we only check *within the
    transaction record*, not the account header, to avoid false positives.
    """
    txns = [
        {
            "account": "Checking",
            "type": "Bank",
            "date": "02/01/2025",
            "amount": "0.01",
            "payee": "OnlyCore",
            # no memo/category/checknum/cleared/address/splits
        }
    ]
    buf = io.StringIO()
    qw.write_qif(txns, out=buf)
    out = buf.getvalue()

    # Present: date, amount, payee
    assert "D02/01/2025\n" in out
    assert "T0.01\n" in out
    assert "POnlyCore\n" in out

    # Extract just the first transaction record (from !Type to '^')
    start = out.index("!Type:Bank")
    end = out.index("^", start)
    record = out[start:end]

    # Absent in the *record*: memo/category/checknum/cleared/address/splits
    assert "\nM" not in record   # no memo lines
    assert "\nL" not in record   # no category
    assert "\nN" not in record   # no checknum in the txn body
    assert "\nC" not in record   # no cleared
    assert "\nA" not in record   # no address lines
    assert "\nS" not in record and "\nE" not in record and "\n$" not in record  # no splits


def test_write_qif_investment_minimal_action_only_skips_missing_security_fields():
    """write_qif (Invst): if only 'action' is supplied, emit N<Action> but omit
    Y/Q/I/O when security/quantity/price/commission are missing."""
    txns = [
        {
            "account": "Brokerage",
            "type": "Invst",
            "date": "02/02/2025",
            "amount": "-1.00",
            "payee": "B",
            "action": "Buy",
            # security/quantity/price/commission intentionally omitted
        }
    ]
    buf = io.StringIO()
    qw.write_qif(txns, out=buf)
    out = buf.getvalue()

    assert "NBuy\n" in out   # action present
    assert "Y" not in out    # no security line
    assert "\nQ" not in out  # no quantity
    assert "\nI" not in out  # no price
    assert "\nO" not in out  # no commission


# ----------------------------- CSV extra coverage -----------------------------

def test_write_csv_flat_header_only_on_empty_input(monkeypatch):
    """write_csv_flat: with no transactions, writes just the header row (no data rows)."""
    csv_text, _args = _capture_csv_and_args(monkeypatch, qw.write_csv_flat, [])
    # DictReader to parse header; expect zero rows
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    assert rows == []
    # Sanity: header includes key fields
    assert {"date", "amount", "payee"}.issubset(set(reader.fieldnames or []))


def test_write_csv_exploded_header_only_on_empty_input(monkeypatch):
    """write_csv_exploded: with no transactions, writes just the header row."""
    csv_text, _args = _capture_csv_and_args(monkeypatch, qw.write_csv_exploded, [])
    reader = csv.DictReader(io.StringIO(csv_text))
    assert list(reader) == []
    assert {"date", "split_category", "split_amount"}.issubset(set(reader.fieldnames or []))



def test_write_csv_quicken_windows_uses_crlf_line_endings(monkeypatch):
    """write_csv_quicken_windows: emits CRLF line endings when DictWriter is
    configured with lineterminator='\\r\\n' (platform-independent)."""
    import qif_converter.qif_writer as qw
    txns = [{"date": "02/03/2025", "payee": "X", "amount": "1.23", "category": "C", "account": "A"}]

    text = _capture_csv_text(monkeypatch, qw.write_csv_quicken_windows, txns)

    lines = text.splitlines(keepends=True)
    assert len(lines) >= 2  # header + at least one data row
    # Every line must end with CRLF
    assert all(line.endswith("\r\n") for line in lines)
    # And there should be no lone '\n' occurrences
    assert text.replace("\r\n", "").find("\n") == -1


def test_write_csv_quicken_mac_uses_lf_line_endings(monkeypatch):
    """write_csv_quicken_mac: emits LF line endings when DictWriter is
    configured with lineterminator='\\n' (platform-independent)."""
    import qif_converter.qif_writer as qw
    txns = [{"date": "02/04/2025", "payee": "Y", "amount": "-4.56", "category": "C", "account": "A"}]

    text = _capture_csv_text(monkeypatch, qw.write_csv_quicken_mac, txns)

    lines = text.splitlines(keepends=True)
    assert len(lines) >= 2  # header + at least one data row
    # Every line must end with LF
    assert all(line.endswith("\n") for line in lines)
    # And there should be no '\r' at all
    assert "\r" not in text
