"""
Shared Clipboard — Tray Client (LAN-only mesh)
================================================
Sistem tepsisinde çalışan clipboard paylaşım istemcisi.
Sunucu yok: her cihaz aynı Wi-Fi'daki diğer cihazları mDNS/Bonjour ile
otomatik bulur ve birbirine doğrudan bağlanır.

Gereksinimler:
    pip install websockets pystray Pillow zeroconf

Linux ek:
    sudo apt install xclip python3-tk
"""

__version__ = "0.1.2"

import asyncio
import json
import locale
import platform
import socket
import hashlib
import subprocess
import threading
import time
import os
import sys
import uuid
from datetime import datetime

try:
    import websockets
except ImportError:
    print("Gerekli: pip install websockets")
    sys.exit(1)

try:
    from pystray import Icon, Menu, MenuItem
    from PIL import Image, ImageDraw
except ImportError:
    print("Gerekli: pip install pystray Pillow")
    sys.exit(1)

try:
    from zeroconf import ServiceInfo, ServiceStateChange, IPVersion
    from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser
except ImportError:
    print("Gerekli: pip install zeroconf")
    sys.exit(1)

import tkinter as tk
from tkinter import ttk, messagebox


SERVICE_TYPE = "_sharedclipboard._tcp.local."


def _log_path():
    """macOS .app içinden stdout görünmediği için dosyaya log yazıyoruz."""
    if platform.system() == "Windows":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif platform.system() == "Darwin":
        base = os.path.expanduser("~/Library/Logs")
    else:
        base = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    log_dir = os.path.join(base, "SharedClipboard")
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        pass
    return os.path.join(log_dir, "tray_client.log")


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def sanitize_label(name: str) -> str:
    """mDNS service label için güvenli karakter seti."""
    out = []
    for c in name:
        if c.isalnum() or c in "-_":
            out.append(c)
        elif c == " ":
            out.append("-")
        # diğer karakterler atlanır
    cleaned = "".join(out).strip("-_")
    return cleaned or "device"


# ──────────────────────────────────────────────
#  i18n — basit, dosya bağımsız sözlük tabanlı
# ──────────────────────────────────────────────

LANGUAGES = {
    "tr": {
        "lang_name": "Türkçe",
        # Settings penceresi
        "settings_title": "Shared Clipboard — Ayarlar",
        "settings_header": "📋 Shared Clipboard",
        "settings_subtitle": "Aynı Wi-Fi'daki cihazlar otomatik bulunur.",
        "settings_device_name": "Cihaz Adı:",
        "settings_language": "Dil:",
        "settings_auto_start": "Açılışta otomatik yayına başla",
        "settings_save": "Kaydet",
        "settings_cancel": "İptal",
        "settings_error_title": "Hata",
        "settings_error_empty_name": "Cihaz adı boş olamaz.",
        # Tray menüsü
        "menu_settings": "Ayarlar",
        "menu_history": "Son Kopyalananlar",
        "menu_clear_history": "Geçmişi Temizle",
        "menu_quit": "Çıkış",
        "menu_history_empty": "(boş)",
        "menu_peers_none": "Bağlı cihaz yok",
        "menu_peers_count": "Bağlı cihazlar: {n}",
        "menu_no_peers_found": "(kimse bulunamadı)",
        # Tray tooltip / başlık
        "tooltip_offline": "Shared Clipboard v{v} — Yayında değil",
        "tooltip_device": "Shared Clipboard — {name}",
        "tooltip_peers": "Shared Clipboard — {n} cihaz bağlı",
        "tooltip_received": "📥 {sender}: {content}",
    },
    "en": {
        "lang_name": "English",
        "settings_title": "Shared Clipboard — Settings",
        "settings_header": "📋 Shared Clipboard",
        "settings_subtitle": "Devices on the same Wi-Fi are discovered automatically.",
        "settings_device_name": "Device name:",
        "settings_language": "Language:",
        "settings_auto_start": "Start broadcasting automatically on launch",
        "settings_save": "Save",
        "settings_cancel": "Cancel",
        "settings_error_title": "Error",
        "settings_error_empty_name": "Device name cannot be empty.",
        "menu_settings": "Settings",
        "menu_history": "Recently Copied",
        "menu_clear_history": "Clear History",
        "menu_quit": "Quit",
        "menu_history_empty": "(empty)",
        "menu_peers_none": "No devices connected",
        "menu_peers_count": "Connected devices: {n}",
        "menu_no_peers_found": "(none found)",
        "tooltip_offline": "Shared Clipboard v{v} — Offline",
        "tooltip_device": "Shared Clipboard — {name}",
        "tooltip_peers": "Shared Clipboard — {n} devices connected",
        "tooltip_received": "📥 {sender}: {content}",
    },
}

