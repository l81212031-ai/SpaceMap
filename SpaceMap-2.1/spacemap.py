import csv
import html
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime
from collections import deque

APP_NAME = "SpaceMap"
VERSION = "2.1"
BG = "#F3F6FB"
CARD = "#FFFFFF"
TEXT = "#1E293B"
MUTED = "#718096"
ACCENT = "#3478F6"
BORDER = "#E3EAF3"
PALETTE = [
    "#3478F6", "#18A889", "#F2A65A", "#8B72E8",
    "#D96B9B", "#36A6C5", "#8BAF45", "#C98563",
    "#668FE0", "#A17BC7", "#D1A33D", "#5AABB0"
]


def format_size(value):
    value = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1024 or unit == "PB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return "0 B"


def modified_text(timestamp):
    try:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "—"


def available_drives():
    drives = []
    if hasattr(os, "listdrives"):
        try:
            drives = list(os.listdrives())
        except OSError:
            pass
    if not drives and os.name == "nt":
        drives = [f"{letter}:\\" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  if os.path.exists(f"{letter}:\\")]
    if not drives:
        drives = [os.path.abspath(os.sep)]
    return drives


def scan_directory(start_path, cancel_event=None):
    """Build a read-only directory tree and return scan statistics.

    Symbolic links are skipped to avoid cycles and scanning outside the chosen
    directory. Permission and filesystem errors are counted rather than fatal.
    Returns None when cancellation is requested.
    """
    start_path = os.path.abspath(os.path.expanduser(start_path))
    if not os.path.isdir(start_path):
        raise NotADirectoryError(start_path)

    root = {
        "name": os.path.basename(os.path.normpath(start_path)) or start_path,
        "path": start_path, "size": 0, "is_dir": True,
        "modified": 0, "children": []
    }
    nodes = {start_path: root}
    files = []
    errors = 0
    file_count = 0
    folder_count = 0
    stack = [root]
    visited = 0

    while stack:
        if cancel_event is not None and cancel_event.is_set():
            return None

        node = stack.pop()
        try:
            with os.scandir(node["path"]) as entries:
                for entry in entries:
                    if cancel_event is not None and cancel_event.is_set():
                        return None
                    try:
                        if entry.is_symlink():
                            continue
                        info = entry.stat(follow_symlinks=False)
                        if entry.is_dir(follow_symlinks=False):
                            child = {
                                "name": entry.name, "path": entry.path,
                                "size": 0, "is_dir": True,
                                "modified": info.st_mtime, "children": []
                            }
                            node["children"].append(child)
                            nodes[entry.path] = child
                            stack.append(child)
                            folder_count += 1
                        elif entry.is_file(follow_symlinks=False):
                            child = {
                                "name": entry.name, "path": entry.path,
                                "size": info.st_size, "is_dir": False,
                                "modified": info.st_mtime, "children": []
                            }
                            node["children"].append(child)
                            files.append(child)
                            file_count += 1
                        else:
                            continue
                        visited += 1
                    except (PermissionError, OSError):
                        errors += 1
        except (PermissionError, OSError):
            errors += 1

    # Child directories are processed before their parents, so each folder's
    # size can be calculated from its immediate children in reverse depth order.
    ordered_nodes = sorted(
        nodes.values(),
        key=lambda item: item["path"].count(os.sep),
        reverse=True
    )
    for node in ordered_nodes:
        node["size"] = sum(child["size"] for child in node["children"])

    files.sort(key=lambda item: item["size"], reverse=True)
    return {
        "root": root, "nodes": nodes, "files": files,
        "file_count": file_count, "folder_count": folder_count,
        "errors": errors, "visited": visited, "path": start_path
    }


class SpaceMapApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} | {VERSION}")
        self.root.geometry("1280x820")
        self.root.minsize(980, 650)

        self.events = queue.Queue()
        self.scan_thread = None
        self.cancel_event = threading.Event()
        self.scanning = False
        self.scan_started = 0.0

        self.root_node = None
        self.nodes = {}
        self.files = []
        self.current_path = None
        self.selected_item = None
        self.last_scan_path = None
        self.scan_errors = 0
        self.total_size = 0
        self.file_count = 0
        self.folder_count = 0
        self.map_items = []

        self.theme_name = "light"
        self.colors = {}
        self.search_var = tk.StringVar()
        self.path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready — choose a folder or drive to begin.")
        self.drive_var = tk.StringVar()
        self.sort_var = tk.StringVar(value="Largest first")

        self._configure_theme()
        self._configure_style()
        self._build_layout()
        self._refresh_drives()
        self._poll_events()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- Theme and layout ----------

    def _configure_theme(self):
        if self.theme_name == "light":
            self.colors = {
                "bg": "#F3F6FB", "card": "#FFFFFF", "text": "#1E293B",
                "muted": "#718096", "accent": "#3478F6",
                "border": "#E3EAF3", "soft": "#EAF1FF",
                "hover": "#F4F7FC", "selected": "#E5EEFF",
                "tree_bg": "#FFFFFF", "status": "#EAF0F8"
            }
        else:
            self.colors = {
                "bg": "#111827", "card": "#1F2937", "text": "#F1F5F9",
                "muted": "#A0AEC0", "accent": "#70A5FF",
                "border": "#374151", "soft": "#263B5C",
                "hover": "#293548", "selected": "#304A70",
                "tree_bg": "#1F2937", "status": "#1B2637"
            }
        self.root.configure(bg=self.colors["bg"])

    def _configure_style(self):
        c = self.colors
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Treeview", background=c["tree_bg"], fieldbackground=c["tree_bg"],
            foreground=c["text"], rowheight=31, borderwidth=0,
            font=("Segoe UI", 9)
        )
        style.configure(
            "Treeview.Heading", background=c["soft"], foreground=c["text"],
            relief="flat", font=("Segoe UI", 9, "bold"), padding=(8, 8)
        )
        style.map(
            "Treeview",
            background=[("selected", c["selected"])],
            foreground=[("selected", c["text"])]
        )
        style.configure(
            "TCombobox", fieldbackground=c["card"], background=c["card"],
            foreground=c["text"], arrowcolor=c["text"], padding=5
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=c["soft"], background=c["accent"], bordercolor=c["soft"]
        )

    def _card(self, parent, **kwargs):
        return tk.Frame(
            parent, bg=self.colors["card"],
            highlightthickness=1, highlightbackground=self.colors["border"],
            **kwargs
        )

    def _label(self, parent, text, size=10, bold=False, color=None, **kwargs):
        return tk.Label(
            parent, text=text, bg=self.colors["card"],
            fg=color or self.colors["text"],
            font=("Segoe UI", size, "bold" if bold else "normal"),
            **kwargs
        )

    def _button(self, parent, text, command, primary=False, **kwargs):
        bg = self.colors["accent"] if primary else self.colors["card"]
        fg = "#FFFFFF" if primary else self.colors["text"]
        return tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg,
            activebackground=self.colors["soft"], activeforeground=self.colors["text"],
            relief="flat", bd=0, padx=13, pady=8,
            font=("Segoe UI", 9, "bold" if primary else "normal"),
            cursor="hand2", **kwargs
        )

    def _build_layout(self):
        c = self.colors

        header = tk.Frame(self.root, bg=c["card"], height=76)
        header.pack(fill="x")
        header.pack_propagate(False)

        brand = tk.Frame(header, bg=c["card"])
        brand.pack(side="left", padx=24, pady=12)
        tk.Label(
            brand, text="◈", bg=c["card"], fg=c["accent"],
            font=("Segoe UI Symbol", 26, "bold")
        ).pack(side="left", padx=(0, 10))
        titlebox = tk.Frame(brand, bg=c["card"])
        titlebox.pack(side="left")
        self._label(titlebox, "SpaceMap", 19, True).pack(anchor="w")
        self._label(titlebox, "ULTIMATE  •  STORAGE ANALYZER", 8, True,
                    c["muted"]).pack(anchor="w")

        self.theme_button = self._button(
            header, "☾  Dark mode", self._toggle_theme
        )
        self.theme_button.pack(side="right", padx=22, pady=18)

        body = tk.Frame(self.root, bg=c["bg"])
        body.pack(fill="both", expand=True, padx=20, pady=16)

        # Location and actions
        top = self._card(body)
        top.pack(fill="x", pady=(0, 13))
        row = tk.Frame(top, bg=c["card"])
        row.pack(fill="x", padx=13, pady=12)

        self.drive_combo = ttk.Combobox(
            row, textvariable=self.drive_var, width=10,
            values=available_drives(), state="readonly"
        )
        self.drive_combo.pack(side="left", padx=(0, 8))
        self._button(row, "Select drive", self._select_drive).pack(side="left", padx=(0, 8))
        self.path_entry = tk.Entry(
            row, textvariable=self.path_var, bg=c["tree_bg"], fg=c["text"],
            insertbackground=c["text"], relief="flat",
            highlightthickness=1, highlightbackground=c["border"],
            font=("Segoe UI", 10)
        )
        self.path_entry.pack(side="left", fill="x", expand=True, ipady=8, padx=4)
        self._button(row, "Browse…", self._browse).pack(side="left", padx=6)
        self.scan_button = self._button(row, "Scan folder", self._start_scan, True)
        self.scan_button.pack(side="left", padx=(4, 0))

        # Summary cards
        summary = tk.Frame(body, bg=c["bg"])
        summary.pack(fill="x", pady=(0, 13))
        self.stat_total = self._stat_card(summary, "TOTAL SIZE", "—", "Selected folder")
        self.stat_files = self._stat_card(summary, "FILES", "—", "Files discovered")
        self.stat_folders = self._stat_card(summary, "FOLDERS", "—", "Folders discovered")
        self.stat_duration = self._stat_card(summary, "SCAN TIME", "—", "Elapsed time")

        # Navigation / search
        toolbar = self._card(body)
        toolbar.pack(fill="x", pady=(0, 13))
        tr = tk.Frame(toolbar, bg=c["card"])
        tr.pack(fill="x", padx=12, pady=9)

        self.back_button = self._button(tr, "← Back", self._go_back)
        self.back_button.pack(side="left", padx=(0, 5))
        self.up_button = self._button(tr, "↑ Up", self._go_up)
        self.up_button.pack(side="left", padx=5)
        self.home_button = self._button(tr, "⌂ Root", self._go_root)
        self.home_button.pack(side="left", padx=5)

        self.breadcrumb = self._label(tr, "No folder scanned", 9, color=c["muted"])
        self.breadcrumb.pack(side="left", padx=14)

        self.search_entry = tk.Entry(
            tr, textvariable=self.search_var, bg=c["tree_bg"], fg=c["text"],
            insertbackground=c["text"], relief="flat",
            highlightthickness=1, highlightbackground=c["border"],
            font=("Segoe UI", 9), width=23
        )
        self.search_entry.pack(side="right", ipady=6, padx=(6, 0))
        self.search_entry.bind("<Return>", lambda e: self._apply_search())
        self._button(tr, "Search", self._apply_search).pack(side="right", padx=5)
        self.sort_combo = ttk.Combobox(
            tr, textvariable=self.sort_var, width=15, state="readonly",
            values=("Largest first", "Smallest first", "Name A–Z", "Name Z–A")
        )
        self.sort_combo.pack(side="right", padx=5)
        self.sort_combo.bind("<<ComboboxSelected>>", lambda e: self._refresh_table())

        # Main panels
        panels = tk.Frame(body, bg=c["bg"])
        panels.pack(fill="both", expand=True)

        left = self._card(panels)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        left_header = tk.Frame(left, bg=c["card"])
        left_header.pack(fill="x", padx=14, pady=(12, 4))
        self._label(left_header, "Storage map", 12, True).pack(side="left")
        self._label(left_header, "Select a block to inspect it", 8,
                    color=c["muted"]).pack(side="right")

        self.map_canvas = tk.Canvas(
            left, bg=c["card"], highlightthickness=0, height=235
        )
        self.map_canvas.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.map_canvas.bind("<Configure>", lambda e: self._draw_map())
        self.map_canvas.bind("<Button-1>", self._map_click)

        right = self._card(panels)
        right.pack(side="right", fill="both", expand=True, padx=(8, 0))
        right_header = tk.Frame(right, bg=c["card"])
        right_header.pack(fill="x", padx=14, pady=(12, 5))
        self._label(right_header, "Folder contents", 12, True).pack(side="left")
        self._label(right_header, "Double-click a folder to open", 8,
                    color=c["muted"]).pack(side="right")

        table_frame = tk.Frame(right, bg=c["card"])
        table_frame.pack(fill="both", expand=True, padx=10, pady=(3, 10))
        columns = ("name", "kind", "size", "modified")
        self.table = ttk.Treeview(
            table_frame, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "name": ("Name", 220, "w"),
            "kind": ("Type", 75, "center"),
            "size": ("Size", 95, "e"),
            "modified": ("Modified", 125, "center")
        }
        for key, (heading, width, anchor) in headings.items():
            self.table.heading(key, text=heading)
            self.table.column(key, width=width, anchor=anchor, stretch=(key == "name"))
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=yscroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        self.table.bind("<Double-1>", self._table_double_click)
        self.table.bind("<<TreeviewSelect>>", self._table_select)
        self.table.bind("<Button-3>", self._context_menu)

        # Details strip
        details = self._card(body)
        details.pack(fill="x", pady=(13, 0))
        self.details_var = tk.StringVar(
            value="Select a file or folder to view its details."
        )
        tk.Label(
            details, textvariable=self.details_var, bg=c["card"],
            fg=c["muted"], anchor="w", font=("Segoe UI", 9),
            padx=13, pady=9
        ).pack(fill="x")

        # Footer and progress
        footer = tk.Frame(self.root, bg=c["status"])
        footer.pack(fill="x", side="bottom")
        self.status_label = tk.Label(
            footer, textvariable=self.status_var, bg=c["status"],
            fg=c["muted"], anchor="w", padx=16, pady=8,
            font=("Segoe UI", 9)
        )
        self.status_label.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(
            footer, mode="indeterminate", length=150
        )
        self.progress.pack(side="right", padx=14, pady=7)
        self._draw_map()

    def _stat_card(self, parent, heading, value, subtitle):
        card = self._card(parent)
        card.pack(side="left", fill="x", expand=True, padx=4)
        inner = tk.Frame(card, bg=self.colors["card"])
        inner.pack(fill="both", padx=13, pady=10)
        self._label(inner, heading, 8, True, self.colors["muted"]).pack(anchor="w")
        value_label = self._label(inner, value, 17, True)
        value_label.pack(anchor="w", pady=(3, 0))
        self._label(inner, subtitle, 8, color=self.colors["muted"]).pack(anchor="w")
        return value_label

    # ---------- Scanning ----------

    def _refresh_drives(self):
        drives = available_drives()
        self.drive_combo["values"] = drives
        if drives and not self.drive_var.get():
            self.drive_var.set(drives[0])

    def _select_drive(self):
        drive = self.drive_var.get()
        if drive:
            self.path_var.set(drive)

    def _browse(self):
        folder = filedialog.askdirectory(title="Choose a folder to analyze")
        if folder:
            self.path_var.set(folder)

    def _start_scan(self):
        if self.scanning:
            self.cancel_event.set()
            self.status_var.set("Stopping scan safely…")
            return

        path = os.path.abspath(os.path.expanduser(self.path_var.get().strip()))
        if not os.path.isdir(path):
            messagebox.showerror("Invalid folder", "Choose an existing folder first.")
            return

        self.cancel_event.clear()
        self.scanning = True
        self.scan_started = time.time()
        self.scan_button.config(text="Cancel scan", command=self._start_scan)
        self.status_var.set("Scanning… this may take a while for large drives.")
        self.progress.start(10)
        self.scan_errors = 0

        self.scan_thread = threading.Thread(
            target=self._scan_worker, args=(path,), daemon=True
        )
        self.scan_thread.start()

    def _scan_worker(self, start_path):
        try:
            result = scan_directory(start_path, self.cancel_event)
        except Exception as exc:
            self.events.put(("failed", str(exc)))
            return
        if result is None:
            self.events.put(("cancelled", None))
        else:
            self.events.put(("complete", result))

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    visited, files, folders = payload
                    self.status_var.set(
                        f"Scanning… {visited:,} items checked | "
                        f"{files:,} files | {folders:,} folders"
                    )
                elif kind == "cancelled":
                    self._finish_scan_controls()
                    self.status_var.set("Scan cancelled. No files were changed.")
                elif kind == "complete":
                    self._finish_scan_controls()
                    self._accept_scan(payload)
                elif kind == "failed":
                    self._finish_scan_controls()
                    self.status_var.set("Scan failed.")
                    messagebox.showerror("Scan failed", payload)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_events)

    def _finish_scan_controls(self):
        self.scanning = False
        self.progress.stop()
        self.scan_button.config(text="Scan folder", command=self._start_scan)

    def _accept_scan(self, result):
        self.root_node = result["root"]
        self.nodes = result["nodes"]
        self.files = result["files"]
        self.file_count = result["file_count"]
        self.folder_count = result["folder_count"]
        self.scan_errors = result["errors"]
        self.total_size = self.root_node["size"]
        self.last_scan_path = result["path"]
        self.current_path = result["path"]
        elapsed = time.time() - self.scan_started

        self.stat_total.config(text=format_size(self.total_size))
        self.stat_files.config(text=f"{self.file_count:,}")
        self.stat_folders.config(text=f"{self.folder_count:,}")
        self.stat_duration.config(text=f"{elapsed:.1f}s")

        self._refresh_table()
        self._draw_map()
        self._update_breadcrumb()
        self.status_var.set(
            f"Scan complete | {self.file_count:,} files | "
            f"{self.folder_count:,} folders | {self.scan_errors:,} inaccessible items"
        )

    # ---------- Folder navigation and table ----------

    def _current_node(self):
        return self.nodes.get(self.current_path) if self.current_path else None

    def _update_breadcrumb(self):
        path = self.current_path or "No folder scanned"
        self.breadcrumb.config(text=path)

    def _go_root(self):
        if self.root_node:
            self.current_path = self.root_node["path"]
            self._refresh_table()
            self._draw_map()
            self._update_breadcrumb()

    def _go_up(self):
        if not self.current_path or not self.root_node:
            return
        parent = os.path.dirname(self.current_path.rstrip(os.sep))
        if parent and (parent == self.root_node["path"] or
                       parent.startswith(self.root_node["path"].rstrip(os.sep) + os.sep)):
            self.current_path = parent
            self._refresh_table()
            self._draw_map()
            self._update_breadcrumb()

    def _go_back(self):
        self._go_up()

    def _apply_search(self):
        self._refresh_table()

    def _visible_children(self):
        node = self._current_node()
        if not node:
            return []
        items = list(node["children"])
        query = self.search_var.get().strip().casefold()
        if query:
            items = [item for item in items if query in item["name"].casefold()]
        mode = self.sort_var.get()
        if mode == "Largest first":
            items.sort(key=lambda x: x["size"], reverse=True)
        elif mode == "Smallest first":
            items.sort(key=lambda x: x["size"])
        elif mode == "Name A–Z":
            items.sort(key=lambda x: x["name"].casefold())
        elif mode == "Name Z–A":
            items.sort(key=lambda x: x["name"].casefold(), reverse=True)
        return items

    def _refresh_table(self):
        self.table.delete(*self.table.get_children())
        for item in self._visible_children():
            kind = "Folder" if item["is_dir"] else self._file_type(item["name"])
            size = format_size(item["size"])
            self.table.insert(
                "", "end", iid=item["path"],
                values=(item["name"], kind, size, modified_text(item["modified"]))
            )
        self._update_breadcrumb()

    @staticmethod
    def _file_type(name):
        ext = os.path.splitext(name)[1].lower()
        return (ext[1:].upper() if ext else "File")[:12]

    def _table_select(self, _event=None):
        selection = self.table.selection()
        if not selection:
            return
        path = selection[0]
        item = self.nodes.get(path)
        if item is None:
            item = next((f for f in self.files if f["path"] == path), None)
        if item:
            self.selected_item = item
            kind = "Folder" if item["is_dir"] else self._file_type(item["name"])
            self.details_var.set(
                f"{item['name']}   •   {kind}   •   {format_size(item['size'])}   •   "
                f"{item['path']}"
            )

    def _table_double_click(self, event):
        row_id = self.table.identify_row(event.y)
        if not row_id:
            return
        item = self.nodes.get(row_id)
        if item and item["is_dir"]:
            self.current_path = item["path"]
            self.search_var.set("")
            self._refresh_table()
            self._draw_map()
        elif os.path.isfile(row_id):
            self._open_in_explorer(row_id)

    # ---------- Treemap ----------

    def _draw_map(self):
        canvas = self.map_canvas
        canvas.delete("all")
        self.map_items = []
        width = max(canvas.winfo_width(), 100)
        height = max(canvas.winfo_height(), 100)
        node = self._current_node()

        if not node:
            canvas.create_text(
                width / 2, height / 2,
                text="Choose a folder and click  Scan folder",
                fill=self.colors["muted"], font=("Segoe UI", 11)
            )
            return

        items = [item for item in node["children"] if item["size"] > 0]
        items.sort(key=lambda x: x["size"], reverse=True)
        if not items:
            canvas.create_text(
                width / 2, height / 2, text="This folder is empty or inaccessible",
                fill=self.colors["muted"], font=("Segoe UI", 11)
            )
            return

        # Keep the overview readable; small entries are grouped into "Other".
        if len(items) > 36:
            keep = items[:35]
            rest = items[35:]
            keep.append({
                "name": f"Other ({len(rest)} items)",
                "path": None, "size": sum(x["size"] for x in rest),
                "is_dir": False, "modified": 0, "children": [],
                "group": rest
            })
            items = keep

        self._draw_treemap_items(items, 5, 5, width - 10, height - 10, 0)

    def _draw_treemap_items(self, items, x, y, w, h, depth):
        if not items or w < 2 or h < 2:
            return
        if len(items) == 1:
            item = items[0]
            color = PALETTE[depth % len(PALETTE)]
            rect = self.map_canvas.create_rectangle(
                x, y, x + w, y + h, fill=color,
                outline=self.colors["card"], width=2
            )
            self.map_items.append((rect, item))
            if w > 75 and h > 30:
                label = item["name"]
                if len(label) > max(8, int(w / 8)):
                    label = label[:max(5, int(w / 8) - 2)] + "…"
                self.map_canvas.create_text(
                    x + 8, y + 8, text=label, anchor="nw",
                    fill="white", font=("Segoe UI", 9, "bold")
                )
            if w > 100 and h > 52:
                self.map_canvas.create_text(
                    x + 8, y + 27, text=format_size(item["size"]),
                    anchor="nw", fill="white", font=("Segoe UI", 8)
                )
            return

        total = sum(max(0, item["size"]) for item in items)
        if total <= 0:
            return
        half = total / 2
        group_a, group_b, running = [], [], 0
        for item in items:
            if running < half or not group_a:
                group_a.append(item)
                running += item["size"]
            else:
                group_b.append(item)
        if not group_b:
            group_b = [group_a.pop()]
        ratio = sum(item["size"] for item in group_a) / total
        ratio = min(max(ratio, 0.08), 0.92)
        if w >= h:
            split = w * ratio
            self._draw_treemap_items(group_a, x, y, split, h, depth + 1)
            self._draw_treemap_items(group_b, x + split, y, w - split, h, depth + 1)
        else:
            split = h * ratio
            self._draw_treemap_items(group_a, x, y, w, split, depth + 1)
            self._draw_treemap_items(group_b, x, y + split, w, h - split, depth + 1)

    def _map_click(self, event):
        for rect, item in reversed(self.map_items):
            coords = self.map_canvas.coords(rect)
            if len(coords) == 4:
                x1, y1, x2, y2 = coords
                if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                    if item.get("group") is not None:
                        self.details_var.set(
                            f"{len(item['group'])} smaller items grouped together • "
                            f"Total: {format_size(item['size'])}"
                        )
                    elif item["is_dir"]:
                        self.current_path = item["path"]
                        self.search_var.set("")
                        self._refresh_table()
                        self._draw_map()
                    else:
                        self.details_var.set(
                            f"{item['name']} • {format_size(item['size'])} • {item['path']}"
                        )
                    return

    # ---------- File actions and exports ----------

    def _open_in_explorer(self, path):
        try:
            if os.name == "nt":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except (OSError, AttributeError) as exc:
            messagebox.showerror("Could not open", str(exc))

    def _show_in_folder(self, path):
        try:
            if os.name == "nt":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                self._open_in_explorer(os.path.dirname(path))
        except OSError as exc:
            messagebox.showerror("Could not open folder", str(exc))

    def _context_menu(self, event):
        row = self.table.identify_row(event.y)
        if not row:
            return
        self.table.selection_set(row)
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Open", command=lambda: self._open_selected(row))
        menu.add_command(label="Show in folder", command=lambda: self._show_in_folder(row))
        menu.add_command(label="Copy full path", command=lambda: self._copy_path(row))
        menu.tk_popup(event.x_root, event.y_root)

    def _open_selected(self, path):
        item = self.nodes.get(path)
        if item and item["is_dir"]:
            self.current_path = path
            self._refresh_table()
            self._draw_map()
        elif os.path.isfile(path):
            self._open_in_explorer(path)

    def _copy_path(self, path):
        self.root.clipboard_clear()
        self.root.clipboard_append(path)
        self.status_var.set("Full path copied to clipboard.")

    def _export_csv(self):
        if not self.files and not self.root_node:
            messagebox.showinfo("Nothing to export", "Run a scan first.")
            return
        path = filedialog.asksaveasfilename(
            title="Export file report", defaultextension=".csv",
            filetypes=[("CSV file", "*.csv")]
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as file:
                writer = csv.writer(file)
                writer.writerow(["Name", "Full path", "Type", "Size (bytes)", "Modified"])
                for item in self.files:
                    writer.writerow([
                        item["name"], item["path"], self._file_type(item["name"]),
                        item["size"], modified_text(item["modified"])
                    ])
            self.status_var.set(f"CSV report exported: {path}")
            messagebox.showinfo("Export complete", "CSV report saved successfully.")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    def _export_html(self):
        if not self.root_node:
            messagebox.showinfo("Nothing to export", "Run a scan first.")
            return
        path = filedialog.asksaveasfilename(
            title="Export HTML summary", defaultextension=".html",
            filetypes=[("HTML file", "*.html")]
        )
        if not path:
            return
        try:
            rows = []
            for item in self.files[:5000]:
                rows.append(
                    "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                        html.escape(item["name"]),
                        html.escape(item["path"]),
                        format_size(item["size"])
                    )
                )
            page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SpaceMap Report</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;background:#f3f6fb;color:#1e293b;
