# quicken_helper/gui_viewers/probe_tab.py
from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Optional

from quicken_helper.gui_viewers.helpers import decode_best_effort
from quicken_helper.legacy import qdx_probe


class ProbeTab(ttk.Frame):
    """Primary function: Run QDX probe and preview artifacts."""

    def __init__(self, master, mb):
        super().__init__(master)
        self.mb = mb
        self._build()

    def _build(self):
        pad = {"padx": 8, "pady": 6}
        self.p_qdx = tk.StringVar()
        self.p_qif = tk.StringVar()
        self.p_out = tk.StringVar()

        files = ttk.LabelFrame(self, text="Files")
        files.pack(fill="x", **pad)
        ttk.Label(files, text="QDX file:").grid(row=0, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.p_qdx, width=90).grid(
            row=0, column=1, sticky="we", padx=5
        )
        ttk.Button(files, text="Browse…", command=self._p_browse_qdx).grid(
            row=0, column=2
        )
        ttk.Label(files, text="(Optional) QIF:").grid(row=1, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.p_qif, width=90).grid(
            row=1, column=1, sticky="we", padx=5
        )
        ttk.Button(files, text="Browse…", command=self._p_browse_qif).grid(
            row=1, column=2
        )
        ttk.Label(files, text="Output (dir or .txt):").grid(row=2, column=0, sticky="w")
        ttk.Entry(files, textvariable=self.p_out, width=90).grid(
            row=2, column=1, sticky="we", padx=5
        )
        ttk.Button(files, text="Browse…", command=self._p_browse_out).grid(
            row=2, column=2
        )
        files.columnconfigure(1, weight=1)

        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        ttk.Button(actions, text="Run Probe", command=self._p_run_probe).pack(
            side="left"
        )

        res = ttk.Frame(self)
        res.pack(fill="both", expand=True, **pad)
        left = ttk.LabelFrame(res, text="Report")
        left.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.p_report = tk.Text(left, wrap="word")
        self.p_report.pack(fill="both", expand=True, padx=4, pady=4)

        right = ttk.LabelFrame(res, text="Artifacts (decompressed blobs)")
        right.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.p_artifacts = tk.Listbox(right, exportselection=False)
        self.p_artifacts.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        btns = ttk.Frame(right)
        btns.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(btns, text="Preview", command=self._p_preview_artifact).pack(
            side="left"
        )
        ttk.Button(
            btns, text="Open Containing Folder", command=self._p_open_artifact_folder
        ).pack(side="left", padx=6)

        prev = ttk.LabelFrame(right, text="Artifact Preview")
        prev.pack(fill="both", expand=False, padx=4, pady=(0, 4))
        self.p_preview = tk.Text(prev, height=12, wrap="word")
        self.p_preview.pack(fill="both", expand=True, padx=4, pady=4)
        self.p_artifacts.bind("<Double-Button-1>", lambda e: self._p_preview_artifact())

    # pickers
    def _p_browse_qdx(self):
        p = filedialog.askopenfilename(
            title="Select QDX file",
            filetypes=[("QDX files", "*.qdx"), ("All files", "*.*")],
        )
        if p:
            self.p_qdx.set(p)

    def _p_browse_qif(self):
        p = filedialog.askopenfilename(
            title="Select QIF (optional)",
            filetypes=[("QIF files", "*.qif"), ("All files", "*.*")],
        )
        if p:
            self.p_qif.set(p)

    def _p_browse_out(self):
        p = filedialog.asksaveasfilename(
            title="Select output report (.txt) or choose a folder in the dialog",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if p:
            self.p_out.set(p)

    # actions
    def _p_run_probe(self):
        try:
            qdx = Path(self.p_qdx.get().strip())
            if not qdx.exists():
                self.mb.showerror("Error", "Please pick a valid QDX file.")
                return
            qif = Path(self.p_qif.get().strip()) if self.p_qif.get().strip() else None
            out = Path(self.p_out.get().strip()) if self.p_out.get().strip() else None

            report, artifacts = qdx_probe.run_probe(qdx, qif, out)
            self.p_report.delete("1.0", "end")
            self.p_report.insert("end", report)
            self.p_artifacts.delete(0, "end")
            for a in artifacts:
                self.p_artifacts.insert("end", str(a))
            self.mb.showinfo("QDX Probe", "Probe completed.")
        except Exception as e:
            self.mb.showerror("Error", str(e))

    def _p_selected_artifact(self) -> Optional[Path]:
        sel = self.p_artifacts.curselection()
        if not sel:
            return None
        try:
            return Path(self.p_artifacts.get(sel[0]))
        except Exception:
            return None

    def _p_open_artifact_folder(self):
        p = self._p_selected_artifact()
        if not p:
            self.mb.showinfo("Info", "Select an artifact first.")
            return
        folder = p.parent
        try:
            if sys.platform.startswith("win"):  # type: ignore[attr-defined]
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            self.mb.showerror("Error", f"Could not open folder:\n{e}")

    def _p_preview_artifact(self):
        p = self._p_selected_artifact()
        if not p or not p.exists():
            self.mb.showinfo("Info", "Select an existing artifact to preview.")
            return
        try:
            data = p.read_bytes()
        except Exception as e:
            self.mb.showerror("Error", f"Failed to read artifact:\n{e}")
            return

        text = decode_best_effort(data)
        if text is None:
            chunk = data[:4096]
            hexed = chunk.hex()
            grouped = " ".join(hexed[i : i + 2] for i in range(0, len(hexed), 2))
            text = (
                f"[binary data] showing first {len(chunk)} bytes as hex:\n\n{grouped}"
            )
        self.p_preview.delete("1.0", "end")
        self.p_preview.insert("end", text)