DEFAULT_LANG = "en"
_current_lang = DEFAULT_LANG


def detect_default_lang() -> str:
    """Sistem locale'i tr* ile başlıyorsa Türkçe, aksi halde İngilizce."""
    candidates = [
        os.environ.get("LANG"),
        os.environ.get("LC_ALL"),
        os.environ.get("LC_MESSAGES"),
    ]
    try:
        candidates.append(locale.getlocale()[0])
    except Exception:
        pass
    for c in candidates:
        if c and c.lower().startswith("tr"):
            return "tr"
    return "en"


def set_lang(code: str):
    global _current_lang
    if code in LANGUAGES:
        _current_lang = code


def current_lang() -> str:
    return _current_lang


def t(key: str, **kwargs) -> str:
    table = LANGUAGES.get(_current_lang, LANGUAGES[DEFAULT_LANG])
    s = table.get(key) or LANGUAGES[DEFAULT_LANG].get(key, key)
    if kwargs:
        try:
            return s.format(**kwargs)
        except Exception:
            return s
    return s


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
        "device_name": socket.gethostname(),
        "auto_start": True,
        "polling_ms": 300,
        "language": detect_default_lang(),
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
                return self._mac_get()
            elif self.system == "Windows":
                return self._win_get()
            elif self.system == "Linux":
                return self._linux_get()
        except Exception as e:
            try:
                log(f"clipboard get hatası ({self.system}): {e!r}")
            except Exception:
                pass
            return ""

    def set(self, text: str):
        try:
            if self.system == "Darwin":
                self._mac_set(text)
            elif self.system == "Windows":
                self._win_set(text)
            elif self.system == "Linux":
                self._linux_set(text)
        except Exception as e:
            try:
                log(f"clipboard set hatası ({self.system}): {e!r}")
            except Exception:
                pass

    @staticmethod
    def _mac_get() -> str:
        # NSPasteboard API'si encoding-bağımsız NSString döner.
        # `pbpaste`/`pbcopy` .app içinde LANG eksik olunca MacRoman'a düşüp
        # Türkçe karakterleri "?" yapıyor — bunu komple bypass ediyoruz.
        from AppKit import NSPasteboard
        pb = NSPasteboard.generalPasteboard()
        s = pb.stringForType_("public.utf8-plain-text")
        return str(s) if s is not None else ""

    @staticmethod
    def _mac_set(text: str):
        from AppKit import NSPasteboard
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents()
        pb.setString_forType_(text, "public.utf8-plain-text")

    @staticmethod
    def _win_setup_ctypes():
        """Win32 API çağrıları için argtypes/restype tanımla.
        Belirtilmezse 64-bit handle'lar 32-bit int'e truncate olur ve
        GlobalLock NULL döner — clipboard sessizce çalışmaz."""
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        k = ctypes.windll.kernel32

        u.OpenClipboard.argtypes = [wintypes.HWND]
        u.OpenClipboard.restype = wintypes.BOOL
        u.CloseClipboard.argtypes = []
        u.CloseClipboard.restype = wintypes.BOOL
        u.EmptyClipboard.argtypes = []
        u.EmptyClipboard.restype = wintypes.BOOL
        u.GetClipboardData.argtypes = [wintypes.UINT]
        u.GetClipboardData.restype = wintypes.HANDLE
        u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
        u.SetClipboardData.restype = wintypes.HANDLE

        k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        k.GlobalAlloc.restype = wintypes.HGLOBAL
        k.GlobalLock.argtypes = [wintypes.HGLOBAL]
        k.GlobalLock.restype = wintypes.LPVOID
        k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        k.GlobalUnlock.restype = wintypes.BOOL
        k.GlobalSize.argtypes = [wintypes.HGLOBAL]
        k.GlobalSize.restype = ctypes.c_size_t
        return u, k

    @staticmethod
    def _win_open_clipboard(u):
        """Başka bir process panoyu kilitlemiş olabilir — birkaç kez dene."""
        for _ in range(10):
            if u.OpenClipboard(None):
                return True
            time.sleep(0.03)
        return False

    def _win_get(self) -> str:
        import ctypes
        u, k = self._win_setup_ctypes()
        CF_UNICODETEXT = 13

        if not self._win_open_clipboard(u):
            return ""
        try:
            h = u.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return ""
            p = k.GlobalLock(h)
            if not p:
                return ""
            try:
                size = k.GlobalSize(h)
                # GlobalSize byte cinsinden; UTF-16 = 2 byte/char, son null hariç
                if size:
                    chars = max(0, size // 2 - 1)
                    return ctypes.wstring_at(p, chars)
                return ctypes.wstring_at(p)
            finally:
                k.GlobalUnlock(h)
        finally:
            u.CloseClipboard()

    def _win_set(self, text: str):
        import ctypes
        u, k = self._win_setup_ctypes()
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002

        data = text.encode("utf-16-le") + b"\x00\x00"

        if not self._win_open_clipboard(u):
            return
        try:
            u.EmptyClipboard()
            h = k.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                return
            p = k.GlobalLock(h)
            if not p:
                return
            ctypes.memmove(p, data, len(data))
            k.GlobalUnlock(h)
            # SetClipboardData başarısızsa h'i bizim free etmemiz lazım;
            # başarılıysa sahipliği sisteme geçer.
            if not u.SetClipboardData(CF_UNICODETEXT, h):
                free = ctypes.windll.kernel32.GlobalFree
                free.argtypes = [ctypes.c_void_p]
                free.restype = ctypes.c_void_p
                free(h)
        finally:
            u.CloseClipboard()

    def _linux_get(self) -> str:
        if self.linux_backend == "wayland":
            r = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, timeout=2)
        else:
            r = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, timeout=2)
        return r.stdout.decode("utf-8", errors="replace")

    def _linux_set(self, text: str):
        data = text.encode("utf-8")
        if self.linux_backend == "wayland":
            subprocess.run(["wl-copy"], input=data, timeout=2)
        else:
            subprocess.run(["xclip", "-selection", "clipboard"], input=data, timeout=2)