margin:40px}main{max-width:1100px;margin:auto;background:white;padding:28px;
border-radius:16px}h1{color:#3478f6} .stats{display:flex;gap:14px;flex-wrap:wrap}
.card{background:#edf3ff;padding:16px;border-radius:10px;min-width:150px}
table{width:100%;border-collapse:collapse;margin-top:24px}
th,td{text-align:left;padding:10px;border-bottom:1px solid #e3eaf3}
th{background:#edf3ff}small{color:#718096}
</style></head><body><main>
<h1>SpaceMap Report</h1><small>Generated {generated}</small>
<p>Scanned location: <b>{root}</b></p>
<div class="stats">
<div class="card">Total size<br><b>{total}</b></div>
<div class="card">Files<br><b>{files}</b></div>
<div class="card">Folders<br><b>{folders}</b></div>
<div class="card">Scan warnings<br><b>{errors}</b></div></div>
<h2>Largest files (up to 5,000)</h2>
<table><thead><tr><th>Name</th><th>Path</th><th>Size</th></tr></thead>
<tbody>{rows}</tbody></table>
</main></body></html>""".format(
                generated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                root=html.escape(self.last_scan_path or ""),
                total=format_size(self.total_size), files=self.file_count,
                folders=self.folder_count, errors=self.scan_errors,
                rows="".join(rows)
            )
            with open(path, "w", encoding="utf-8") as file:
                file.write(page)
            self.status_var.set(f"HTML report exported: {path}")
            messagebox.showinfo("Export complete", "HTML report saved successfully.")
        except OSError as exc:
            messagebox.showerror("Export failed", str(exc))

    # ---------- Menus, theme, close ----------

    def _toggle_theme(self):
        self.theme_name = "dark" if self.theme_name == "light" else "light"
        self.root.config(menu="")
        for child in self.root.winfo_children():
            child.destroy()
        self._configure_theme()
        self._configure_style()
        self._build_layout()
        self._refresh_drives()
        self.theme_button.config(text="☀  Light mode" if self.theme_name == "dark" else "☾  Dark mode")
        self._build_menubar()
        if self.root_node:
            self.stat_total.config(text=format_size(self.total_size))
            self.stat_files.config(text=f"{self.file_count:,}")
            self.stat_folders.config(text=f"{self.folder_count:,}")
            self._refresh_table()
            self._draw_map()
            self._update_breadcrumb()

    def _build_menubar(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Scan folder", command=self._start_scan)
        file_menu.add_separator()
        file_menu.add_command(label="Export CSV report…", command=self._export_csv)
        file_menu.add_command(label="Export HTML report…", command=self._export_html)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(label="Go to root", command=self._go_root)
        view_menu.add_command(label="Go up one folder", command=self._go_up)
        view_menu.add_command(label="Toggle light / dark", command=self._toggle_theme)
        menubar.add_cascade(label="Navigate", menu=view_menu)

        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(
            label="About SpaceMap",
            command=lambda: messagebox.showinfo(
                "About SpaceMap",
                f"{APP_NAME} {VERSION}\nOffline storage analyzer.\n"
                "Read-only: it never deletes or modifies scanned files."
            )
        )
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)

    def _on_close(self):
        if self.scanning:
            self.cancel_event.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = SpaceMapApp(root)

    app._build_menubar()

    root.mainloop()


if __name__ == "__main__":
    main()
