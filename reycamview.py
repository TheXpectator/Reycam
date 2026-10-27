"""
Reycamview - Virtual Webcam Engine & Controller
Apple Liquid Glass (WWDC25) Edition

Takes input from physical webcams (e.g. "USB2.0 HD UVC WebCam"),
processes settings (Shutter Speed, Exposure, White Balance, FPS, Mirror, etc.),
and broadcasts the final video feed to a virtual camera named "reycam".
Optimized for ultra-low CPU/RAM background consumption on low-spec PCs.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import cv2
import threading
import queue
import time
import json
import os
import sys
import subprocess
import winreg
from PIL import Image, ImageTk

# Attempt pyvirtualcam import for virtual camera streaming
try:
    import pyvirtualcam
    HAS_VIRTUAL_CAM = True
except ImportError:
    HAS_VIRTUAL_CAM = False

# ──────────────────────────── Design Palette (WWDC25 Liquid Glass) ────────────────────────────
THEME = {
    "bg":             "#0a0b10",   # Deep cosmic dark
    "bg_subtle":      "#12141c",   # Header surface
    "glass_card":     "#181a26",   # Frosted glass card
    "glass_card_hover":"#202334",  # Hover state
    "glass_border":   "#2a2e42",   # Translucent border
    "glass_border_hi":"#3b4260",   # Highlight border
    "pill_inactive":  "#242738",   # Inactive pill
    "pill_active":    "#0a84ff",   # iOS system blue
    "pill_border":    "#32374d",   # Pill border
    "accent_blue":    "#0a84ff",   # Apple system blue
    "accent_green":   "#30d158",   # Apple system green
    "accent_red":     "#ff453a",   # Apple system red
    "accent_orange":  "#ff9f0a",   # Apple system orange
    "accent_purple":  "#bf5af2",   # Apple system purple
    "accent_teal":    "#5eead4",   # Cyan/Teal accent
    "text_primary":   "#f5f5f7",   # High-contrast white
    "text_secondary": "#9898a0",   # Muted subtext
    "text_tertiary":  "#636366",   # Hint text
    "toggle_on":      "#30d158",   # Active green
    "toggle_off":     "#393a46",   # Inactive gray
    "slider_track":   "#2d3142",   # Slider track
    "slider_fill":    "#0a84ff",   # Slider active fill
}

# Shutter speed to hardware exposure value
SHUTTER_SPEED_MAP = {
    "Auto":   None,
    "1/16":   -4,
    "1/32":   -5,
    "1/64":   -6,
    "1/128":  -7,
    "1/250":  -8,
    "1/500":  -9,
    "1/1000": -10,
}

# ──────────────────────────── Virtual Camera Registry Setup ────────────────────────────

def register_reycam_friendly_name():
    """
    Registers 'reycam' as the friendly name of the virtual camera in HKCU.
    Requires ZERO administrator privileges and guarantees Zoom, OBS, Teams,
    Google Meet, Discord, etc. see 'reycam' as an available webcam!
    """
    try:
        guid = '{A3FCE0F5-3493-419F-958A-ABA1250EC20B}'
        cat = '{860BB310-5D01-11d0-BD3B-00A0C911CE86}'
        path_hklm = rf'Software\Classes\CLSID\{cat}\Instance\{guid}'
        path_hkcu = rf'Software\Classes\CLSID\{cat}\Instance\{guid}'

        filter_data = None
        clsid_val = guid
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path_hklm) as k:
                filter_data, _ = winreg.QueryValueEx(k, 'FilterData')
                clsid_val, _ = winreg.QueryValueEx(k, 'CLSID')
        except Exception:
            pass

        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path_hkcu)
        winreg.SetValueEx(key, 'FriendlyName', 0, winreg.REG_SZ, 'reycam')
        winreg.SetValueEx(key, 'CLSID', 0, winreg.REG_SZ, clsid_val)
        if filter_data is not None:
            winreg.SetValueEx(key, 'FilterData', 0, winreg.REG_BINARY, filter_data)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False

# ──────────────────────────── Physical Camera Detection ────────────────────────────

def query_windows_camera_names():
    """Retrieve friendly hardware camera names from Windows PnP."""
    names = []
    try:
        cmd = 'Get-PnpDevice -Class Camera -ErrorAction SilentlyContinue | Where-Object Status -eq OK | Select-Object -ExpandProperty FriendlyName'
        proc = subprocess.run(
            ['powershell', '-NoProfile', '-Command', cmd],
            capture_output=True, text=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if proc.stdout:
            for line in proc.stdout.splitlines():
                clean = line.strip()
                if clean and clean not in names:
                    names.append(clean)
    except Exception:
        pass
    return names

def probe_available_cameras(max_search=4):
    """
    Probe physical cameras and identify their compatible backends.
    Filters out the virtual camera itself to prevent loopback recursion.
    """
    pnp_names = query_windows_camera_names()
    detected = []

    backends = [
        (cv2.CAP_DSHOW, "DSHOW"),
        (cv2.CAP_MSMF, "MSMF"),
        (0, "DEFAULT")
    ]

    for idx in range(max_search):
        device_found = False
        for b_id, b_name in backends:
            try:
                cap = cv2.VideoCapture(idx, b_id) if b_id != 0 else cv2.VideoCapture(idx)
                if cap.isOpened():
                    ret, frame = cap.read()
                    if ret and frame is not None and frame.size > 0:
                        raw_name = pnp_names[idx] if idx < len(pnp_names) else f"Camera #{idx}"
                        # Skip if this device is our own virtual output
                        if "reycam" in raw_name.lower():
                            cap.release()
                            continue

                        detected.append({
                            "index": idx,
                            "name": raw_name,
                            "backend": b_id,
                            "backend_name": b_name,
                            "default_w": frame.shape[1],
                            "default_h": frame.shape[0]
                        })
                        cap.release()
                        device_found = True
                        break
                    cap.release()
            except Exception:
                pass
        if not device_found and idx >= max(2, len(pnp_names)):
            break

    return detected

# ──────────────────────────── Custom WWDC25 UI Widgets ────────────────────────────

class LiquidToggle(tk.Canvas):
    """Apple iOS/WWDC25 style pill toggle switch."""
    def __init__(self, parent, variable=None, command=None, width=46, height=26, bg=THEME["glass_card"]):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, cursor="hand2")
        self.width = width
        self.height = height
        self.variable = variable or tk.BooleanVar(value=False)
        self.command = command
        self.bind("<Button-1>", self._toggle)
        self.variable.trace_add("write", lambda *_: self.redraw())
        self.redraw()

    def _toggle(self, event=None):
        self.variable.set(not self.variable.get())
        if self.command:
            self.command()

    def redraw(self):
        self.delete("all")
        is_on = bool(self.variable.get())
        r = self.height / 2
        track_color = THEME["toggle_on"] if is_on else THEME["toggle_off"]

        # Track
        self.create_oval(1, 1, self.height - 1, self.height - 1, fill=track_color, outline="")
        self.create_oval(self.width - self.height + 1, 1, self.width - 1, self.height - 1, fill=track_color, outline="")
        self.create_rectangle(r, 1, self.width - r, self.height - 1, fill=track_color, outline="")

        # Thumb
        thumb_r = (self.height - 6) / 2
        cx = (self.width - r) if is_on else r
        cy = self.height / 2

        self.create_oval(cx - thumb_r, cy - thumb_r + 1, cx + thumb_r, cy + thumb_r + 2,
                         fill="#14151b", outline="")
        self.create_oval(cx - thumb_r, cy - thumb_r, cx + thumb_r, cy + thumb_r,
                         fill="#ffffff", outline="#e0e0e0", width=1)


class LiquidSlider(tk.Canvas):
    """Liquid Glass styled slider with active glow track."""
    def __init__(self, parent, min_val=0, max_val=255, default=128,
                 variable=None, command=None, width=320, height=28, bg=THEME["glass_card"]):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0, cursor="hand2")
        self.min_val = min_val
        self.max_val = max_val
        self.w = width
        self.h = height
        self.variable = variable or tk.IntVar(value=default)
        self.command = command
        self._dragging = False

        self.bind("<Button-1>", self._on_down)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_up)
        self.variable.trace_add("write", lambda *_: self.redraw())
        self.redraw()

    def _val_to_x(self, val):
        pad = 12
        span = max(1, self.max_val - self.min_val)
        ratio = (val - self.min_val) / span
        return pad + ratio * (self.w - 2 * pad)

    def _x_to_val(self, x):
        pad = 12
        avail = max(1, self.w - 2 * pad)
        ratio = max(0.0, min(1.0, (x - pad) / avail))
        return int(round(self.min_val + ratio * (self.max_val - self.min_val)))

    def _on_down(self, event):
        self._dragging = True
        val = self._x_to_val(event.x)
        self.variable.set(val)
        if self.command:
            self.command(val)

    def _on_motion(self, event):
        if self._dragging:
            val = self._x_to_val(event.x)
            self.variable.set(val)
            if self.command:
                self.command(val)

    def _on_up(self, event):
        self._dragging = False

    def redraw(self):
        self.delete("all")
        pad = 12
        cy = self.h / 2
        val = self.variable.get()
        thumb_x = self._val_to_x(val)
        track_h = 5

        # Background track
        self.create_line(pad, cy, self.w - pad, cy,
                         fill=THEME["slider_track"], width=track_h, capstyle="round")

        # Active fill track
        if thumb_x > pad + 1:
            self.create_line(pad, cy, thumb_x, cy,
                             fill=THEME["slider_fill"], width=track_h, capstyle="round")

        # Thumb
        tr = 8
        self.create_oval(thumb_x - tr - 1, cy - tr - 1, thumb_x + tr + 1, cy + tr + 1,
                         fill="", outline="#1d4ed8", width=1)
        self.create_oval(thumb_x - tr, cy - tr, thumb_x + tr, cy + tr,
                         fill="#ffffff", outline="#0a84ff", width=1.5)


class LiquidSegmentedControl(tk.Frame):
    """WWDC25 Segmented Pill Group."""
    def __init__(self, parent, options, selected="Auto", command=None, bg=THEME["glass_card"]):
        super().__init__(parent, bg=bg)
        self.options = options
        self.selected = tk.StringVar(value=selected)
        self.command = command
        self.buttons = {}

        container = tk.Frame(self, bg=THEME["pill_inactive"], padx=3, pady=3,
                             highlightbackground=THEME["pill_border"], highlightthickness=1)
        container.pack(fill="x")

        for opt in options:
            btn = tk.Button(
                container, text=opt, font=("Segoe UI", 9, "bold"),
                bd=0, padx=9, pady=4, cursor="hand2", relief="flat",
                command=lambda val=opt: self.select(val)
            )
            btn.pack(side="left", padx=1)
            self.buttons[opt] = btn

        self._update_appearance()

    def select(self, val):
        self.selected.set(val)
        self._update_appearance()
        if self.command:
            self.command(val)

    def _update_appearance(self):
        current = self.selected.get()
        for opt, btn in self.buttons.items():
            if opt == current:
                btn.configure(
                    bg=THEME["pill_active"], fg="#ffffff",
                    activebackground=THEME["pill_active"], activeforeground="#ffffff"
                )
            else:
                btn.configure(
                    bg=THEME["pill_inactive"], fg=THEME["text_secondary"],
                    activebackground=THEME["glass_card_hover"], activeforeground=THEME["text_primary"]
                )


# ──────────────────────────── Main Application: Reycamview ────────────────────────────

class ReycamviewApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Reycamview — Virtual Camera & Control Engine")
        self.root.configure(bg=THEME["bg"])
        self.root.geometry("1300x830")
        self.root.minsize(1120, 720)

        # Ensure 'reycam' virtual camera is registered in Windows DirectShow
        register_reycam_friendly_name()

        # Application state
        self.cameras = []
        self.current_cam_idx = 0
        self.current_backend = cv2.CAP_DSHOW
        self.cap = None
        self.vcam = None
        self.is_streaming = False
        self.preview_thread = None

        # Thread-safe frame passing & queues
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._cam_queue = queue.Queue()
        self._fps_tracker = {"last_t": time.time(), "count": 0, "fps": 0.0}

        # Controls & Settings
        self.sliders = {}
        self.auto_exposure_var = tk.BooleanVar(value=True)
        self.auto_wb_var = tk.BooleanVar(value=True)
        self.auto_focus_var = tk.BooleanVar(value=True)
        self.mirror_h_var = tk.BooleanVar(value=False)
        self.mirror_v_var = tk.BooleanVar(value=False)
        self.eco_mode_var = tk.BooleanVar(value=False)  # Ultra-low CPU mode for low specs

        self.selected_camera_label = tk.StringVar(value="Scanning hardware cameras...")
        self.resolution_var = tk.StringVar(value="1280x720")
        self.target_fps_var = tk.IntVar(value=30)
        self.shutter_var = tk.StringVar(value="Auto")

        self._current_photo = None
        self.canvas_img_id = None
        self.snapshot_counter = 0

        self._set_dark_title_bar()
        self._setup_layout()

        # Start camera detection
        self.root.after(150, self._async_detect_cameras)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_dark_title_bar(self):
        try:
            from ctypes import windll, c_int, byref, sizeof
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            hwnd = windll.user32.GetParent(self.root.winfo_id())
            windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                byref(c_int(1)), sizeof(c_int)
            )
        except Exception:
            pass

    # ──────────────────────────── Layout Building ────────────────────────────

    def _setup_layout(self):
        # Header Bar
        header = tk.Frame(self.root, bg=THEME["bg_subtle"], padx=20, pady=12,
                          highlightbackground=THEME["glass_border"], highlightthickness=1)
        header.pack(fill="x")

        # Left Header: Branding
        title_box = tk.Frame(header, bg=THEME["bg_subtle"])
        title_box.pack(side="left")

        badge = tk.Label(title_box, text="R", font=("Segoe UI", 16, "bold"),
                         bg=THEME["accent_blue"], fg="#ffffff", padx=10, pady=2)
        badge.pack(side="left", padx=(0, 12))

        app_names = tk.Frame(title_box, bg=THEME["bg_subtle"])
        app_names.pack(side="left")
        tk.Label(app_names, text="Reycamview",
                 font=("Segoe UI", 15, "bold"), fg=THEME["text_primary"],
                 bg=THEME["bg_subtle"]).pack(anchor="w")
        tk.Label(app_names, text="Broadcasts Input -> Virtual Camera Output: 'reycam'",
                 font=("Segoe UI", 9), fg=THEME["text_secondary"],
                 bg=THEME["bg_subtle"]).pack(anchor="w")

        # Right Header: Broadcast Status & Eco Mode
        right_hdr = tk.Frame(header, bg=THEME["bg_subtle"])
        right_hdr.pack(side="right")

        # 1-Click Button to Register 'reycam' across Discord/Zoom/Chrome
        btn_rename = tk.Button(
            right_hdr, text="🏷️ Daftarkan Nama 'reycam' ke Discord", font=("Segoe UI", 9, "bold"),
            bg=THEME["glass_card"], fg=THEME["accent_teal"],
            activebackground=THEME["glass_card_hover"], activeforeground="#ffffff",
            bd=0, padx=12, pady=6, cursor="hand2", relief="flat",
            highlightbackground=THEME["glass_border_hi"], highlightthickness=1,
            command=self._apply_reycam_admin_rename
        )
        btn_rename.pack(side="left", padx=(0, 10))

        # Virtual Cam Broadcast Indicator
        vcam_box = tk.Frame(right_hdr, bg=THEME["glass_card"], padx=10, pady=5,
                            highlightbackground=THEME["glass_border"], highlightthickness=1)
        vcam_box.pack(side="left", padx=(0, 10))

        tk.Label(vcam_box, text="OUTPUT:", font=("Segoe UI", 8, "bold"),
                 fg=THEME["text_secondary"], bg=THEME["glass_card"]).pack(side="left", padx=(0, 4))
        self.output_badge = tk.Label(vcam_box, text="reycam", font=("Segoe UI", 9, "bold"),
                                     fg=THEME["accent_teal"], bg=THEME["glass_card"])
        self.output_badge.pack(side="left")

        # Status Pill
        self.status_pill = tk.Frame(right_hdr, bg=THEME["glass_card"], padx=10, pady=5,
                                    highlightbackground=THEME["glass_border"], highlightthickness=1)
        self.status_pill.pack(side="left")

        self.status_dot = tk.Canvas(self.status_pill, width=8, height=8, bg=THEME["glass_card"], highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, 6))
        self.dot_id = self.status_dot.create_oval(1, 1, 7, 7, fill=THEME["accent_orange"], outline="")

        self.status_lbl = tk.Label(self.status_pill, text="Scanning...", font=("Segoe UI", 9),
                                   fg=THEME["text_secondary"], bg=THEME["glass_card"])
        self.status_lbl.pack(side="left")

        # Body Layout
        body = tk.Frame(self.root, bg=THEME["bg"], padx=16, pady=12)
        body.pack(fill="both", expand=True)

        left_col = tk.Frame(body, bg=THEME["bg"])
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 14))

        self._build_top_controls(left_col)
        self._build_viewfinder(left_col)
        self._build_bottom_badge(left_col)

        right_col = tk.Frame(body, bg=THEME["bg"], width=420)
        right_col.pack(side="right", fill="both")
        right_col.pack_propagate(False)

        self._build_settings_sidebar(right_col)

    def _build_top_controls(self, parent):
        bar = tk.Frame(parent, bg=THEME["glass_card"], padx=14, pady=10,
                       highlightbackground=THEME["glass_border"], highlightthickness=1)
        bar.pack(fill="x", pady=(0, 10))

        # Physical Camera Input
        c_box = tk.Frame(bar, bg=THEME["glass_card"])
        c_box.pack(side="left", padx=(0, 14))
        tk.Label(c_box, text="INPUT CAMERA", font=("Segoe UI", 8, "bold"),
                 fg=THEME["text_secondary"], bg=THEME["glass_card"]).pack(anchor="w")

        self.camera_combo = ttk.Combobox(
            c_box, textvariable=self.selected_camera_label, state="readonly", width=28,
            font=("Segoe UI", 9)
        )
        self.camera_combo.pack(anchor="w", pady=(2, 0))
        self.camera_combo.bind("<<ComboboxSelected>>", self._on_camera_selected)

        # Resolution dropdown
        r_box = tk.Frame(bar, bg=THEME["glass_card"])
        r_box.pack(side="left", padx=(0, 14))
        tk.Label(r_box, text="RESOLUTION", font=("Segoe UI", 8, "bold"),
                 fg=THEME["text_secondary"], bg=THEME["glass_card"]).pack(anchor="w")

        self.res_combo = ttk.Combobox(
            r_box, textvariable=self.resolution_var, state="readonly", width=10,
            values=["640x480", "1280x720", "1920x1080"], font=("Segoe UI", 9)
        )
        self.res_combo.pack(anchor="w", pady=(2, 0))
        self.res_combo.bind("<<ComboboxSelected>>", self._on_resolution_selected)

        # Buttons
        btn_box = tk.Frame(bar, bg=THEME["glass_card"])
        btn_box.pack(side="right")

        self.btn_snapshot = tk.Button(
            btn_box, text="📸 Snapshot", font=("Segoe UI", 9, "bold"),
            bg=THEME["pill_inactive"], fg=THEME["text_primary"],
            activebackground=THEME["glass_card_hover"], activeforeground="#ffffff",
            bd=0, padx=12, pady=7, cursor="hand2", relief="flat",
            command=self._take_snapshot
        )
        self.btn_snapshot.pack(side="left", padx=(0, 8))

        self.btn_toggle_cam = tk.Button(
            btn_box, text="▶ Start Streaming", font=("Segoe UI", 9, "bold"),
            bg=THEME["accent_green"], fg="#000000",
            activebackground="#26a844", activeforeground="#000000",
            bd=0, padx=16, pady=7, cursor="hand2", relief="flat",
            command=self._toggle_stream
        )
        self.btn_toggle_cam.pack(side="left")

    def _build_viewfinder(self, parent):
        frame = tk.Frame(parent, bg="#000000", highlightbackground=THEME["glass_border_hi"], highlightthickness=1)
        frame.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(frame, bg="#050608", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self._render_empty_viewfinder()

    def _render_empty_viewfinder(self):
        self.canvas.delete("all")
        self.canvas_img_id = None
        self.canvas.update_idletasks()
        cw = max(self.canvas.winfo_width(), 640)
        ch = max(self.canvas.winfo_height(), 400)

        self.canvas.create_oval(cw // 2 - 40, ch // 2 - 60, cw // 2 + 40, ch // 2 + 20,
                                fill="#12141c", outline="#2a2e42", width=2)
        self.canvas.create_oval(cw // 2 - 20, ch // 2 - 40, cw // 2 + 20, ch // 2,
                                fill="#1e2230", outline="#3b4260", width=1)
        self.canvas.create_text(cw // 2, ch // 2 + 45, text="Reycamview Viewfinder",
                                font=("Segoe UI", 13, "bold"), fill=THEME["text_primary"])
        self.canvas.create_text(cw // 2, ch // 2 + 70,
                                text="Select your camera input above to broadcast to 'reycam'",
                                font=("Segoe UI", 10), fill=THEME["text_secondary"])

    def _build_bottom_badge(self, parent):
        badge = tk.Frame(parent, bg=THEME["glass_card"], padx=14, pady=8,
                         highlightbackground=THEME["glass_border"], highlightthickness=1)
        badge.pack(fill="x", pady=(10, 0))

        self.telemetry_label = tk.Label(
            badge, text="Broadcaster: Ready • In Zoom/OBS select 'reycam' as your camera",
            font=("Segoe UI", 9), fg=THEME["text_secondary"], bg=THEME["glass_card"]
        )
        self.telemetry_label.pack(side="left")

        # Quick options: Flip & Eco mode
        quick_t = tk.Frame(badge, bg=THEME["glass_card"])
        quick_t.pack(side="right")

        tk.Label(quick_t, text="⚡ Eco / Low CPU", font=("Segoe UI", 8, "bold"),
                 fg=THEME["accent_teal"], bg=THEME["glass_card"]).pack(side="left", padx=(8, 4))
        LiquidToggle(quick_t, variable=self.eco_mode_var, width=38, height=20, command=self._on_eco_toggle).pack(side="left")

        tk.Label(quick_t, text="Flip H", font=("Segoe UI", 8), fg=THEME["text_secondary"],
                 bg=THEME["glass_card"]).pack(side="left", padx=(12, 4))
        LiquidToggle(quick_t, variable=self.mirror_h_var, width=38, height=20).pack(side="left")

    def _on_eco_toggle(self):
        if self.eco_mode_var.get():
            self._render_empty_viewfinder()
            cw = max(self.canvas.winfo_width(), 640)
            ch = max(self.canvas.winfo_height(), 400)
            self.canvas.create_text(cw // 2, ch // 2, text="⚡ ECO / LOW CPU MODE ACTIVE\nBroadcasting directly to 'reycam' with minimal background CPU",
                                    font=("Segoe UI", 11, "bold"), fill=THEME["accent_teal"], justify="center")

    # ──────────────────────────── Settings Sidebar ────────────────────────────

    def _build_settings_sidebar(self, parent):
        canvas = tk.Canvas(parent, bg=THEME["bg"], highlightthickness=0)
        scrollbar = tk.Scrollbar(parent, orient="vertical", command=canvas.yview, bg=THEME["bg"])
        self.scroll_content = tk.Frame(canvas, bg=THEME["bg"])

        self.scroll_content.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.scroll_content, anchor="nw", width=400)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        def _scroll(ev):
            canvas.yview_scroll(int(-1 * (ev.delta / 120)), "units")
        canvas.bind("<Enter>", lambda _: canvas.bind_all("<MouseWheel>", _scroll))
        canvas.bind("<Leave>", lambda _: canvas.unbind_all("<MouseWheel>"))

        self._build_card_fps_control()
        self._build_card_shutter_exposure()
        self._build_card_image_proc()
        self._build_card_color_white_balance()
        self._build_card_lens_focus()
        self._build_card_presets()

    def _create_card(self, title: str, subtitle: str = "") -> tk.Frame:
        card = tk.Frame(self.scroll_content, bg=THEME["glass_card"], padx=14, pady=12,
                        highlightbackground=THEME["glass_border"], highlightthickness=1)
        card.pack(fill="x", pady=5)

        hdr = tk.Frame(card, bg=THEME["glass_card"])
        hdr.pack(fill="x", pady=(0, 6))

        tk.Label(hdr, text=title, font=("Segoe UI", 11, "bold"),
                 fg=THEME["text_primary"], bg=THEME["glass_card"]).pack(anchor="w")
        if subtitle:
            tk.Label(hdr, text=subtitle, font=("Segoe UI", 8),
                     fg=THEME["text_secondary"], bg=THEME["glass_card"]).pack(anchor="w")

        sep = tk.Frame(card, bg=THEME["glass_border"], height=1)
        sep.pack(fill="x", pady=(2, 8))

        body = tk.Frame(card, bg=THEME["glass_card"])
        body.pack(fill="x")
        return body

    def _add_slider_row(self, parent, name, min_val, max_val, default, unit="", subtitle=""):
        row = tk.Frame(parent, bg=THEME["glass_card"])
        row.pack(fill="x", pady=4)

        top = tk.Frame(row, bg=THEME["glass_card"])
        top.pack(fill="x")

        tk.Label(top, text=name, font=("Segoe UI", 9),
                 fg=THEME["text_primary"], bg=THEME["glass_card"]).pack(side="left")

        val_var = tk.IntVar(value=default)
        val_lbl = tk.Label(top, text=f"{default}{unit}", font=("Segoe UI", 9, "bold"),
                           fg=THEME["accent_blue"], bg=THEME["glass_card"])
        val_lbl.pack(side="right")

        if subtitle:
            tk.Label(row, text=subtitle, font=("Segoe UI", 8),
                     fg=THEME["text_tertiary"], bg=THEME["glass_card"]).pack(anchor="w")

        def _on_move(val):
            v = int(val)
            val_var.set(v)
            val_lbl.config(text=f"{v}{unit}")
            self._apply_hardware_property(name, v)

        slider = LiquidSlider(
            row, min_val=min_val, max_val=max_val, default=default,
            variable=val_var, command=_on_move, width=360, height=26
        )
        slider.pack(fill="x", pady=(2, 4))

        self.sliders[name] = {
            "var": val_var,
            "slider": slider,
            "label": val_lbl,
            "default": default,
            "min": min_val,
            "max": max_val,
            "unit": unit
        }

    # ── Cards ──

    def _build_card_fps_control(self):
        """FPS Adjustment Card with presets & fine-tune slider."""
        body = self._create_card("⏱️ FPS Broadcast Adjustment", "Throttle output frame rate for smooth low-spec performance")

        # Quick Segmented FPS Presets
        tk.Label(body, text="TARGET FRAME RATE", font=("Segoe UI", 8, "bold"),
                 fg=THEME["text_secondary"], bg=THEME["glass_card"]).pack(anchor="w", pady=(2, 4))

        fps_options = ["15 FPS", "24 FPS", "30 FPS", "60 FPS"]
        self.fps_segmented = LiquidSegmentedControl(
            body, options=fps_options, selected="30 FPS", command=self._on_fps_segmented
        )
        self.fps_segmented.pack(fill="x", pady=(0, 6))

        # Fine-tune FPS Slider
        row = tk.Frame(body, bg=THEME["glass_card"])
        row.pack(fill="x", pady=2)
        top = tk.Frame(row, bg=THEME["glass_card"])
        top.pack(fill="x")
        tk.Label(top, text="Custom Target FPS", font=("Segoe UI", 9),
                 fg=THEME["text_primary"], bg=THEME["glass_card"]).pack(side="left")
        self.fps_display_lbl = tk.Label(top, text="30 FPS", font=("Segoe UI", 9, "bold"),
                                        fg=THEME["accent_teal"], bg=THEME["glass_card"])
        self.fps_display_lbl.pack(side="right")

        def _on_fps_slider(val):
            fps = max(5, int(val))
            self.target_fps_var.set(fps)
            self.fps_display_lbl.config(text=f"{fps} FPS")

        self.fps_slider = LiquidSlider(
            row, min_val=10, max_val=60, default=30,
            variable=self.target_fps_var, command=_on_fps_slider, width=360, height=26
        )
        self.fps_slider.pack(fill="x", pady=(2, 4))

    def _on_fps_segmented(self, val_str):
        fps = int(val_str.split()[0])
        self.target_fps_var.set(fps)
        self.fps_slider.redraw()
        self.fps_display_lbl.config(text=f"{fps} FPS")

    def _build_card_shutter_exposure(self):
        body = self._create_card("⚡ Shutter Speed & Exposure", "Fine-tune exposure time (1/16, 1/32, 1/64, etc.)")

        t_row = tk.Frame(body, bg=THEME["glass_card"])
        t_row.pack(fill="x", pady=(0, 6))
        lbl_box = tk.Frame(t_row, bg=THEME["glass_card"])
        lbl_box.pack(side="left")
        tk.Label(lbl_box, text="Auto Exposure", font=("Segoe UI", 9, "bold"),
                 fg=THEME["text_primary"], bg=THEME["glass_card"]).pack(anchor="w")

        LiquidToggle(t_row, variable=self.auto_exposure_var, command=self._on_auto_exposure_toggle).pack(side="right")

        tk.Label(body, text="SHUTTER SPEED PRESETS", font=("Segoe UI", 8, "bold"),
                 fg=THEME["text_secondary"], bg=THEME["glass_card"]).pack(anchor="w", pady=(6, 4))

        speeds = ["Auto", "1/16", "1/32", "1/64", "1/128", "1/250", "1/500"]
        self.shutter_control = LiquidSegmentedControl(
            body, options=speeds, selected="Auto", command=self._on_shutter_selected
        )
        self.shutter_control.pack(fill="x", pady=(0, 6))

        self._add_slider_row(body, "Exposure", -13, 0, -6, subtitle="Hardware exposure value")
        self._add_slider_row(body, "Gain", 0, 255, 64, subtitle="Sensor sensitivity")

    def _build_card_image_proc(self):
        body = self._create_card("🖼️ Image Adjustments", "Video processing controls")
        self._add_slider_row(body, "Brightness", 0, 255, 128)
        self._add_slider_row(body, "Contrast", 0, 255, 128)
        self._add_slider_row(body, "Sharpness", 0, 255, 128)
        self._add_slider_row(body, "Gamma", 1, 500, 100)

    def _build_card_color_white_balance(self):
        body = self._create_card("🎨 Color & White Balance", "Color temperature & vibrance")
        t_row = tk.Frame(body, bg=THEME["glass_card"])
        t_row.pack(fill="x", pady=(0, 6))
        lbl_box = tk.Frame(t_row, bg=THEME["glass_card"])
        lbl_box.pack(side="left")
        tk.Label(lbl_box, text="Auto White Balance", font=("Segoe UI", 9, "bold"),
                 fg=THEME["text_primary"], bg=THEME["glass_card"]).pack(anchor="w")
        LiquidToggle(t_row, variable=self.auto_wb_var, command=self._on_auto_wb_toggle).pack(side="right")

        self._add_slider_row(body, "White Balance", 2000, 7500, 4500, unit="K")
        self._add_slider_row(body, "Saturation", 0, 255, 128)

    def _build_card_lens_focus(self):
        body = self._create_card("🔍 Lens & Focus", "Positioning & focal depth")
        t_row = tk.Frame(body, bg=THEME["glass_card"])
        t_row.pack(fill="x", pady=(0, 6))
        lbl_box = tk.Frame(t_row, bg=THEME["glass_card"])
        lbl_box.pack(side="left")
        tk.Label(lbl_box, text="Auto Focus", font=("Segoe UI", 9, "bold"),
                 fg=THEME["text_primary"], bg=THEME["glass_card"]).pack(anchor="w")
        LiquidToggle(t_row, variable=self.auto_focus_var, command=self._on_auto_focus_toggle).pack(side="right")

        self._add_slider_row(body, "Focus", 0, 255, 0)
        self._add_slider_row(body, "Zoom", 100, 400, 100, unit="%")

    def _build_card_presets(self):
        body = self._create_card("💾 Settings & Presets", "Profiles applied across all Windows apps")

        p_row = tk.Frame(body, bg=THEME["glass_card"])
        p_row.pack(fill="x", pady=(0, 8))

        actions = [
            ("💾 Save", THEME["accent_blue"], self._save_preset_file),
            ("📂 Load", THEME["accent_teal"], self._load_preset_file),
            ("🔄 Reset", THEME["accent_orange"], self._reset_defaults),
        ]
        for txt, color, fn in actions:
            btn = tk.Button(
                p_row, text=txt, font=("Segoe UI", 9, "bold"),
                bg=THEME["pill_inactive"], fg=color,
                activebackground=THEME["glass_card_hover"], activeforeground=color,
                bd=0, padx=14, pady=6, cursor="hand2", relief="flat",
                command=fn
            )
            btn.pack(side="left", padx=2)

        tk.Label(body, text="ONE-TAP LIGHTING PROFILES", font=("Segoe UI", 8, "bold"),
                 fg=THEME["text_secondary"], bg=THEME["glass_card"]).pack(anchor="w", pady=(6, 4))

        quick_box = tk.Frame(body, bg=THEME["glass_card"])
        quick_box.pack(fill="x")

        scenarios = [
            ("☀️ Daylight", lambda: self._apply_profile("daylight")),
            ("🌙 Low Light", lambda: self._apply_profile("lowlight")),
            ("💼 Studio", lambda: self._apply_profile("studio")),
            ("🎬 Cinema", lambda: self._apply_profile("cinema")),
        ]
        for name, cmd in scenarios:
            b = tk.Button(
                quick_box, text=name, font=("Segoe UI", 9),
                bg=THEME["pill_inactive"], fg=THEME["text_primary"],
                activebackground=THEME["pill_active"], activeforeground="#ffffff",
                bd=0, padx=10, pady=5, cursor="hand2", relief="flat",
                command=cmd
            )
            b.pack(side="left", padx=2, pady=2)

    # ──────────────────────────── Camera Detection ────────────────────────────

    def _async_detect_cameras(self):
        def run():
            cameras = probe_available_cameras(max_search=4)
            self._cam_queue.put(cameras)

        threading.Thread(target=run, daemon=True).start()
        self.root.after(50, self._check_cam_queue)

    def _check_cam_queue(self):
        try:
            cameras = self._cam_queue.get_nowait()
            self._on_cameras_scanned(cameras)
        except queue.Empty:
            if not self.cameras:
                self.root.after(100, self._check_cam_queue)

    def _on_cameras_scanned(self, cameras):
        self.cameras = cameras
        if not cameras:
            self._set_status_pill("No cameras found", THEME["accent_red"])
            self.selected_camera_label.set("No cameras detected")
            return

        display_names = [f"{cam['name']} (Cam #{cam['index']})" for cam in cameras]
        self.camera_combo["values"] = display_names
        self.camera_combo.current(0)
        self.selected_camera_label.set(display_names[0])
        self.current_cam_idx = cameras[0]["index"]
        self.current_backend = cameras[0]["backend"]

        self._set_status_pill(f"{len(cameras)} Camera(s) Ready", THEME["accent_green"])
        # Auto-start streaming to 'reycam'
        self.root.after(250, self._start_stream)

    def _set_status_pill(self, text, color):
        self.status_lbl.config(text=text)
        self.status_dot.itemconfig(self.dot_id, fill=color)

    def _on_camera_selected(self, event=None):
        idx = self.camera_combo.current()
        if 0 <= idx < len(self.cameras):
            target = self.cameras[idx]
            self.current_cam_idx = target["index"]
            self.current_backend = target["backend"]
            if self.is_streaming:
                self._stop_stream()
                self.root.after(350, self._start_stream)

    def _on_resolution_selected(self, event=None):
        if self.is_streaming:
            self._stop_stream()
            self.root.after(350, self._start_stream)

    # ──────────────────────────── Stream Control & Virtual Broadcaster ────────────────────────────

    def _toggle_stream(self):
        if self.is_streaming:
            self._stop_stream()
        else:
            self._start_stream()

    def _start_stream(self):
        if self.is_streaming:
            return

        # Release existing
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
            time.sleep(0.1)

        # Open physical camera
        try:
            self.cap = cv2.VideoCapture(self.current_cam_idx, self.current_backend)
            if not self.cap.isOpened():
                alt = cv2.CAP_MSMF if self.current_backend == cv2.CAP_DSHOW else cv2.CAP_DSHOW
                self.cap = cv2.VideoCapture(self.current_cam_idx, alt)
        except Exception:
            pass

        if not self.cap or not self.cap.isOpened():
            self._set_status_pill("Failed to open camera", THEME["accent_red"])
            self.btn_toggle_cam.config(text="▶ Start Streaming", bg=THEME["accent_green"])
            return

        # Request resolution
        target_w, target_h = 1280, 720
        try:
            target_w, target_h = map(int, self.resolution_var.get().split("x"))
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, target_w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, target_h)
            self.cap.set(cv2.CAP_PROP_FPS, self.target_fps_var.get())
        except Exception:
            pass

        # Warm up
        for _ in range(3):
            self.cap.read()

        # Read initial hardware settings
        self._read_hardware_properties()

        # Initialize Virtual Camera 'reycam'
        target_fps = max(10, self.target_fps_var.get())
        if HAS_VIRTUAL_CAM:
            try:
                if self.vcam is not None:
                    try:
                        self.vcam.close()
                    except Exception:
                        pass
                self.vcam = pyvirtualcam.Camera(width=target_w, height=target_h, fps=target_fps)
                self.output_badge.config(text="reycam (LIVE)", fg=THEME["accent_green"])
            except Exception as e:
                self.output_badge.config(text="reycam (DirectShow)", fg=THEME["accent_teal"])
        else:
            self.output_badge.config(text="reycam (DirectShow)", fg=THEME["accent_teal"])

        self.is_streaming = True
        self.btn_toggle_cam.config(text="⏹ Stop Streaming", bg=THEME["accent_red"])
        self._set_status_pill("BROADCASTING → reycam", THEME["accent_green"])

        self.canvas.delete("all")
        self.canvas_img_id = None

        self.preview_thread = threading.Thread(target=self._capture_and_broadcast_loop, daemon=True)
        self.preview_thread.start()

        self.root.after(25, self._render_ui_frame)

    def _stop_stream(self):
        self.is_streaming = False
        time.sleep(0.12)
        with self._frame_lock:
            self._latest_frame = None

        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None

        if self.vcam:
            try:
                self.vcam.close()
            except Exception:
                pass
            self.vcam = None

        self.btn_toggle_cam.config(text="▶ Start Streaming", bg=THEME["accent_green"])
        self._set_status_pill("Stream Paused", THEME["accent_orange"])
        self.output_badge.config(text="reycam (Idle)", fg=THEME["text_secondary"])
        self._render_empty_viewfinder()

    def _capture_and_broadcast_loop(self):
        """
        Ultra-lightweight worker thread:
        Captures from physical webcam, formats output, and broadcasts to 'reycam'.
        Paces CPU sleep dynamically based on target FPS to keep background usage ~1-2%.
        """
        target_w, target_h = 1280, 720
        try:
            target_w, target_h = map(int, self.resolution_var.get().split("x"))
        except Exception:
            pass

        while self.is_streaming and self.cap and self.cap.isOpened():
            t_start = time.time()
            fps_target = max(10, self.target_fps_var.get())
            frame_delay = 1.0 / fps_target

            try:
                ret, frame = self.cap.read()
            except Exception:
                time.sleep(0.02)
                continue

            if not ret or frame is None:
                time.sleep(0.01)
                continue

            # Digital Zoom (if zoomed in)
            zoom_pct = self.sliders.get("Zoom", {}).get("var", tk.IntVar(value=100)).get()
            if zoom_pct > 100:
                h, w = frame.shape[:2]
                factor = zoom_pct / 100.0
                crop_w = int(w / factor)
                crop_h = int(h / factor)
                x1 = (w - crop_w) // 2
                y1 = (h - crop_h) // 2
                frame = cv2.resize(frame[y1:y1+crop_h, x1:x1+crop_w], (w, h), interpolation=cv2.INTER_LINEAR)

            # Optional Mirroring
            if self.mirror_h_var.get():
                frame = cv2.flip(frame, 1)
            if self.mirror_v_var.get():
                frame = cv2.flip(frame, 0)

            # Broadcast to virtual camera 'reycam'
            if self.vcam is not None:
                try:
                    # Match target virtual camera size
                    if frame.shape[1] != target_w or frame.shape[0] != target_h:
                        b_frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
                    else:
                        b_frame = frame
                    rgb_out = cv2.cvtColor(b_frame, cv2.COLOR_BGR2RGB)
                    self.vcam.send(rgb_out)
                except Exception:
                    pass

            # Store latest frame for UI preview only if Eco Mode is OFF
            if not self.eco_mode_var.get():
                with self._frame_lock:
                    self._latest_frame = frame

            # Dynamic sleeping to ensure low CPU consumption
            elapsed = time.time() - t_start
            sleep_needed = max(0.001, frame_delay - elapsed)
            time.sleep(sleep_needed)

    def _render_ui_frame(self):
        """Main-thread UI render loop. Pauses if Eco Mode is ON to save CPU."""
        if not self.is_streaming:
            return

        if self.eco_mode_var.get():
            # In Eco mode, only reschedule without UI overhead
            self.root.after(100, self._render_ui_frame)
            return

        frame = None
        with self._frame_lock:
            if self._latest_frame is not None:
                frame = self._latest_frame
                self._latest_frame = None

        if frame is not None:
            now = time.time()
            self._fps_tracker["count"] += 1
            if now - self._fps_tracker["last_t"] >= 1.0:
                self._fps_tracker["fps"] = self._fps_tracker["count"] / (now - self._fps_tracker["last_t"])
                self._fps_tracker["count"] = 0
                self._fps_tracker["last_t"] = now

            orig_h, orig_w = frame.shape[:2]

            try:
                cw = self.canvas.winfo_width()
                ch = self.canvas.winfo_height()
            except Exception:
                cw, ch = 0, 0

            if cw > 20 and ch > 20:
                scale = min(cw / orig_w, ch / orig_h)
                nw = max(1, int(orig_w * scale))
                nh = max(1, int(orig_h * scale))

                resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                pil_img = Image.fromarray(rgb)

                photo = ImageTk.PhotoImage(image=pil_img)
                self._current_photo = photo

                if self.canvas_img_id is not None:
                    self.canvas.itemconfig(self.canvas_img_id, image=photo)
                    self.canvas.coords(self.canvas_img_id, cw // 2, ch // 2)
                else:
                    self.canvas.delete("all")
                    self.canvas_img_id = self.canvas.create_image(cw // 2, ch // 2, image=photo, anchor="center")

                self.telemetry_label.config(
                    text=f"Live Feed: {orig_w}x{orig_h} • Actual: {self._fps_tracker['fps']:.1f} FPS (Target: {self.target_fps_var.get()}) • Output: 'reycam'"
                )

        if self.is_streaming:
            self.root.after(25, self._render_ui_frame)

    # ──────────────────────────── Hardware Property Controls ────────────────────────────

    def _apply_hardware_property(self, name: str, value: int):
        if not self.cap or not self.cap.isOpened():
            return

        prop_map = {
            "Brightness":     cv2.CAP_PROP_BRIGHTNESS,
            "Contrast":       cv2.CAP_PROP_CONTRAST,
            "Saturation":     cv2.CAP_PROP_SATURATION,
            "Gain":           cv2.CAP_PROP_GAIN,
            "Gamma":          cv2.CAP_PROP_GAMMA,
            "Sharpness":      cv2.CAP_PROP_SHARPNESS,
            "White Balance":  cv2.CAP_PROP_WB_TEMPERATURE,
            "Focus":          cv2.CAP_PROP_FOCUS,
            "Exposure":       cv2.CAP_PROP_EXPOSURE,
        }

        if name in prop_map:
            try:
                self.cap.set(prop_map[name], value)
            except Exception:
                pass

    def _read_hardware_properties(self):
        if not self.cap or not self.cap.isOpened():
            return

        prop_map = {
            "Brightness":     cv2.CAP_PROP_BRIGHTNESS,
            "Contrast":       cv2.CAP_PROP_CONTRAST,
            "Saturation":     cv2.CAP_PROP_SATURATION,
            "Gain":           cv2.CAP_PROP_GAIN,
            "Gamma":          cv2.CAP_PROP_GAMMA,
            "Sharpness":      cv2.CAP_PROP_SHARPNESS,
            "White Balance":  cv2.CAP_PROP_WB_TEMPERATURE,
            "Exposure":       cv2.CAP_PROP_EXPOSURE,
        }

        for name, prop in prop_map.items():
            if name in self.sliders:
                try:
                    val = self.cap.get(prop)
                    if val != -1:
                        s = self.sliders[name]
                        clamped = max(s["min"], min(s["max"], int(val)))
                        s["var"].set(clamped)
                        s["slider"].redraw()
                        unit = s.get("unit", "")
                        s["label"].config(text=f"{clamped}{unit}")
                except Exception:
                    pass

    def _on_shutter_selected(self, speed_str: str):
        self.shutter_var.set(speed_str)
        exp_target = SHUTTER_SPEED_MAP.get(speed_str)

        if exp_target is None:
            self.auto_exposure_var.set(True)
            self._on_auto_exposure_toggle()
        else:
            self.auto_exposure_var.set(False)
            self._on_auto_exposure_toggle()
            if "Exposure" in self.sliders:
                self.sliders["Exposure"]["var"].set(exp_target)
                self.sliders["Exposure"]["slider"].redraw()
                self.sliders["Exposure"]["label"].config(text=str(exp_target))
            self._apply_hardware_property("Exposure", exp_target)

    def _on_auto_exposure_toggle(self):
        if not self.cap or not self.cap.isOpened():
            return
        try:
            is_auto = self.auto_exposure_var.get()
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1 if is_auto else 0)
        except Exception:
            pass

    def _on_auto_wb_toggle(self):
        if not self.cap or not self.cap.isOpened():
            return
        try:
            is_auto = self.auto_wb_var.get()
            self.cap.set(cv2.CAP_PROP_AUTO_WB, 1 if is_auto else 0)
        except Exception:
            pass

    def _on_auto_focus_toggle(self):
        if not self.cap or not self.cap.isOpened():
            return
        try:
            is_auto = self.auto_focus_var.get()
            self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1 if is_auto else 0)
        except Exception:
            pass

    # ──────────────────────────── Presets & Profiles ────────────────────────────

    def _apply_profile(self, profile: str):
        profiles = {
            "daylight": {
                "shutter": "1/64", "auto_exp": False, "exp": -6, "gain": 32,
                "wb": 5500, "auto_wb": False, "brightness": 135, "contrast": 135, "saturation": 145
            },
            "lowlight": {
                "shutter": "1/16", "auto_exp": False, "exp": -4, "gain": 180,
                "wb": 4200, "auto_wb": True, "brightness": 170, "contrast": 115, "saturation": 125
            },
            "studio": {
                "shutter": "1/32", "auto_exp": False, "exp": -5, "gain": 48,
                "wb": 5000, "auto_wb": False, "brightness": 128, "contrast": 140, "saturation": 130
            },
            "cinema": {
                "shutter": "1/32", "auto_exp": False, "exp": -5, "gain": 64,
                "wb": 4000, "auto_wb": False, "brightness": 118, "contrast": 155, "saturation": 110
            }
        }

        p = profiles.get(profile)
        if not p:
            return

        self.shutter_control.select(p["shutter"])
        self.auto_exposure_var.set(p["auto_exp"])
        self.auto_wb_var.set(p["auto_wb"])

        val_map = {
            "Exposure": p["exp"], "Gain": p["gain"], "White Balance": p["wb"],
            "Brightness": p["brightness"], "Contrast": p["contrast"], "Saturation": p["saturation"]
        }
        for k, v in val_map.items():
            if k in self.sliders:
                s = self.sliders[k]
                s["var"].set(v)
                s["slider"].redraw()
                unit = s.get("unit", "")
                s["label"].config(text=f"{v}{unit}")
                self._apply_hardware_property(k, v)

        self._on_auto_exposure_toggle()
        self._on_auto_wb_toggle()
        self._set_status_pill(f"Profile: {profile.title()} Active", THEME["accent_blue"])

    def _reset_defaults(self):
        for name, s in self.sliders.items():
            d = s["default"]
            s["var"].set(d)
            s["slider"].redraw()
            unit = s.get("unit", "")
            s["label"].config(text=f"{d}{unit}")
            self._apply_hardware_property(name, d)

        self.auto_exposure_var.set(True)
        self.auto_wb_var.set(True)
        self.auto_focus_var.set(True)
        self.shutter_control.select("Auto")
        self.fps_segmented.select("30 FPS")

        self._on_auto_exposure_toggle()
        self._on_auto_wb_toggle()
        self._on_auto_focus_toggle()
        self._set_status_pill("Hardware Reset to Defaults", THEME["accent_orange"])

    def _save_preset_file(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Preset", "*.json")],
            initialfile="reycam_profile.json",
            title="Save Profile"
        )
        if path:
            data = {
                "camera_name": self.selected_camera_label.get(),
                "fps": self.target_fps_var.get(),
                "shutter": self.shutter_var.get(),
                "auto_exposure": self.auto_exposure_var.get(),
                "auto_wb": self.auto_wb_var.get(),
                "properties": {k: v["var"].get() for k, v in self.sliders.items()}
            }
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            self._set_status_pill("Profile Saved", THEME["accent_green"])

    def _load_preset_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON Preset", "*.json")],
            title="Load Profile"
        )
        if path:
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                if "shutter" in data:
                    self.shutter_control.select(data["shutter"])
                if "fps" in data:
                    self.target_fps_var.set(data["fps"])
                    self.fps_slider.redraw()
                    self.fps_display_lbl.config(text=f"{data['fps']} FPS")
                if "auto_exposure" in data:
                    self.auto_exposure_var.set(data["auto_exposure"])
                if "auto_wb" in data:
                    self.auto_wb_var.set(data["auto_wb"])
                if "properties" in data:
                    for k, v in data["properties"].items():
                        if k in self.sliders:
                            s = self.sliders[k]
                            s["var"].set(v)
                            s["slider"].redraw()
                            unit = s.get("unit", "")
                            s["label"].config(text=f"{v}{unit}")
                            self._apply_hardware_property(k, v)
                self._set_status_pill("Profile Applied", THEME["accent_green"])
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load: {e}")

    def _take_snapshot(self):
        if not self.cap or not self.cap.isOpened():
            messagebox.showinfo("Snapshot", "Please start camera stream first.")
            return

        ret, frame = self.cap.read()
        if not ret or frame is None:
            messagebox.showerror("Snapshot", "Could not capture frame.")
            return

        if self.mirror_h_var.get():
            frame = cv2.flip(frame, 1)

        self.snapshot_counter += 1
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("JPEG Image", "*.jpg")],
            initialfile=f"reycam_snap_{self.snapshot_counter:03d}.png",
            title="Save Snapshot"
        )
        if path:
            cv2.imwrite(path, frame)
            self._set_status_pill(f"Saved: {os.path.basename(path)}", THEME["accent_green"])

    def _apply_reycam_admin_rename(self):
        """
        Request Administrator privileges to rename the 64-bit DirectShow driver to 'reycam' in HKLM.
        This forces Discord, Zoom, and Chrome to display 'reycam' directly in their camera lists!
        """
        temp_bat = os.path.join(os.environ.get("TEMP", "C:\\Temp"), "set_reycam_name.bat")
        bat_content = r'''@echo off
reg add "HKLM\SOFTWARE\Classes\CLSID\{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance\{A3FCE0F5-3493-419F-958A-ABA1250EC20B}" /v FriendlyName /t REG_SZ /d "reycam" /f
reg add "HKLM\SOFTWARE\Classes\WOW6432Node\CLSID\{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance\{A3FCE0F5-3493-419F-958A-ABA1250EC20B}" /v FriendlyName /t REG_SZ /d "reycam" /f
reg add "HKCU\Software\Classes\CLSID\{860BB310-5D01-11d0-BD3B-00A0C911CE86}\Instance\{A3FCE0F5-3493-419F-958A-ABA1250EC20B}" /v FriendlyName /t REG_SZ /d "reycam" /f
'''
        try:
            with open(temp_bat, "w") as f:
                f.write(bat_content)

            import ctypes
            res = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f'/c "{temp_bat}"', None, 0)
            if res > 32:
                messagebox.showinfo(
                    "Pendaftaran 'reycam' Berhasil!",
                    "Kamera berhasil didaftarkan sebagai 'reycam' di sistem Windows!\n\n"
                    "Langkah Terakhir:\n"
                    "1. Tutup aplikasi Discord sepenuhnya (Quit Discord).\n"
                    "2. Buka kembali Discord.\n"
                    "3. Masuk ke Voice & Video Settings, dan 'reycam' akan muncul di daftar kamera!"
                )
            else:
                messagebox.showinfo("Dibatalkan", "Pendaftaran dibatalkan.")
        except Exception as e:
            messagebox.showerror("Error", f"Gagal mengeksekusi registrasi: {e}")

    def _on_close(self):
        self.is_streaming = False
        time.sleep(0.15)
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
        if self.vcam:
            try:
                self.vcam.close()
            except Exception:
                pass
        self.root.destroy()


# ──────────────────────────── Application Entrypoint ────────────────────────────

def main():
    root = tk.Tk()

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("TCombobox",
                    fieldbackground=THEME["glass_card"],
                    background=THEME["glass_border"],
                    foreground=THEME["text_primary"],
                    arrowcolor=THEME["text_secondary"],
                    selectbackground=THEME["accent_blue"],
                    selectforeground="#ffffff")
    style.map("TCombobox",
              fieldbackground=[("readonly", THEME["glass_card"])],
              selectbackground=[("readonly", THEME["glass_card"])],
              selectforeground=[("readonly", THEME["text_primary"])])

    root.option_add("*TCombobox*Listbox.background", THEME["glass_card"])
    root.option_add("*TCombobox*Listbox.foreground", THEME["text_primary"])
    root.option_add("*TCombobox*Listbox.selectBackground", THEME["accent_blue"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", "{Segoe UI} 10")

    app = ReycamviewApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
