"""Phone Webcam untuk Windows: HP Android jadi webcam lewat kabel USB.

Semua yang dibutuhkan sudah ada di dalam .exe ini:
  - adb (untuk komunikasi USB debugging)
  - APK aplikasi HP (dipasang otomatis)
  - driver kamera virtual Unity Capture (dipasang sekali, perlu izin Administrator)
"""
import ctypes
import os
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk

import cv2
import numpy as np
import pyvirtualcam

APP_NAME = "Phone Webcam"
PKG = "com.example.webcam"
APK_VERSION = 2            # harus sama dengan versionCode di android/app/build.gradle.kts
PHONE_PORT = 8080
LOCAL_PORT = 18080
NO_WINDOW = 0x08000000
VCAM_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                        "PhoneWebcam", "UnityCapture")
VCAM_DLL = os.path.join(VCAM_DIR, "UnityCaptureFilter64.dll")


def res_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


ADB = res_path("adb", "adb.exe")
if not os.path.exists(ADB):
    ADB = "adb"            # mode pengembangan: pakai adb dari PATH
APK = res_path("app-debug.apk")


# ----------------------------------------------------------------- ADB
def adb(*args, serial=None, timeout=20):
    cmd = [ADB] + (["-s", serial] if serial else []) + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=NO_WINDOW)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def list_devices():
    _, out = adb("devices")
    devs = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith(("*", "List", "adb server")):
            continue
        parts = line.split()
        if len(parts) >= 2:
            devs.append((parts[0], parts[1]))
    return devs


def phone_version(serial):
    _, out = adb("shell", "dumpsys", "package", PKG, serial=serial)
    m = re.search(r"versionCode=(\d+)", out)
    return int(m.group(1)) if m else None


def install_apk(serial):
    _, out = adb("install", "-r", "-g", APK, serial=serial, timeout=180)
    if "INCOMPATIBLE" in out or "signatures do not match" in out:
        adb("uninstall", PKG, serial=serial)
        _, out = adb("install", "-g", APK, serial=serial, timeout=180)
    return "Success" in out, out


def launch_phone_app(serial):
    adb("shell", "input", "keyevent", "KEYCODE_WAKEUP", serial=serial)
    adb("shell", "wm", "dismiss-keyguard", serial=serial)
    adb("shell", "am", "start", "-n", f"{PKG}/.MainActivity",
        "--ez", "autostart", "true", serial=serial)


# ------------------------------------------------------------- Stream MJPEG
def open_stream(query):
    s = socket.create_connection(("127.0.0.1", LOCAL_PORT), timeout=3)
    try:
        s.sendall(f"GET /stream?{query} HTTP/1.1\r\nHost: localhost\r\n\r\n".encode())
        f = s.makefile("rb")
        if not f.readline().startswith(b"HTTP/1.1 200"):
            raise OSError("no stream")
        while True:
            h = f.readline()
            if h in (b"\r\n", b"\n", b""):
                break
        s.settimeout(8)
        return s, f
    except Exception:
        s.close()
        return None


def read_frame(f):
    length = None
    while True:
        line = f.readline()
        if not line:
            raise EOFError
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":")[1])
        elif line in (b"\r\n", b"\n") and length is not None:
            break
    data = f.read(length)
    if len(data) < length:
        raise EOFError
    return data


def process(jpg, rot, mirror):
    img = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    if rot == 90:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif rot == 180:
        img = cv2.rotate(img, cv2.ROTATE_180)
    elif rot == 270:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if mirror:
        img = cv2.flip(img, 1)
    h, w = img.shape[:2]
    if w % 4:                       # Unity Capture butuh lebar kelipatan 4
        img = img[:, : w - (w % 4)]
    return np.ascontiguousarray(img)


# ----------------------------------------------------------- Kamera virtual
def vcam_installed():
    return os.path.exists(VCAM_DLL)


def install_vcam():
    """Salin driver ke Program Files lalu jalankan Install.bat bawaannya (minta izin Admin)."""
    src = res_path("unitycapture")
    bat = os.path.join(tempfile.gettempdir(), "phonewebcam_vcam_install.bat")
    with open(bat, "w", encoding="mbcs") as fh:
        fh.write(
            '@echo off\r\n'
            f'mkdir "{VCAM_DIR}" 2>nul\r\n'
            f'xcopy "{src}\\*" "{VCAM_DIR}\\" /E /I /Y >nul\r\n'
            f'cd /d "{VCAM_DIR}"\r\n'
            'echo.| call Install.bat\r\n'
        )
    ctypes.windll.shell32.ShellExecuteW(None, "runas", bat, None, None, 1)


