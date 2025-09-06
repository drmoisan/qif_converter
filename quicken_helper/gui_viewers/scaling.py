# quicken_helper/gui_viewers/scaling.py
from __future__ import annotations

import os
import sys
from typing import Any


def detect_system_font_scale(default: float = 1.0) -> float:
    """Return the OS/UI font scaling factor as a float (1.0 = 100%).

    Strategy:
    • Windows: try User32.GetDpiForSystem → fallback to GetDeviceCaps(LOGPIXELSX) → fallback to registry.
    • macOS: use AppKit.NSScreen.backingScaleFactor (e.g., 2.0 for Retina).
    • Linux/Unix: honor common env vars (GDK_SCALE, GDK_DPI_SCALE, QT_SCALE_FACTOR).
    • On any failure, return `default`.

    Notes:
    • Windows DPI base is 96; scale = dpi / 96.0.
    • Linux GDK uses two knobs: GDK_SCALE (integer pixel scaling) and GDK_DPI_SCALE (additional font DPI scaling).
      Effective scale ~ GDK_SCALE * GDK_DPI_SCALE (when both are present).
    """
    # ---- Windows ----
    if sys.platform.startswith("win"):
        try:
            import ctypes  # type: ignore

            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            try:
                # Windows 10+ (1607): preferred
                dpi = user32.GetDpiForSystem()  # type: ignore[attr-defined]
                if isinstance(dpi, int) and dpi > 0:
                    return max(0.5, min(4.0, dpi / 96.0))
            except AttributeError:
                # Older Windows: use GetDeviceCaps
                hdc = user32.GetDC(0)
                if hdc:
                    try:
                        gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
                        LOGPIXELSX = 88
                        dpi = gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
                        if isinstance(dpi, int) and dpi > 0:
                            return max(0.5, min(4.0, dpi / 96.0))
                    finally:
                        user32.ReleaseDC(0, hdc)
            # Registry fallback
            try:
                import winreg  # type: ignore

                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop"
                ) as k:
                    for name in ("LogPixels", "AppliedDPI"):
                        try:
                            val, _ = winreg.QueryValueEx(k, name)
                            if isinstance(val, int) and val > 0:
                                return max(0.5, min(4.0, float(val) / 96.0))
                        except FileNotFoundError:
                            pass
            except Exception:
                pass
        except Exception:
            pass

    # ---- macOS ----
    if sys.platform == "darwin":
        try:
            # AppKit is available when running with a GUI session
            from AppKit import NSScreen  # type: ignore

            screen = NSScreen.mainScreen() or (NSScreen.screens()[0] if NSScreen.screens() else None)  # type: ignore
            if screen is not None:
                scale = screen.backingScaleFactor()  # type: ignore[attr-defined]
                if isinstance(scale, (int, float)) and scale > 0:
                    return float(scale)
        except Exception:
            pass

    # ---- Linux / Unix ----
    try:
        # GDK: pixel scale (integer on many systems)
        gdk_scale = os.environ.get("GDK_SCALE")
        # GDK_DPI_SCALE: additional font/dpi scaling (float)
        gdk_dpi_scale = os.environ.get("GDK_DPI_SCALE")
        # Qt: unified scale factor
        qt_scale = os.environ.get("QT_SCALE_FACTOR")

        scale = 1.0
        if gdk_scale:
            try:
                scale *= float(gdk_scale)
            except ValueError:
                pass
        if gdk_dpi_scale:
            try:
                scale *= float(gdk_dpi_scale)
            except ValueError:
                pass
        if qt_scale:
            try:
                # If Qt is present, it often represents the effective scale; prefer the larger signal.
                scale = max(scale, float(qt_scale))
            except ValueError:
                pass

        if scale > 0:
            return max(0.5, min(4.0, scale))
    except Exception:
        pass

    return default


def apply_global_font_scaling(root: Any, scale: float) -> None:
    """Apply a global UI font scale to a Tkinter app.

    This function is idempotent:
    - On first call, it records each standard Tk named font's *base* size.
    - On subsequent calls, it scales from the recorded base (not cumulatively).

    Behavior:
    - Sets Tk's pixel-per-point scaling: ``tk scaling <scale>``.
    - Rescales standard named fonts (if present): TkDefaultFont, TkTextFont, TkFixedFont,
      TkMenuFont, TkHeadingFont, TkCaptionFont, TkSmallCaptionFont, TkIconFont, TkTooltipFont.
    - Protects against invalid scales; clamps to [0.5, 4.0].
    - Safe no-ops if Tkinter is unavailable or ``root`` lacks expected attributes.

    Parameters
    ----------
    root : Any
        A ``tk.Tk`` (or object exposing ``.tk`` and Tkinter font APIs).
    scale : float
        Desired scale where 1.0 = 100%, 1.25 = 125%, etc.
    """
    try:
        # Import inside the function so this module can be imported headlessly.
        from tkinter import font as tkfont  # type: ignore
    except Exception:
        return  # Headless environment or Tk not installed

    # Validate & clamp
    try:
        s = float(scale)
    except Exception:
        return
    s = max(0.5, min(4.0, s))

    # 1) Apply Tk's global scaling (affects point-sized fonts)
    try:
        # Equivalent to: tk.call('tk', 'scaling', s)
        root.tk.call("tk", "scaling", s)  # type: ignore[attr-defined]
    except Exception:
        pass  # Not fatal; continue with manual font scaling

    # 2) Scale standard named fonts deterministically (idempotent)
    try:
        # Names that Tk commonly defines; not all are guaranteed in every build.
        standard_font_names = [
            "TkDefaultFont",
            "TkTextFont",
            "TkFixedFont",
            "TkMenuFont",
            "TkHeadingFont",
            "TkCaptionFont",
            "TkSmallCaptionFont",
            "TkIconFont",
            "TkTooltipFont",
        ]

        # Record base sizes (first run) and re-use them later.
        # Stored on the root object to avoid module-global state.
        base_key = "_qh_base_font_sizes"
        base_sizes: dict[str, int] = getattr(root, base_key, {})  # type: ignore[assignment]

        # Discover which named fonts actually exist
        try:
            existing_names = set(tkfont.names())  # type: ignore[arg-type]
        except Exception:
            existing_names = set()  # type: ignore[assignment]

        for name in standard_font_names:
            if name not in existing_names:
                continue
            try:
                f = tkfont.nametofont(name)  # type: ignore[call-arg]
            except Exception:
                continue

            # Tk font size is int; positive means points, negative means pixels (absolute).
            try:
                size_obj = f.cget("size")  # type: ignore[call-arg]
            except Exception:
                continue

            if size_obj == 0:
                # Unknown or zero size — skip to avoid surprises.
                continue

            # Persist original base size the first time we see this font.
            if name not in base_sizes:
                base_sizes[name] = size_obj

            base = base_sizes[name]

            # Maintain sign semantics: negative = pixels, positive = points.
            sign = -1 if base < 0 else 1
            abs_base = abs(base)

            # Compute new size from the *base*, not from the current value (idempotent).
            new_abs_size = max(6, int(round(abs_base * s)))
            new_size = sign * new_abs_size

            try:
                f.configure(size=new_size)  # type: ignore[call-arg]
            except Exception:
                # Ignore individual font failures; continue with others.
                pass

        # Save (or update) base sizes on the root so future calls remain idempotent.
        try:
            setattr(root, base_key, base_sizes)
        except Exception:
            pass
    except Exception:
        # A failure here shouldn't crash the app.
        pass
