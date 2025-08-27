from __future__ import annotations

import binascii
import zlib
from pathlib import Path

import pytest

import quicken_helper.legacy.qdx_probe as qdx

# ------------------------------- small helpers --------------------------------

def _mk_qif(tmp_path: Path, body: str = "!Type:Bank\nD01/01'25\n^\nD01/02'25\n^\n") -> Path:
    """Create a minimal QIF file with two '^' terminators (2 txns by our counter)."""
    p = tmp_path / "sample.qif"
    p.write_text(body, encoding="utf-8")
    return p


# -------------------------------- read_bytes ----------------------------------

def test_read_bytes_reads_exact_file_bytes(tmp_path: Path):
    """read_bytes: returns the identical bytes written to the file (binary-safe)."""
    p = tmp_path / "blob.bin"
    data = b"\x00\x01ABC\xff"
    p.write_bytes(data)
    assert qdx.read_bytes(p) == data


# --------------------------------- hex_head -----------------------------------

def test_hex_head_returns_lowercase_hex_of_prefix():
    """hex_head: formats the first N bytes as lowercase hex, length == 2*N."""
    data = b"\x00\x01\xab\xcd\xef"
    out = qdx.hex_head(data, length=4)
    assert out == binascii.hexlify(data[:4]).decode()
    assert out.islower() and len(out) == 8  # 2 hex chars per byte


# ---------------------------------- entropy -----------------------------------

def test_entropy_zero_stream_is_zero_and_uniform_0_255_is_eight_bits():
    """entropy: 0.0 bits/byte for constant stream; ~8.0 for a uniform 0..255 byte set."""
    assert qdx.entropy(b"\x00" * 256) == 0.0
    # A single pass of 0..255 should evaluate to 8.0 exactly in this implementation.
    assert pytest.approx(qdx.entropy(bytes(range(256))), rel=0, abs=1e-9) == 8.0


# ------------------------------- string scans ---------------------------------

def test_iter_ascii_strings_emits_only_runs_of_len_at_least_MIN_STR():
    """iter_ascii_strings: emits only ASCII runs with length >= MIN_STR; shorter runs are ignored."""
    # runs: "short"(5) ignored, "longenough"(10) captured, "123456"(6) captured
    data = b"short\x00longenough\x00abc\x00123456\x00"
    outs = list(qdx.iter_ascii_strings(data))
    assert "longenough" in outs and "123456" in outs
    assert not any(s == "short" for s in outs)

def test_iter_utf16le_strings_extracts_readable_runs(tmp_path: Path):
    """iter_utf16le_strings: decodes UTF-16LE runs and emits those >= MIN_STR characters."""
    s = "hello world"  # 11 chars >= default MIN_STR=6
    data = s.encode("utf-16le")
    outs = list(qdx.iter_utf16le_strings(data))
    assert s in outs


# ------------------------------- container sigs -------------------------------

def test_is_zip_and_is_gzip_detect_headers():
    """is_zip/is_gzip: detect PK.. (ZIP) and 1F 8B 08.. (GZIP) magic headers; random bytes are False."""
    assert qdx.is_zip(b"PK\x03\x04more")
    assert qdx.is_gzip(b"\x1f\x8b\x08rest")
    assert not qdx.is_zip(b"NOZIP")
    assert not qdx.is_gzip(b"NOZIP")


# ------------------------------ zlib detection --------------------------------

def test_find_zlib_streams_and_try_decompress_at_roundtrip():
    """find_zlib_streams/try_decompress_at: finds zlib header offsets and decompresses successfully.
    Invalid offsets return None from try_decompress_at.
    """
    payload = b"HEAD" + zlib.compress(b"spam" * 8) + b"TAIL"
    offs = qdx.find_zlib_streams(payload)
    assert offs and offs[0] == 4  # immediately after "HEAD"
    # Valid offset decompresses
    out = qdx.try_decompress_at(payload, offs[0])
    assert out.startswith(b"spam")
    # Invalid offset yields None
    assert qdx.try_decompress_at(payload, 1) is None


# -------------------------------- preview_text --------------------------------

def test_preview_text_truncates_and_falls_back_to_latin1():
    """preview_text: decodes as UTF-8 with ignore; falls back to latin-1; trims; truncates with ellipsis."""
    # Force latin-1 fallback (\xff) and length > maxlen to trigger ellipsis.
    blob = (b"\xff" + b"x" * 100)
    view = qdx.preview_text(blob, maxlen=20)
    ellipsis = " …"  # space + ellipsis, used by preview_text on truncation
    assert len(view) <= 20 + len(ellipsis) and view.endswith(ellipsis)


# -------------------------------- QIF counter ---------------------------------

def test_count_qif_transactions_counts_caret_lines(tmp_path: Path):
    """count_qif_transactions: counts lines that are exactly '^' as transactions."""
    qif = _mk_qif(tmp_path, body="!Type:Bank\n^\n^\n^\n")
    assert qdx.count_qif_transactions(qif) == 3


# ------------------------------- run_probe (I/O) -------------------------------

def test_run_probe_returns_report_and_no_artifacts_when_out_none(tmp_path: Path):
    """run_probe: on a zlib-only blob, returns a report as a string and no artifacts when out=None.
    The report includes container info, zlib candidate preview, and QIF comparison.
    """
    qdx_path = tmp_path / "sample.qdx"
    qdx_path.write_bytes(zlib.compress(b"<xml>hello</xml> moretext"))
    qif = _mk_qif(tmp_path)

    report, artifacts = qdx.run_probe(qdx_path, qif=qif, out=None)
    assert isinstance(report, str) and artifacts == []
    # Robust substring checks (don’t rely on exact formatting):
    assert "# QDX Probe" in report
    assert "Container" in report or "Container:" in report
    assert "zlib candidates" in report
    assert "preview: <xml>hello</xml> moretext" in report
    assert "transactions by '^' lines: 2" in report  # explicit standalone line for easy asserting

def test_run_probe_writes_txt_and_artifacts_when_out_is_file(tmp_path: Path):
    """run_probe: when 'out' is a .txt path, writes the report to that path and saves artifacts
    (e.g., decompressed zlib_* blobs) into the same directory; returns artifact paths.
    """
    qdx_path = tmp_path / "with_zlib.qdx"
    comp = zlib.compress(b"DECOMP" + b"X" * 50)
    qdx_path.write_bytes(b"HEAD" + comp + b"TAIL")
    qif = _mk_qif(tmp_path, body="^\n^\n^\n")
    out_txt = tmp_path / "probe.txt"

    report, artifacts = qdx.run_probe(qdx_path, qif=qif, out=out_txt)
    assert out_txt.exists()
    # At least one decompressed blob should be saved; verify contents are plausible length.
    assert artifacts and all(p.exists() for p in artifacts)
    # The known offset after "HEAD" is 4; many implementations name like zlib_00000004.bin
    assert any("00000004" in p.name for p in artifacts)

def test_run_probe_writes_txt_inside_dir_when_out_is_directory(tmp_path: Path):
    """run_probe: when 'out' is a directory, writes 'qdx_probe_report.txt' inside it and saves artifacts there."""
    out_dir = tmp_path / "outdir"
    out_dir.mkdir()
    qdx_path = tmp_path / "f.qdx"
    qdx_path.write_bytes(zlib.compress(b"abc" * 10))
    report, artifacts = qdx.run_probe(qdx_path, qif=None, out=out_dir)

    report_file = out_dir / "qdx_probe_report.txt"
    assert report_file.exists()
    # Even if artifacts may be empty for tiny inputs, the report should exist and be non-empty.
    assert isinstance(report, str) and len(report) > 0