# ------------------------------------------------------------------ Worker
class Worker(threading.Thread):
    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        self.stop_evt = threading.Event()
        self.restart_evt = threading.Event()

    def say(self, text, level="info"):
        self.app.post(("status", text, level))

    def run(self):
        while not self.stop_evt.is_set():
            try:
                serial = self.wait_device()
                if not serial:
                    break
                if not self.prepare(serial):
                    continue
                self.stream(serial)
            except Exception as e:                       # jaga agar thread tidak mati
                self.say(f"Error: {e}", "err")
                self.stop_evt.wait(2)
        self.app.post(("stopped",))

    def device_present(self, serial):
        return any(d == serial and s == "device" for d, s in list_devices())

    def wait_device(self):
        while not self.stop_evt.is_set():
            devs = list_devices()
            ok = [d for d, s in devs if s == "device"]
            if ok:
                return ok[0]
            self.app.post(("phone", None, None))
            if any(s == "unauthorized" for _, s in devs):
                self.say("Setujui “Izinkan USB debugging” di layar HP", "warn")
            elif any(s == "offline" for _, s in devs):
                self.say("HP offline — cabut dan colok ulang kabel USB", "warn")
            else:
                self.say("Colokkan HP lewat USB (USB debugging harus aktif)", "warn")
            self.stop_evt.wait(1.5)
        return None

    def prepare(self, serial):
        _, model = adb("shell", "getprop", "ro.product.model", serial=serial)
        self.app.post(("phone", model or serial, serial))
        ver = phone_version(serial)
        if ver is None or ver < APK_VERSION:
            self.say("Memasang aplikasi di HP…", "info")
            ok, out = install_apk(serial)
            if not ok:
                last = out.splitlines()[-1][:90] if out else "?"
                self.say(f"Gagal memasang aplikasi: {last} — izinkan “Instal via USB” di HP", "err")
                self.stop_evt.wait(4)
                return False
        adb("shell", "dumpsys", "deviceidle", "whitelist", "+" + PKG, serial=serial)
        adb("forward", f"tcp:{LOCAL_PORT}", f"tcp:{PHONE_PORT}", serial=serial)
        return True

    def stream(self, serial):
        attempts = 0
        while not self.stop_evt.is_set():
            if not self.device_present(serial):
                self.say("HP terlepas", "warn")
                return
            try:
                conn = open_stream(self.app.query())
            except OSError:
                conn = None
            if conn is None:
                if attempts % 8 == 0:
                    self.say("Membuka aplikasi di HP… (buka kunci layar jika perlu)", "warn")
                    launch_phone_app(serial)
                attempts += 1
                self.stop_evt.wait(1.0)
                continue
            attempts = 0
            self.restart_evt.clear()
            self.pump(conn)

    def pump(self, conn):
        sock, f = conn
        cam = cam_size = None
        use_v = True
        n, t0 = 0, time.time()
        try:
            self.say("Terhubung — streaming", "ok")
            while not self.stop_evt.is_set() and not self.restart_evt.is_set():
                jpg = read_frame(f)
                c = self.app.cfg
                img = process(jpg, c["rot"], c["mirror"])
                if img is None:
                    continue
                self.app.latest = img
                h, w = img.shape[:2]
                if c["vcam"] and self.app.vcam_ok and use_v:
                    try:
                        if cam is None or cam_size != (w, h):
                            if cam:
                                cam.close()
                            cam = pyvirtualcam.Camera(
                                width=w, height=h, fps=c["fps"],
                                fmt=pyvirtualcam.PixelFormat.BGR, backend="unitycapture")
                            cam_size = (w, h)
                        cam.send(img)
                    except Exception as e:
                        use_v = False
                        self.say(f"Kamera virtual gagal: {e}", "err")
                n += 1
                now = time.time()
                if now - t0 >= 1:
                    extra = " · kamera virtual aktif" if cam else ""
                    self.app.post(("stats", f"{n / (now - t0):.0f} FPS · {w}×{h}{extra}"))
                    n, t0 = 0, now
        except (OSError, EOFError):
            if not self.stop_evt.is_set() and not self.restart_evt.is_set():
                self.say("Koneksi terputus — mencoba lagi…", "warn")
                self.stop_evt.wait(1)
        finally:
            if cam:
                try:
                    cam.close()
                except Exception:
                    pass
            for x in (f, sock):
                try:
                    x.close()
                except Exception:
                    pass


# ---------------------------------------------------------------------- UI
COLORS = {"info": "#444444", "ok": "#0a7d33", "warn": "#b36b00", "err": "#c62828"}


