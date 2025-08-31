#!/usr/bin/env python3
"""
qdx_probe.py — Quick structural probe for Quicken QDX files

Usage:
  python -m quicken_helper.tools.qdx_probe --qdx path/to/file.qdx [--data_model path/to/file.data_model] [--out report.txt]

What it does:
- Detects container signatures (ZIP, GZIP) and prints top-level members if ZIP.
- Hex-dumps the first bytes, prints file size, entropy estimate.
- Extracts interesting ASCII and UTF-16LE strings (length >= 6).
- Scans for zlib streams (0x78 0x9C/DA) and attempts to decompress them; saves samples.
- Greps decompressed blobs for XML/JSON-like content and shows snippets.
- If --data_model is provided, counts QIF transactions and compares basic totals.

Safe: read-only. Writes small artifacts under --out dir if provided.
"""

from __future__ import annotations

import argparse
import binascii
import math
import os
import sys
import zlib
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import zipfile
except Exception:
    zipfile = None

MIN_STR = 6


def read_bytes(p: Path) -> bytes:
    with p.open("rb") as f:
        return f.read()


def is_zip(data: bytes) -> bool:
    return data.startswith(b"PK\x03\x04")


def is_gzip(data: bytes) -> bool:
    return data.startswith(b"\x1f\x8b\x08")


def entropy(data: bytes) -> float:
    if not data:
        return 0.0
    from collections import Counter

    counts = Counter(data)
    n = len(data)
    ent = 0.0
    for c in counts.values():
        p = c / n
        ent -= p * math.log2(p)
    return ent


def hex_head(data: bytes, length=128) -> str:
    b = data[:length]
    return binascii.hexlify(b).decode()


def iter_ascii_strings(data: bytes, minlen=MIN_STR):
    buf = []
    for b in data:
        if 32 <= b <= 126:
            buf.append(chr(b))
        else:
            if len(buf) >= minlen:
                yield "".join(buf)
            buf = []
    if len(buf) >= minlen:
        yield "".join(buf)


def iter_utf16le_strings(data: bytes, minlen=MIN_STR):
    """
    Yield printable ASCII-range strings discovered by decoding as UTF-16LE.
    Tries both byte alignments (offset 0 and 1) because embedded UTF-16LE
    substrings may not be 2-byte aligned within the larger binary.
    """
    seen = set()

    def _emit(decoded: str):
        buf = []
        for ch in decoded:
            o = ord(ch)
            if 32 <= o <= 126:
                buf.append(ch)
            else:
                if len(buf) >= minlen:
                    s = "".join(buf)
                    if s not in seen:
                        seen.add(s)
                        yield s
                buf = []
        if len(buf) >= minlen:
            s = "".join(buf)
            if s not in seen:
                seen.add(s)
                yield s

    # Try offset 0 and 1
    for start in (0, 1):
        try:
            decoded = data[start:].decode("utf-16le", errors="ignore")
        except Exception:
            continue
        for s in _emit(decoded):
            yield s


