# qif_converter/qfx_to_txns.py
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

def _to_date(s: str) -> str:
    # ofx dates often like 20250115 or 20250115T120000
    if not s:
        return ""
    s = s.strip()
    # strip timezone offsets like "[0:GMT]"
    s = s.split("[", 1)[0]
    # pick YYYYMMDD part
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8:
        y, m, d = digits[:4], digits[4:6], digits[6:8]
        try:
            return datetime(int(y), int(m), int(d)).strftime("%m/%d/%Y")
        except Exception:
            pass
    return ""

def _tx(amount: float, payee: str = "", memo: str = "", date: str = "", checknum: str = "") -> Dict[str, Any]:
    # conform to your existing schema used in qif_to_csv paths
    return {
        "date": date,                  # "mm/dd/YYYY"
        "payee": payee or "",
        "amount": f"{amount:.2f}",
        "category": "",
        "memo": memo or "",
        "account": "",
        "checknum": checknum or "",
        "splits": [],
    }

def parse_qfx(path: Path | str) -> List[Dict[str, Any]]:
    """
    Parse a QFX/OFX file into the same txns dict schema as parse_qif().
    Prefers ofxparse if installed; falls back to a light SGML parser.
    """
    p = Path(path)
    raw = p.read_text(encoding="utf-8", errors="ignore")

    # --- try ofxparse first ---
    try:
        import ofxparse  # type: ignore
        with p.open("rb") as f:
            ofx = ofxparse.OfxParser.parse(f)
        out: List[Dict[str, Any]] = []
        for acct in ofx.accounts or []:
            for tr in acct.statement.transactions or []:
                amt = float(tr.amount or 0.0)
                payee = (tr.payee or tr.memo or "").strip()
                memo = (tr.memo or "").strip()
                date = _to_date(getattr(tr, "date", None).strftime("%Y%m%d") if getattr(tr, "date", None) else "")
                checknum = getattr(tr, "checknum", "") or ""
                out.append(_tx(amt, payee, memo, date, checknum))
        return out
    except Exception:
        pass  # fall through to minimal fallback

    # --- minimal fallback (SGML-ish tag scanning) ---
    # We’ll scan for <STMTTRN> blocks and pick child tags we care about.
    # This won’t cover every OFX variant, but handles common QFX exports.
    lower = raw.lower()
    out: List[Dict[str, Any]] = []
    start = 0
    while True:
        i = lower.find("<stmttrn>", start)
        if i == -1:
            break
        j = lower.find("</stmttrn>", i)
        if j == -1:
            break
        block = raw[i:j]
        def tagval(tag):
            # <TAG>value on same line OR <TAG>value</TAG>
            # do a simple search ignoring case
            t = tag.lower()
            k = block.lower().find(f"<{t}>")
            if k == -1:
                return ""
            k2 = k + len(t) + 2
            # read to end of line or next angle bracket
            end = block.find("<", k2)
            val = block[k2:end] if end != -1 else block[k2:]
            return val.strip()

        amount_s = tagval("TRNAMT")
        name = tagval("NAME")
        memo = tagval("MEMO")
        dtposted = tagval("DTPOSTED")
        checknum = tagval("CHECKNUM")

        try:
            amt = float(amount_s.replace(",", ""))
        except Exception:
            amt = 0.0
        out.append(_tx(amt, payee=name or memo, memo=memo, date=_to_date(dtposted), checknum=checknum))
        start = j + len("</stmttrn>")
    return out
