# quicken_helper/gui_viewers/scaling.py
from __future__ import annotations

import os


def _safe_float(x, default):
    try:
        return float(x)
    except Exception:
        return default

def detect_system_font_scale(root) -> float:
    env_scale = os.environ.get("QIF_GUI_FONT_SCALE")
    if env_scale:
        val = _safe_float(env_scale, 1.0)
        return max(val, 0.5)

    scale_candidates = []
    try:
        tk_scaling = float(root.tk.call("tk", "scaling"))
        scale_candidates.append((tk_scaling * 72.0) / 96.0)
    except Exception:
        pass

    try:
        dpi = float(root.winfo_fpixels("1i"))
        scale_candidates.append(dpi / 96.0)
    except Exception:
        pass

    if not scale_candidates:
        return 1.0

    scale = max(1.0, max(scale_candidates))
    return max(0.75, min(scale, 3.0))

def apply_global_font_scaling(root, base_pt: int = 10, minimum_pt: int = 12):
    try:
        from tkinter import font as tkfont
    except Exception:
        return

    env_size = os.environ.get("QIF_GUI_FONT_SIZE")
    if env_size:
        try:
            target_pt = int(env_size)
        except Exception:
            target_pt = minimum_pt
    else:
        scale = detect_system_font_scale(root)
        target_pt = max(minimum_pt, int(round(base_pt * scale)))

    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkFixedFont"):
        try:
            f = tkfont.nametofont(name)
            f.configure(size=target_pt)
        except Exception:
            pass

    try:
        default = tkfont.nametofont("TkDefaultFont")
        root.option_add("*Font", default)
    except Exception:
        pass