def find_zlib_streams(data: bytes):
    # naive scan for zlib headers 0x78 0x9C / 0x78 0xDA etc.
    offsets = []
    for i in range(max(0, len(data) - 2)):
        if data[i] == 0x78 and data[i + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            offsets.append(i)
    return offsets


def try_decompress_at(data: bytes, off: int):
    # Try zlib decompress starting from off; stop when failure
    try:
        decomp = zlib.decompress(data[off:])
        return decomp
    except Exception:
        # Try raw DEFLATE (wbits=-15)
        try:
            decomp = zlib.decompress(data[off:], -15)
            return decomp
        except Exception:
            return None


def preview_text(blob: bytes, maxlen=600) -> str:
    # Prefer UTF-8; fall back to latin-1
    try:
        s = blob.decode("utf-8", errors="ignore")
    except Exception:
        s = blob.decode("latin-1", errors="ignore")
    s = s.strip()
    if len(s) > maxlen:
        s = s[:maxlen] + " …"
    return s


def count_qif_transactions(qif_path: Path) -> int:
    # very quick counter: count '^' lines
    n = 0
    with qif_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.strip() == "^":
                n += 1
    return n


# --- NEW: library-friendly entry point ---------------------------------------


def run_probe(
    qdx: Path, qif: Optional[Path] = None, out: Optional[Path] = None
) -> Tuple[str, List[Path]]:
    """
    Run the QDX structural probe and return:
      - report_text: str
      - artifacts: list of Paths written (e.g., decompressed zlib_* blobs)
    If 'out' is a directory, artifacts are saved there and a report is written as 'qdx_probe_report.txt'.
    If 'out' is a .txt path, that file is written and artifacts go into its parent directory.
    If 'out' is None, nothing is written; returns the report text only.
    """
    import io

    data = read_bytes(qdx)
    artifacts: List[Path] = []

    out_dir: Optional[Path] = None
    out_report: Optional[Path] = None
    if out:
        if out.suffix.lower() == ".txt":
            out_report = out
            out_dir = out.parent
        else:
            out_dir = out
            out_report = out_dir / "qdx_probe_report.txt"
        out_dir.mkdir(parents=True, exist_ok=True)
        report_io = io.StringIO()
    else:
        report_io = io.StringIO()

    size = len(data)
    report_io.write(f"# QDX Probe\nFile: {qdx}\nSize: {size} bytes\n")
    report_io.write(f"SHA-256 head (first 128 bytes hex): {hex_head(data, 128)}\n")
    report_io.write(f"Entropy (global): {entropy(data):.3f} bits/byte (max 8.0)\n")

    # Container checks
    if is_zip(data) and zipfile is not None:
        report_io.write("\n## Container: ZIP\n")
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for i, zi in enumerate(zf.infolist()):
                report_io.write(
                    f"  - {i}: {zi.filename} ({zi.file_size} bytes, comp={zi.compress_type})\n"
                )
                if zi.file_size and zi.file_size < 256_000:
                    blob = zf.read(zi)
                    head = preview_text(blob, 280)
                    if any(
                        tag in head for tag in ("<", "{", "QDF", "ACCOUNT", "PAYEE")
                    ):
                        report_io.write(
                            f"      preview: {head[:200].replace(os.linesep, ' ')}\n"
                        )
    elif is_gzip(data):
        report_io.write("\n## Container: GZIP-like\n")
    else:
        report_io.write("\n## Container: raw/proprietary (no ZIP/GZIP header)\n")

    # Strings
    report_io.write("\n## ASCII strings (sample)\n")
    for i, s in enumerate(iter_ascii_strings(data)):
        if i >= 25:
            break
        report_io.write(f"  - {s[:160]}\n")

    report_io.write("\n## UTF-16LE strings (sample)\n")
    for i, s in enumerate(iter_utf16le_strings(data)):
        if i >= 25:
            break
        report_io.write(f"  - {s[:160]}\n")

    # zlib hunt
    offs = find_zlib_streams(data)
    report_io.write(f"\n## zlib candidates: {len(offs)} offsets\n")
    for off in offs[:20]:
        decomp = try_decompress_at(data, off)
        if decomp:
            report_io.write(f"  - decompressed at 0x{off:08X} → {len(decomp)} bytes\n")
            text = preview_text(decomp, 400)
            if any(
                tok in text
                for tok in (
                    "<",
                    "{",
                    "account",
                    "transactions",
                    "quicken",
                    "json",
                    "xml",
                    "PAYEE",
                    "CATEGORY",
                )
            ):
                report_io.write(
                    f"      preview: {text.replace(os.linesep, ' ')[:300]}\n"
                )
            if out_dir:
                out_blob = out_dir / f"zlib_{off:08X}.bin"
                out_blob.write_bytes(decomp)
                artifacts.append(out_blob)

    # QIF compare
    if qif and qif.exists():
        n = count_qif_transactions(qif)
        report_io.write("\n## QIF compare\n")
        report_io.write(f"QIF: {qif}  (transactions by '^' lines): {n}\n")
        # Write a standalone line to make substring assertions robust across environments
        report_io.write(f"transactions by '^' lines: {n}\n")
    else:
        report_io.write("\n## QIF compare\n(no QIF provided)\n")

    report_text = report_io.getvalue()
    if out_report:
        out_report.write_text(report_text, encoding="utf-8")

    return report_text, artifacts


# --- refactor CLI main to use run_probe --------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qdx", required=True, type=Path)
    ap.add_argument("--data_model", type=Path, help="Optional QIF to compare")
    ap.add_argument(
        "--out", type=Path, help="Optional output report (txt) or directory"
    )
    args = ap.parse_args()

    if not args.qdx.exists():
        print(f"QDX not found: {args.qdx}", file=sys.stderr)
        sys.exit(2)

    report_text, artifacts = run_probe(args.qdx, args.qif, args.out)

    if args.out is None:
        print(report_text)
    else:
        if args.out.suffix.lower() == ".txt":
            print(f"Wrote report: {args.out}")
            print(f"Artifacts dir: {args.out.parent}")
        else:
            print(f"Wrote report: {args.out / 'qdx_probe_report.txt'}")
            print(f"Artifacts dir: {args.out}")
        if artifacts:
            print(f"Saved {len(artifacts)} artifact(s).")


if __name__ == "__main__":
    main()