# ──────────────────────────────────────────────
#  Tray ikonu oluşturma
# ──────────────────────────────────────────────

def create_icon_image(color="#4CAF50", status_color=None):
    """Clipboard şeklinde bir tray ikonu oluştur."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([8, 12, 56, 58], radius=6, fill=color, outline="#333", width=2)
    draw.rounded_rectangle([20, 4, 44, 20], radius=4, fill="#666", outline="#333", width=2)

    for y in [26, 34, 42, 50]:
        draw.line([(16, y), (48, y)], fill="#ffffff80", width=2)

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
    set_lang(config.get("language", DEFAULT_LANG))

    root = tk.Tk()
    root.title(t("settings_title"))
    root.geometry("440x300")
    root.resizable(False, False)

    style = ttk.Style(root)
    style.configure("TLabel", padding=5)
    style.configure("TEntry", padding=5)
    style.configure("Header.TLabel", font=("", 14, "bold"))

    main_frame = ttk.Frame(root, padding=20)
    main_frame.pack(fill="both", expand=True)

    ttk.Label(main_frame, text=t("settings_header"), style="Header.TLabel").pack(anchor="w")
    ttk.Label(main_frame, text=t("settings_subtitle")).pack(anchor="w")
    ttk.Separator(main_frame, orient="horizontal").pack(fill="x", pady=(5, 15))

    form = ttk.Frame(main_frame)
    form.pack(fill="x")

    ttk.Label(form, text=t("settings_device_name")).grid(row=0, column=0, sticky="w", pady=5)
    name_var = tk.StringVar(value=config["device_name"])
    ttk.Entry(form, textvariable=name_var, width=28).grid(row=0, column=1, pady=5, padx=(10, 0))

    ttk.Label(form, text=t("settings_language")).grid(row=1, column=0, sticky="w", pady=5)
    lang_display = {code: data["lang_name"] for code, data in LANGUAGES.items()}
    display_to_code = {v: k for k, v in lang_display.items()}
    current_code = config.get("language", DEFAULT_LANG)
    lang_var = tk.StringVar(value=lang_display.get(current_code, lang_display[DEFAULT_LANG]))
    ttk.Combobox(
        form,
        textvariable=lang_var,
        values=list(lang_display.values()),
        state="readonly",
        width=26,
    ).grid(row=1, column=1, pady=5, padx=(10, 0))

    auto_var = tk.BooleanVar(value=config.get("auto_start", True))
    ttk.Checkbutton(main_frame, text=t("settings_auto_start"), variable=auto_var).pack(anchor="w", pady=(15, 5))

    btn_frame = ttk.Frame(main_frame)
    btn_frame.pack(fill="x", pady=(15, 0))

    def save():
        name = name_var.get().strip()
        if not name:
            messagebox.showerror(t("settings_error_title"), t("settings_error_empty_name"))
            return
        config["device_name"] = name
        config["auto_start"] = auto_var.get()
        config["language"] = display_to_code.get(lang_var.get(), DEFAULT_LANG)
        save_config(config)
        root.destroy()

    ttk.Button(btn_frame, text=t("settings_save"), command=save).pack(side="right")
    ttk.Button(btn_frame, text=t("settings_cancel"), command=root.destroy).pack(side="right", padx=(0, 5))

    root.mainloop()


# ──────────────────────────────────────────────
#  PeerNode — mesh düğümü (mDNS + WebSocket server/client)
# ──────────────────────────────────────────────

def get_local_ip() -> str:
    """LAN IP'sini al (loopback değil)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class PeerNode:
    """
    Her cihazda çalışan mesh düğümü:
      - WebSocket server olarak gelen bağlantıları kabul eder
      - mDNS ile kendini yayınlar (_sharedclipboard._tcp.local.)
      - mDNS ile diğerlerini arar, küçük peer_id büyüğe outbound bağlanır
      - Yeni clipboard mesajını tüm bağlı peer'lere yayar
    """

    def __init__(self, device_name: str, on_remote_clipboard, on_peers_changed):
        self.device_name = device_name
        self.peer_id = uuid.uuid4().hex
        self.on_remote_clipboard = on_remote_clipboard  # (content, sender_name)
        self.on_peers_changed = on_peers_changed        # (list[str])
        self.peers = {}  # peer_id -> {"ws": ws, "name": str}
        self.aiozc = None
        self.service_info = None
        self.browser = None
        self.server = None
        self.port = None
        self.loop = None
        self._running = False

    def peer_names(self):
        return [p["name"] for p in self.peers.values()]

    async def start(self):
        self.loop = asyncio.get_running_loop()
        self._running = True

        # WebSocket server — 0 = OS uygun bir port atar
        self.server = await websockets.serve(self._handle_inbound, "0.0.0.0", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        log(f"WebSocket server :{self.port} dinlemede")

        # mDNS advertise + browse
        self.aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        ip = get_local_ip()
        # mDNS label'lar nokta/özel karakter alamaz; cihaz adını sanitize et.
        safe_label = f"{sanitize_label(self.device_name)}-{self.peer_id[:6]}"
        service_name = f"{safe_label}.{SERVICE_TYPE}"
        self.service_info = ServiceInfo(
            SERVICE_TYPE,
            service_name,
            addresses=[socket.inet_aton(ip)],
            port=self.port,
            properties={
                b"name": self.device_name.encode("utf-8"),
                b"id": self.peer_id.encode("utf-8"),
                b"os": platform.system().encode("utf-8"),
            },
            server=f"{safe_label}.local.",
        )
        try:
            await self.aiozc.async_register_service(self.service_info)
            log(f"mDNS yayını: {service_name} -> {ip}:{self.port}")
        except Exception as e:
            log(f"zeroconf register HATASI: {e!r}")
            raise

        self.browser = AsyncServiceBrowser(
            self.aiozc.zeroconf,
            SERVICE_TYPE,
            handlers=[self._on_service_state_change],
        )
        log(f"mDNS browse başladı (peer_id={self.peer_id[:8]})")

    def _on_service_state_change(self, *, zeroconf, service_type, name, state_change):
        # Zeroconf >=0.130 callback'i keyword-only argümanlarla çağırır.
        if state_change == ServiceStateChange.Added:
            asyncio.run_coroutine_threadsafe(
                self._handle_discovered(service_type, name),
                self.loop,
            )

    async def _handle_discovered(self, service_type, name):
        log(f"mDNS keşfedildi: {name}")
        try:
            info = await self.aiozc.async_get_service_info(service_type, name, timeout=3000)
        except Exception as e:
            log(f"get_service_info hatası: {e!r}")
            return
        if not info or not info.properties:
            log(f"{name} için boş info/properties")
            return

        peer_id = info.properties.get(b"id", b"").decode("utf-8", errors="replace")
        if not peer_id or peer_id == self.peer_id:
            return
        # Tie-break: küçük peer_id, büyüğe bağlanır (her çift için tek bağlantı).
        if self.peer_id >= peer_id:
            log(f"{peer_id[:8]} bana bağlanacak (tie-break)")
            return
        if peer_id in self.peers:
            return

        addresses = []
        try:
            addresses = info.parsed_addresses()
        except Exception:
            pass
        if not addresses:
            for a in info.addresses or []:
                try:
                    addresses.append(socket.inet_ntoa(a))
                except Exception:
                    pass
        if not addresses:
            log(f"{name} için adres çözülemedi")
            return
        host = addresses[0]
        port = info.port
        peer_name = info.properties.get(b"name", b"?").decode("utf-8", errors="replace")

        log(f"outbound bağlanılıyor: {peer_name} @ {host}:{port}")
        try:
            ws = await asyncio.wait_for(
                websockets.connect(f"ws://{host}:{port}"),
                timeout=5,
            )
        except Exception as e:
            log(f"outbound başarısız: {e!r}")
            return

        try:
            await ws.send(json.dumps({
                "type": "hello",
                "id": self.peer_id,
                "name": self.device_name,
            }))
        except Exception:
            await ws.close()
            return

        log(f"outbound bağlandı: {peer_name} ({peer_id[:8]})")
        self._add_peer(peer_id, ws, peer_name)
        try:
            async for raw in ws:
                self._dispatch_message(raw, peer_id)
        except Exception:
            pass
        finally:
            log(f"outbound koptu: {peer_name}")
            self._remove_peer(peer_id)

    async def _handle_inbound(self, ws):
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=5)
            data = json.loads(first)
        except Exception:
            await ws.close()
            return

        if data.get("type") != "hello":
            await ws.close()
            return

        peer_id = data.get("id", "")
        peer_name = data.get("name", "?")
        if not peer_id or peer_id == self.peer_id:
            await ws.close()
            return
        if peer_id in self.peers:
            await ws.close()
            return

        log(f"inbound bağlandı: {peer_name} ({peer_id[:8]})")
        self._add_peer(peer_id, ws, peer_name)
        try:
            async for raw in ws:
                self._dispatch_message(raw, peer_id)
        except Exception:
            pass
        finally:
            log(f"inbound koptu: {peer_name}")
            self._remove_peer(peer_id)

    def _add_peer(self, peer_id, ws, name):
        self.peers[peer_id] = {"ws": ws, "name": name}
        try:
            self.on_peers_changed(self.peer_names())
        except Exception:
            pass

    def _remove_peer(self, peer_id):
        if self.peers.pop(peer_id, None) is not None:
            try:
                self.on_peers_changed(self.peer_names())
            except Exception:
                pass

    def _dispatch_message(self, raw, peer_id):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if data.get("type") == "clipboard":
            content = data.get("content", "")
            sender = self.peers.get(peer_id, {}).get("name", "?")
            try:
                self.on_remote_clipboard(content, sender)
            except Exception:
                pass

    async def broadcast_clipboard(self, content: str):
        if not self.peers:
            return
        msg = json.dumps({
            "type": "clipboard",
            "content": content,
            "sender": self.device_name,
        })
        dead = []
        for pid, info in list(self.peers.items()):
            try:
                await info["ws"].send(msg)
            except Exception:
                dead.append(pid)
        for pid in dead:
            self._remove_peer(pid)

    async def stop(self):
        self._running = False
        if self.browser:
            try:
                await self.browser.async_cancel()
            except Exception:
                pass
        if self.aiozc:
            try:
                if self.service_info:
                    await self.aiozc.async_unregister_service(self.service_info)
                await self.aiozc.async_close()
            except Exception:
                pass
        for info in list(self.peers.values()):
            try:
                await info["ws"].close()
            except Exception:
                pass
        self.peers.clear()
        if self.server:
            self.server.close()
            try:
                await self.server.wait_closed()
            except Exception:
                pass


