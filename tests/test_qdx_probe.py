from pathlib import Path
import io
import struct
import zipfile
import zlib

import pytest

from qif_converter import qdx_probe as qp


def _make_raw_qdx_bytes() -> bytes:
    """
    Build a small 'raw' (non-ZIP/GZIP) binary with:
      - some ASCII strings,
      - a UTF-16LE string,
      - an embedded zlib-compressed blob containing XML-ish text.
    """
    parts = []
    parts.append(b"\x00" * 16)  # filler
    parts.append(b"ACCOUNT_LIST\x00PAYEE_TABLE\x00")  # ASCII tokens

    # UTF-16LE string "QuickenData"
    utf16 = "QuickenData".encode("utf-16le")
    parts.append(utf16 + b"\x00\x00")

    # zlib stream containing XML-ish content
    payload = b"<xml><transactions><t id='1'/><t id='2'/></transactions></xml>"
    comp = zlib.compress(payload)
    parts.append(b"\x00" * 7)  # some noise
    parts.append(comp)
    parts.append(b"\x00" * 5)

    return b"".join(parts)


def _write_file(p: Path, data: bytes):
    p.write_bytes(data)
    return p


def _write_zip_qdx(p: Path) -> Path:
    # Create a tiny ZIP with one member that looks JSON-ish
    with zipfile.ZipFile(p, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("payload.json", b'{"transactions":[{"id":1},{"id":2}]}')
        zf.writestr("meta.txt", b"QDF VERSION 30")
    return p


def _write_qif(p: Path, n: int) -> Path:
    # Create a QIF with n transactions (one caret per txn)
    lines = ["!Type:Bank\n"]
    for i in range(n):
        lines += [f"D08/0{i+1}'25\n", "T-1.00\n", "PTest\n", "^\n"]
    p.write_text("".join(lines), encoding="utf-8")
    return p


def test_run_probe_raw_blob_with_zlib_and_strings(tmp_path: Path):
    qdx_path = tmp_path / "raw.qdx"
    _write_file(qdx_path, _make_raw_qdx_bytes())

    out_dir = tmp_path / "artifacts"
    report, artifacts = qp.run_probe(qdx_path, qif=None, out=out_dir)

    # Report should say raw/proprietary and list zlib candidates
    assert "Container: raw/proprietary" in report
    assert "zlib candidates:" in report
    # Should have at least one decompressed blob saved
    assert artifacts, "expected at least one artifact from zlib scan"
    for a in artifacts:
        assert a.exists() and a.parent == out_dir

    # Report should include some of our token strings
    assert "ASCII strings" in report
    assert "ACCOUNT_LIST" in report or "PAYEE_TABLE" in report


def test_run_probe_zip_container_lists_members(tmp_path: Path):
    qdx_zip = tmp_path / "in_zip.qdx"
    _write_zip_qdx(qdx_zip)

    report, artifacts = qp.run_probe(qdx_zip, qif=None, out=None)

    assert "Container: ZIP" in report
    assert "payload.json" in report
    assert "meta.txt" in report
    # When out=None, artifacts list may be empty (we only save when out_dir is set)
    assert isinstance(artifacts, list)


def test_run_probe_with_qif_compare_and_txt_out(tmp_path: Path):
    qdx_path = tmp_path / "raw2.qdx"
    _write_file(qdx_path, _make_raw_qdx_bytes())
    qif_path = _write_qif(tmp_path / "sample.qif", n=2)

    out_txt = tmp_path / "probe_report.txt"
    report, artifacts = qp.run_probe(qdx_path, qif=qif_path, out=out_txt)

    # A file was requested → the report should be written to that path
    assert out_txt.exists()
    saved = out_txt.read_text(encoding="utf-8")
    assert "QIF compare" in saved
    assert "transactions by '^' lines: 2" in saved

    # For .txt, artifacts (if any) go to the parent directory
    for a in artifacts:
        assert a.parent == out_txt.parent


def test_helpers_detect_signatures_and_strings(tmp_path: Path):
    # Minimal sanity checks on helper functions
    raw = _make_raw_qdx_bytes()
    assert not qp.is_zip(raw)
    assert not qp.is_gzip(raw)

    # ASCII/UTF-16LE string iterators should find some content
    ascii_strs = list(qp.iter_ascii_strings(raw))
    assert any("ACCOUNT" in s for s in ascii_strs)

    utf16_strs = list(qp.iter_utf16le_strings(raw))
    assert any("QuickenData" in s for s in utf16_strs)

    # zlib finder should detect the compressed block we embedded
    offs = qp.find_zlib_streams(raw)
    assert offs, "should find at least one zlib header"
    blob = qp.try_decompress_at(raw, offs[0])
    assert blob is not None
    assert b"<transactions>" in blob
