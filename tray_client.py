"""
Shared Clipboard — Tray Client
================================
Sistem tepsisinde çalışan, kullanıcı dostu clipboard paylaşım istemcisi.

Gereksinimler:
    pip install websockets pystray Pillow

Linux ek:
    sudo apt install xclip python3-tk
"""

import asyncio
import json
import platform
import socket
import hashlib
import subprocess
import threading
import os
import sys
import time
from datetime import datetime

try:
    import websockets
except ImportError:
    print("Gerekli: pip install websockets")
    sys.exit(1)

try:
    from pystray import Icon, Menu, MenuItem
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Gerekli: pip install pystray Pillow")
    sys.exit(1)

import tkinter as tk
from tkinter import ttk, messagebox


# ──────────────────────────────────────────────
#  Ayarlar (JSON dosyasında saklanır)
# ──────────────────────────────────────────────

def get_config_path():
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif platform.system() == "Darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    config_dir = os.path.join(base, "SharedClipboard")
    os.makedirs(config_dir, exist_ok=True)
    return os.path.join(config_dir, "config.json")


def load_config() -> dict:
    path = get_config_path()
    defaults = {
        "server_host": "",
        "server_port": 8765,
        "device_name": socket.gethostname(),
        "auto_connect": False,
        "polling_ms": 300,
    }
    try:
        with open(path, "r", encoding="utf-8") as f:
            saved = json.load(f)
            defaults.update(saved)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return defaults


def save_config(config: dict):
    path = get_config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# ──────────────────────────────────────────────
#  Clipboard işlemleri (platforma özel)
# ──────────────────────────────────────────────

class ClipboardHandler:
    def __init__(self):
        self.system = platform.system()
        if self.system == "Linux":
            session = os.environ.get("XDG_SESSION_TYPE", "").lower()
            self.linux_backend = "wayland" if session == "wayland" else "x11"

    def get(self) -> str:
        try:
            if self.system == "Darwin":
                r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
                return r.stdout
            elif self.system == "Windows":
                return self._win_get()
            elif self.system == "Linux":
                return self._linux_get()
        except Exception:
            return ""

    def set(self, text: str):
        try:
            if self.system == "Darwin":
                subprocess.run(["pbcopy"], input=text, text=True, timeout=2)
            elif self.system == "Windows":
                self._win_set(text)
            elif self.system == "Linux":
                self._linux_set(text)
        except Exception:
            pass

    def _win_get(self) -> str:
        import ctypes
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        if not u.OpenClipboard(0):
            return ""
        try:
            h = u.GetClipboardData(13)
            if not h:
                return ""
            k.GlobalLock.restype = ctypes.c_void_p
            p = k.GlobalLock(h)
            if not p:
                return ""
            try:
                return ctypes.wstring_at(p)
            finally:
                k.GlobalUnlock(h)
        finally:
            u.CloseClipboard()

    def _win_set(self, text: str):
        import ctypes
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32
        if not u.OpenClipboard(0):
            return
        try:
            u.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            h = k.GlobalAlloc(0x0002, len(data))
            k.GlobalLock.restype = ctypes.c_void_p
            p = k.GlobalLock(h)
            ctypes.memmove(p, data, len(data))
            k.GlobalUnlock(h)
            u.SetClipboardData(13, h)
        finally:
            u.CloseClipboard()

    def _linux_get(self) -> str:
        if self.linux_backend == "wayland":
            r = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=2)
        else:
            r = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=2)
        return r.stdout

    def _linux_set(self, text: str):
        if self.linux_backend == "wayland":
            subprocess.run(["wl-copy"], input=text, text=True, timeout=2)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, timeout=2)


# ──────────────────────────────────────────────
#  Tray ikonu oluşturma
# ──────────────────────────────────────────────