# ──────────────────────────────────────────────
#  Ana uygulama
# ──────────────────────────────────────────────

class SharedClipboardApp:
    def __init__(self):
        self.config = load_config()
        set_lang(self.config.get("language", DEFAULT_LANG))
        self.clipboard = ClipboardHandler()
        self.peer_names = []
        self.last_hash = ""
        self.remote_hash = ""
        self.running = True
        self.history = []
        self._settings_proc = None
        self.node = None
        self.loop = None
        self.loop_thread = None

        # Menu'ya callable ver: pystray menü her açıldığında çağırır,
        # bu sayede peer listesi / history dinamik olarak güncellenir.
        # (icon.menu = ... ataması macOS'ta NSMenu'yu rebuild etmez.)
        self.icon = Icon(
            "SharedClipboard",
            create_icon_image(status_color="#999"),
            title=t("tooltip_offline", v=__version__),
            menu=Menu(self._menu_items),
        )

    # ── Menü ──

    def _menu_items(self):
        """pystray menü her açıldığında çağırır; güncel state'i render eder."""
        if self.peer_names:
            peers_label = t("menu_peers_count", n=len(self.peer_names))
            peer_submenu = Menu(
                *[MenuItem(n, None, enabled=False) for n in self.peer_names]
            )
        else:
            peers_label = t("menu_peers_none")
            peer_submenu = Menu(MenuItem(t("menu_no_peers_found"), None, enabled=False))

        history_submenu = Menu(*self._history_items())

        return (
            MenuItem(f"Shared Clipboard v{__version__}", None, enabled=False),
            Menu.SEPARATOR,
            MenuItem(t("menu_settings"), self._open_settings),
            Menu.SEPARATOR,
            MenuItem(peers_label, peer_submenu),
            MenuItem(t("menu_history"), history_submenu),
            Menu.SEPARATOR,
            MenuItem(t("menu_quit"), self._quit),
        )

    def _history_items(self):
        if not self.history:
            return [MenuItem(t("menu_history_empty"), None, enabled=False)]
        items = []
        # En yenisi en üstte; son 10 kayıt
        for entry in reversed(self.history[-10:]):
            label = entry.replace("\r", "").replace("\n", " ⏎ ")
            if len(label) > 60:
                label = label[:57] + "..."
            items.append(MenuItem(label, self._make_history_action(entry)))
        items.append(Menu.SEPARATOR)
        items.append(MenuItem(t("menu_clear_history"), self._clear_history))
        return items

    def _make_history_action(self, entry):
        # pystray action'ı 0/1/2 arg almalı; closure ile entry'yi yakalıyoruz.
        def handler(icon, item):
            self._reuse_history(entry)
        return handler

    def _reuse_history(self, content: str):
        """Geçmişten bir item seçildi: panoya yaz ve diğer cihazlara yay."""
        h = self._content_hash(content)
        # Kendi watch loop'umuzun aynı içeriği tekrar broadcast etmesini önle
        self.last_hash = h
        self.clipboard.set(content)
        # Async loop'a broadcast iş ekle (menü callback'i UI thread'inde)
        if self.node and self.loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.node.broadcast_clipboard(content),
                    self.loop,
                )
            except Exception:
                pass
        self._update_icon("receiving")
        threading.Timer(0.4, lambda: self._update_icon("online")).start()

    def _clear_history(self):
        self.history.clear()
        self._update_menu()

    def _update_menu(self):
        # Menu factory pattern kullandığımız için item'lar her açılışta
        # yeniden üretiliyor. update_menu() backend cache'ini geçersiz kılar
        # (özellikle Linux/Windows için gerekli; macOS no-op).
        try:
            self.icon.update_menu()
        except Exception:
            pass

    def _update_icon(self, status):
        colors = {
            "online": "#4CAF50",
            "offline": "#999",
            "receiving": "#2196F3",
            "error": "#f44336",
        }
        try:
            self.icon.icon = create_icon_image(status_color=colors.get(status, "#999"))
        except Exception:
            pass

    # ── Menü eylemleri ──

    def _open_settings(self):
        if self._settings_proc and self._settings_proc.poll() is None:
            return
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
        new_config = load_config()
        name_changed = new_config.get("device_name") != self.config.get("device_name")
        lang_changed = new_config.get("language") != self.config.get("language")
        self.config = new_config
        if lang_changed:
            set_lang(self.config.get("language", DEFAULT_LANG))
            self._refresh_title()
        if name_changed:
            self._restart_node()
        self._update_menu()

    def _refresh_title(self):
        """Mevcut state'e göre tray tooltip'ini tekrar üretir (dil değişiminden sonra)."""
        if self.peer_names:
            self.icon.title = t("tooltip_peers", n=len(self.peer_names))
        elif self.node and self.loop:
            self.icon.title = t("tooltip_device", name=self.config["device_name"])
        else:
            self.icon.title = t("tooltip_offline", v=__version__)

    def _quit(self):
        self.running = False
        self._stop_node()
        try:
            self.icon.stop()
        except Exception:
            pass

    # ── Node yönetimi ──

    def start_node(self):
        if self.loop_thread and self.loop_thread.is_alive():
            return
        self.loop_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.loop_thread.start()

    def _restart_node(self):
        self._stop_node()
        # Loop thread'inin kapanmasını bekle, sonra yeniden başlat
        if self.loop_thread:
            self.loop_thread.join(timeout=3)
        self.loop_thread = None
        self.start_node()

    def _stop_node(self):
        if self.node and self.loop:
            try:
                fut = asyncio.run_coroutine_threadsafe(self.node.stop(), self.loop)
                fut.result(timeout=3)
            except Exception:
                pass
        if self.loop:
            try:
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception:
                pass

    def _run_async_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._async_main())
        except Exception as e:
            print(f"[App] loop hatası: {e}")
        finally:
            try:
                self.loop.close()
            except Exception:
                pass

    async def _async_main(self):
        log(f"=== SharedClipboard başlıyor — cihaz: {self.config['device_name']} ===")
        self.node = PeerNode(
            device_name=self.config["device_name"],
            on_remote_clipboard=self._on_remote_clipboard,
            on_peers_changed=self._on_peers_changed,
        )
        try:
            await self.node.start()
        except Exception as e:
            log(f"node start HATASI: {e!r}")
            self._update_icon("error")
            return

        self._update_icon("online")
        self.icon.title = t("tooltip_device", name=self.config["device_name"])
        self._update_menu()

        try:
            await self._watch_clipboard()
        finally:
            await self.node.stop()

    async def _watch_clipboard(self):
        interval = self.config.get("polling_ms", 300) / 1000
        while self.running:
            try:
                current = self.clipboard.get()
                h = self._content_hash(current)
                if (h != self.last_hash
                        and h != self.remote_hash
                        and current.strip()):
                    self.last_hash = h
                    await self.node.broadcast_clipboard(current)
                    self.history.append(current)
                    if len(self.history) > 20:
                        self.history = self.history[-20:]
                    self._update_menu()
            except Exception as e:
                log(f"watch_clipboard hatası: {e!r}")
            await asyncio.sleep(interval)

    # ── Callback'ler ──

    def _on_remote_clipboard(self, content: str, sender: str):
        h = self._content_hash(content)
        self.remote_hash = h
        self.last_hash = h
        self.clipboard.set(content)
        self.history.append(content)
        if len(self.history) > 20:
            self.history = self.history[-20:]
        self._update_icon("receiving")
        self.icon.title = t("tooltip_received", sender=sender, content=content[:40])
        self._update_menu()

        # Kısa süre sonra normal duruma dön (UI thread'inde tetiklemek için timer)
        threading.Timer(0.6, lambda: self._update_icon("online")).start()

    def _on_peers_changed(self, names):
        self.peer_names = names
        if names:
            self.icon.title = t("tooltip_peers", n=len(names))
        else:
            self.icon.title = t("tooltip_device", name=self.config["device_name"])
        self._update_menu()

    # ── Yardımcı ──

    @staticmethod
    def _content_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    # ── Çalıştır ──

    def run(self):
        if self.config.get("auto_start", True):
            self.start_node()
        self.icon.run()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--settings":
        run_settings_ui()
        return
    app = SharedClipboardApp()
    app.run()


if __name__ == "__main__":
    main()