class App:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        r = self.root = tk.Tk()
        r.title(APP_NAME)
        self.sc = max(1.0, r.winfo_fpixels("1i") / 96)
        S = self.S = lambda x: int(x * self.sc)
        r.geometry(f"{S(840)}x{S(500)}")
        r.minsize(S(840), S(500))
        try:
            ttk.Style().theme_use("vista")
        except tk.TclError:
            pass
        ttk.Style().configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=S(8))

        self.q = queue.Queue()
        self.worker = None
        self.latest = None
        self.photo = None
        self.serial = None
        self.vcam_ok = vcam_installed()
        self._tick_n = 0
        self._restart_job = None
        self.cfg = None

        self.v_cam = tk.StringVar(value="Belakang")
        self.v_res = tk.StringVar(value="720p")
        self.v_fps = tk.StringVar(value="30")
        self.v_q = tk.DoubleVar(value=80)
        self.v_rot = tk.StringVar(value="0°")
        self.v_mirror = tk.BooleanVar(value=False)
        self.v_vcam = tk.BooleanVar(value=True)
        self.v_prev = tk.BooleanVar(value=True)
        self.v_phone = tk.StringVar(value="—")

        self.build()
        for v in (self.v_cam, self.v_res, self.v_fps, self.v_q, self.v_rot,
                  self.v_mirror, self.v_vcam):
            v.trace_add("write", self.sync)
        self.sync()
        r.protocol("WM_DELETE_WINDOW", self.on_close)
        r.after(40, self.tick)

    # ---- tata letak
    def build(self):
        S, r = self.S, self.root
        left = ttk.Frame(r, padding=S(12))
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(r, padding=(0, S(12), S(12), S(12)))
        right.pack(side="right", fill="y")

        self.cw, self.ch = S(480), S(270)
        self.canvas = tk.Canvas(left, width=self.cw, height=self.ch, bg="black",
                                highlightthickness=0)
        self.canvas.pack()
        self.hint = self.canvas.create_text(self.cw // 2, self.ch // 2, fill="#9a9a9a",
                                            text="Pratinjau akan tampil di sini",
                                            font=("Segoe UI", 11))
        self.img_id = None
        self.stats = ttk.Label(left, text="", foreground="#666666")
        self.stats.pack(anchor="w", pady=(S(6), 0))
        self.status = tk.Label(left, text="Siap. Tekan Mulai.", anchor="w", justify="left",
                               wraplength=self.cw, fg=COLORS["info"], font=("Segoe UI", 10))
        self.status.pack(anchor="w", fill="x", pady=(S(8), 0))
        ttk.Checkbutton(left, text="Tampilkan pratinjau", variable=self.v_prev,
                        command=self.clear_preview).pack(anchor="w", pady=(S(8), 0))

        # Koneksi
        box = ttk.LabelFrame(right, text="Koneksi", padding=S(8))
        box.pack(fill="x")
        ttk.Label(box, text="HP:").grid(row=0, column=0, sticky="w")
        ttk.Label(box, textvariable=self.v_phone).grid(row=0, column=1, sticky="w", padx=S(6))
        ttk.Label(box, text="Kamera virtual:").grid(row=1, column=0, sticky="w")
        self.lbl_vcam = tk.Label(box, text="", font=("Segoe UI", 9, "bold"))
        self.lbl_vcam.grid(row=1, column=1, sticky="w", padx=S(6))
        self.btn_vcam = ttk.Button(box, text="Pasang kamera virtual", command=self.on_install_vcam)
        self.btn_vcam.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(S(6), 0))

        # Kamera
        cam = ttk.LabelFrame(right, text="Kamera HP", padding=S(8))
        cam.pack(fill="x", pady=(S(10), 0))
        self.combo(cam, 0, "Kamera", self.v_cam, ["Belakang", "Depan"])
        self.combo(cam, 1, "Resolusi", self.v_res, ["480p", "720p", "1080p"])
        self.combo(cam, 2, "FPS", self.v_fps, ["15", "24", "30"])
        ttk.Label(cam, text="Kualitas").grid(row=3, column=0, sticky="w", pady=S(2))
        self.lbl_q = ttk.Label(cam, text="80")
        self.lbl_q.grid(row=3, column=2, padx=S(6))
        ttk.Scale(cam, from_=50, to=95, variable=self.v_q, length=S(110),
                  command=lambda v: self.lbl_q.config(text=str(int(float(v))))
                  ).grid(row=3, column=1, sticky="ew")

        # Tampilan
        disp = ttk.LabelFrame(right, text="Tampilan", padding=S(8))
        disp.pack(fill="x", pady=(S(10), 0))
        self.combo(disp, 0, "Rotasi", self.v_rot, ["0°", "90°", "180°", "270°"])
        ttk.Checkbutton(disp, text="Cermin (mirror)", variable=self.v_mirror
                        ).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(disp, text="Kirim ke kamera virtual", variable=self.v_vcam
                        ).grid(row=2, column=0, columnspan=2, sticky="w")

        self.btn = ttk.Button(right, text="Mulai", style="Big.TButton", command=self.toggle)
        self.btn.pack(fill="x", pady=(S(14), 0))
        self.refresh_vcam_ui()

    def combo(self, parent, row, label, var, values):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=self.S(2))
        ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=11
                     ).grid(row=row, column=1, columnspan=2, sticky="ew", padx=self.S(6))

    # ---- pengaturan
    def sync(self, *_):
        cfg = dict(
            cam="front" if self.v_cam.get() == "Depan" else "back",
            h={"480p": 480, "720p": 720, "1080p": 1080}[self.v_res.get()],
            fps=int(self.v_fps.get()),
            q=int(round(self.v_q.get())),
            rot=int(self.v_rot.get().rstrip("°")),
            mirror=self.v_mirror.get(),
            vcam=self.v_vcam.get(),
        )
        old, self.cfg = self.cfg, cfg
        if old and self.worker and any(old[k] != cfg[k] for k in ("cam", "h", "fps", "q")):
            if self._restart_job:
                self.root.after_cancel(self._restart_job)
            self._restart_job = self.root.after(500, self._do_restart)

    def _do_restart(self):
        self._restart_job = None
        if self.worker:
            self.worker.restart_evt.set()

    def query(self):
        c = self.cfg
        return f"cam={c['cam']}&h={c['h']}&fps={c['fps']}&q={c['q']}"

    def post(self, msg):
        self.q.put(msg)

    # ---- aksi
    def toggle(self):
        if self.worker:
            self.worker.stop_evt.set()
            self.btn.config(state="disabled", text="Menghentikan…")
            return
        self.worker = Worker(self)
        self.worker.start()
        self.btn.config(text="Berhenti")
        self.set_status("Mencari HP…", "info")

    def on_install_vcam(self):
        install_vcam()
        self.set_status("Menunggu instalasi kamera virtual (jendela Administrator)…", "info")

    def set_status(self, text, level="info"):
        self.status.config(text=text, fg=COLORS.get(level, COLORS["info"]))

    def clear_preview(self):
        if not self.v_prev.get():
            self.latest = None
            self.show_idle()

    def show_idle(self):
        if self.img_id:
            self.canvas.delete(self.img_id)
            self.img_id = None
        self.canvas.itemconfig(self.hint, state="normal")

    def refresh_vcam_ui(self):
        if self.vcam_ok:
            self.lbl_vcam.config(text="Terpasang", fg=COLORS["ok"])
            self.btn_vcam.config(text="Pasang ulang")
        else:
            self.lbl_vcam.config(text="Belum terpasang", fg=COLORS["warn"])
            self.btn_vcam.config(text="Pasang kamera virtual")

    def draw(self):
        img = self.latest
        if img is None:
            return
        h, w = img.shape[:2]
        s = min(self.cw / w, self.ch / h)
        nw, nh = max(1, int(w * s)), max(1, int(h * s))
        rgb = cv2.cvtColor(cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA),
                           cv2.COLOR_BGR2RGB)
        self.photo = tk.PhotoImage(data=b"P6 %d %d 255\n" % (nw, nh) + rgb.tobytes())
        self.canvas.itemconfig(self.hint, state="hidden")
        if self.img_id:
            self.canvas.itemconfig(self.img_id, image=self.photo)
        else:
            self.img_id = self.canvas.create_image(self.cw // 2, self.ch // 2, image=self.photo)

    def tick(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "status":
                    self.set_status(m[1], m[2])
                elif m[0] == "phone":
                    self.v_phone.set(m[1] or "—")
                    self.serial = m[2]
                elif m[0] == "stats":
                    self.stats.config(text=m[1])
                elif m[0] == "stopped":
                    self.worker = None
                    self.latest = None
                    self.show_idle()
                    self.stats.config(text="")
                    self.btn.config(state="normal", text="Mulai")
                    self.set_status("Berhenti.", "info")
        except queue.Empty:
            pass
        if self.v_prev.get():
            self.draw()
        self._tick_n += 1
        if self._tick_n % 25 == 0:
            now = vcam_installed()
            if now != self.vcam_ok:
                self.vcam_ok = now
                self.refresh_vcam_ui()
        self.root.after(40, self.tick)

    def on_close(self):
        if self.worker:
            self.worker.stop_evt.set()
        serial = self.serial

        def bye():
            if serial:
                adb("shell", "am", "stopservice", "-n", f"{PKG}/.WebcamService",
                    serial=serial, timeout=6)
            adb("forward", "--remove", f"tcp:{LOCAL_PORT}", timeout=6)
            adb("kill-server", timeout=6)      # supaya adb.exe sementara tidak terkunci

        t = threading.Thread(target=bye, daemon=True)
        t.start()
        t.join(8)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    App().run()