def create_icon_image(color="#4CAF50", status_color=None):
    """Clipboard şeklinde bir tray ikonu oluştur."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Clipboard gövdesi
    draw.rounded_rectangle([8, 12, 56, 58], radius=6, fill=color, outline="#333", width=2)

    # Clipboard klipsi (üst kısım)
    draw.rounded_rectangle([20, 4, 44, 20], radius=4, fill="#666", outline="#333", width=2)

    # Satır çizgileri (kağıt efekti)
    for y in [26, 34, 42, 50]:
        draw.line([(16, y), (48, y)], fill="#ffffff80", width=2)

    # Durum noktası (sağ alt)
    if status_color:
        draw.ellipse([44, 44, 58, 58], fill=status_color, outline="#333", width=1)

    return img


# ──────────────────────────────────────────────
#  Ayarlar penceresi (standalone — subprocess olarak çalışır)
# ──────────────────────────────────────────────
# macOS'ta tkinter main thread'de olmak zorunda; pystray de main
# thread'i NSApp.run() ile tutuyor. Aynı process'te tkinter açmak
# SIGTRAP/deadlock verir, bu yüzden ayrı bir process'te açıyoruz.

def run_settings_ui():
    config = load_config()

    root = tk.Tk()
    root.title("Shared Clipboard — Ayarlar")
    root.geometry("420x320")
    root.resizable(False, False)

    style = ttk.Style(root)
    style.configure("TLabel", padding=5)
    style.configure("TEntry", padding=5)
    style.configure("Header.TLabel", font=("", 14, "bold"))

    main_frame = ttk.Frame(root, padding=20)
    main_frame.pack(fill="both", expand=True)

    ttk.Label(main_frame, text="📋 Shared Clipboard", style="Header.TLabel").pack(anchor="w")
    ttk.Separator(main_frame, orient="horizontal").pack(fill="x", pady=(5, 15))

    form = ttk.Frame(main_frame)
    form.pack(fill="x")

    ttk.Label(form, text="Sunucu IP:").grid(row=0, column=0, sticky="w", pady=5)
    host_var = tk.StringVar(value=config["server_host"])
    ttk.Entry(form, textvariable=host_var, width=25).grid(row=0, column=1, pady=5, padx=(10, 0))

    ttk.Label(form, text="Port:").grid(row=1, column=0, sticky="w", pady=5)
    port_var = tk.StringVar(value=str(config["server_port"]))
    ttk.Entry(form, textvariable=port_var, width=10).grid(row=1, column=1, pady=5, padx=(10, 0), sticky="w")

    ttk.Label(form, text="Cihaz Adı:").grid(row=2, column=0, sticky="w", pady=5)
    name_var = tk.StringVar(value=config["device_name"])
    ttk.Entry(form, textvariable=name_var, width=25).grid(row=2, column=1, pady=5, padx=(10, 0))

    auto_var = tk.BooleanVar(value=config["auto_connect"])
    ttk.Checkbutton(main_frame, text="Başlangıçta otomatik bağlan", variable=auto_var).pack(anchor="w", pady=(15, 5))

    btn_frame = ttk.Frame(main_frame)
    btn_frame.pack(fill="x", pady=(15, 0))

    def save():
        try:
            port = int(port_var.get().strip())
        except ValueError:
            messagebox.showerror("Hata", "Port geçerli bir sayı olmalı.")
            return
        config["server_host"] = host_var.get().strip()
        config["server_port"] = port
        config["device_name"] = name_var.get().strip()
        config["auto_connect"] = auto_var.get()
        save_config(config)
        root.destroy()

    ttk.Button(btn_frame, text="Kaydet", command=save).pack(side="right")
    ttk.Button(btn_frame, text="İptal", command=root.destroy).pack(side="right", padx=(0, 5))

    root.mainloop()


# ──────────────────────────────────────────────
#  Ana uygulama
# ──────────────────────────────────────────────

class SharedClipboardApp:
    def __init__(self):
        self.config = load_config()
        self.clipboard = ClipboardHandler()
        self.connected = False
        self.connected_clients = []
        self.last_hash = ""
        self.remote_hash = ""
        self.running = True
        self.ws = None
        self.loop = None
        self.connection_thread = None
        self.history = []  # son kopyalananlar
        self._settings_proc = None

        # Tray ikonu
        self.icon = Icon(
            "SharedClipboard",
            create_icon_image(status_color="#999"),
            title="Shared Clipboard — Bağlı değil",
            menu=self._build_menu(),
        )

    def _build_menu(self):
        history_items = (
            [MenuItem("(boş)", None, enabled=False)] if not self.history
            else [MenuItem(h[:50], None, enabled=False) for h in self.history[-5:]]
        )
        return Menu(
            MenuItem("Ayarlar", self._open_settings),
            MenuItem(
                "Bağlan" if not self.connected else "Bağlantıyı Kes",
                self._toggle_from_menu,
            ),
            Menu.SEPARATOR,
            MenuItem("Son Kopyalananlar", Menu(*history_items)),
            Menu.SEPARATOR,
            MenuItem("Çıkış", self._quit),
        )

    def _update_menu(self):
        self.icon.menu = self._build_menu()

    def _update_icon(self, status):
        colors = {
            "connected": "#4CAF50",     # yeşil
            "disconnected": "#999",     # gri
            "receiving": "#2196F3",     # mavi
            "error": "#f44336",         # kırmızı
        }
        self.icon.icon = create_icon_image(status_color=colors.get(status, "#999"))

    def _open_settings(self):
        # macOS'ta tkinter'ı aynı process'te (ve non-main thread'de) açmak
        # crash'e yol açar. Settings UI'ı ayrı bir process'te başlatıyoruz.
        if self._settings_proc and self._settings_proc.poll() is None:
            return  # zaten açık
        if getattr(sys, "frozen", False):
            args = [sys.executable, "--settings"]
        else:
            args = [sys.executable, os.path.abspath(__file__), "--settings"]
        try:
            self._settings_proc = subprocess.Popen(args)
        except Exception:
            return
        threading.Thread(target=self._wait_settings, daemon=True).start()

    def _wait_settings(self):
        try:
            self._settings_proc.wait()
        except Exception:
            return
        # Settings kapandı: config'i yeniden yükle ve menüyü güncelle
        self.config = load_config()
        self._update_menu()

    def _toggle_from_menu(self):
        if self.connected:
            self.disconnect()
        else:
            self.start_connection()

    def _quit(self):
        self.running = False
        self.disconnect()
        self.icon.stop()

    # ── Bağlantı yönetimi ──

    def content_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def start_connection(self):
        if not self.config["server_host"]:
            # macOS'ta non-main thread'den tkinter messagebox crash verir;
            # native bildirim ve tray title üzerinden uyaralım.
            self.icon.title = "Shared Clipboard — Önce Ayarlar'dan IP girin"
            try:
                self.icon.notify(
                    "Önce Ayarlar'dan sunucu IP adresini girin.",
                    "Shared Clipboard",
                )
            except Exception:
                pass
            return

        self.connection_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.connection_thread.start()

    def _run_async_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._connect_loop())

    async def _connect_loop(self):
        host = self.config["server_host"]
        port = self.config["server_port"]
        url = f"ws://{host}:{port}"

        while self.running:
            try:
                async with websockets.connect(url) as ws:
                    self.ws = ws
                    self.connected = True
                    self._update_icon("connected")
                    self.icon.title = f"Shared Clipboard — {host}:{port}"
                    self._update_menu()

                    await ws.send(json.dumps({
                        "type": "register",
                        "name": self.config["device_name"],
                        "os": platform.system(),
                    }))

                    await asyncio.gather(
                        self._watch_clipboard(ws),
                        self._listen_server(ws),
                        self._keepalive(ws),
                    )
            except (ConnectionRefusedError, OSError):
                self._update_icon("error")
                self.icon.title = "Shared Clipboard — Bağlantı hatası"
                self.connected = False
                self._update_menu()
                await asyncio.sleep(5)
            except websockets.exceptions.ConnectionClosed:
                self.connected = False
                self._update_icon("disconnected")
                self._update_menu()
                await asyncio.sleep(2)

    async def _watch_clipboard(self, ws):
        interval = self.config.get("polling_ms", 300) / 1000
        while self.running and self.connected:
            try:
                current = self.clipboard.get()
                h = self.content_hash(current)
                if h != self.last_hash and h != self.remote_hash and current.strip():
                    self.last_hash = h
                    await ws.send(json.dumps({
                        "type": "clipboard",
                        "content": current,
                    }))
                    self.history.append(current)
                    if len(self.history) > 20:
                        self.history = self.history[-20:]
                    self._update_menu()
            except websockets.exceptions.ConnectionClosed:
                break
            except Exception:
                pass
            await asyncio.sleep(interval)

    async def _listen_server(self, ws):
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if data.get("type") == "clipboard_update":
                    content = data["content"]
                    h = data.get("hash", "")
                    self.remote_hash = h
                    self.last_hash = h
                    self.clipboard.set(content)
                    self.history.append(content)
                    if len(self.history) > 20:
                        self.history = self.history[-20:]
                    self._update_icon("receiving")
                    self.icon.title = f"📥 {data.get('sender', '?')}: {content[:40]}"
                    self._update_menu()
                    await asyncio.sleep(0.5)
                    self._update_icon("connected")

                elif data.get("type") == "client_list":
                    self.connected_clients = data.get("clients", [])
                    names = ", ".join(c["name"] for c in self.connected_clients)
                    self.icon.title = f"Shared Clipboard — {names}"
                    self._update_menu()

        except websockets.exceptions.ConnectionClosed:
            self.connected = False

    async def _keepalive(self, ws):
        while self.running and self.connected:
            try:
                await ws.send(json.dumps({"type": "ping"}))
            except Exception:
                break
            await asyncio.sleep(30)

    def disconnect(self):
        self.connected = False
        if self.ws:
            try:
                asyncio.run_coroutine_threadsafe(self.ws.close(), self.loop)
            except Exception:
                pass
        self._update_icon("disconnected")
        self.icon.title = "Shared Clipboard — Bağlı değil"
        self._update_menu()

    # ── Başlat ──

    def run(self):
        if self.config["auto_connect"] and self.config["server_host"]:
            self.start_connection()
        self.icon.run()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--settings":
        run_settings_ui()
        return
    app = SharedClipboardApp()
    app.run()


if __name__ == "__main__":
    main()
