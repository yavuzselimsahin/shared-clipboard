"""
Shared Clipboard Client
========================
Clipboard'u izler, değişiklikleri sunucuya gönderir ve
diğer cihazlardan gelen değişiklikleri yerel clipboard'a yazar.

Kullanım:
    pip install websockets pyperclip
    python client.py --server 192.168.1.100 [--port 8765] [--name "Laptop"]

Notlar:
    Linux'ta xclip veya xsel gerekli:
        sudo apt install xclip
    Wayland kullanıyorsanız:
        sudo apt install wl-clipboard
"""

import asyncio
import json
import platform
import socket
import argparse
import signal
import sys
import time
import subprocess

try:
    import websockets
except ImportError:
    print("Gerekli: pip install websockets")
    exit(1)


# ──────────────────────────────────────────────
#  Platforma özel clipboard işlemleri
# ──────────────────────────────────────────────

class ClipboardHandler:
    """Platforma göre doğru clipboard yöntemini seçer."""

    def __init__(self):
        self.system = platform.system()
        self._check_dependencies()

    def _check_dependencies(self):
        if self.system == "Linux":
            # Wayland mı X11 mi kontrol et
            session = os.environ.get("XDG_SESSION_TYPE", "").lower()
            if session == "wayland":
                self.linux_backend = "wayland"
                self._check_command("wl-copy", "sudo apt install wl-clipboard")
                self._check_command("wl-paste", "sudo apt install wl-clipboard")
            else:
                self.linux_backend = "x11"
                self._check_command("xclip", "sudo apt install xclip")

    def _check_command(self, cmd, install_hint):
        import shutil
        if not shutil.which(cmd):
            print(f"⚠ '{cmd}' bulunamadı. Kurmak için: {install_hint}")

    def get(self) -> str:
        """Clipboard içeriğini oku."""
        try:
            if self.system == "Darwin":  # macOS
                result = subprocess.run(
                    ["pbpaste"], capture_output=True, text=True, timeout=2
                )
                return result.stdout
            elif self.system == "Windows":
                return self._win_get()
            elif self.system == "Linux":
                return self._linux_get()
        except Exception:
            return ""

    def set(self, text: str):
        """Clipboard'a yaz."""
        try:
            if self.system == "Darwin":
                subprocess.run(
                    ["pbcopy"], input=text, text=True, timeout=2
                )
            elif self.system == "Windows":
                self._win_set(text)
            elif self.system == "Linux":
                self._linux_set(text)
        except Exception as e:
            print(f"⚠ Clipboard yazma hatası: {e}")

    # --- Windows ---
    def _win_get(self) -> str:
        import ctypes
        from ctypes import wintypes
        CF_UNICODETEXT = 13
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.OpenClipboard(0):
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            kernel32.GlobalLock.restype = ctypes.c_void_p
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return ""
            try:
                return ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def _win_set(self, text: str):
        import ctypes
        from ctypes import wintypes
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.OpenClipboard(0):
            return
        try:
            user32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            kernel32.GlobalLock.restype = ctypes.c_void_p
            ptr = kernel32.GlobalLock(handle)
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(CF_UNICODETEXT, handle)
        finally:
            user32.CloseClipboard()

    # --- Linux ---
    def _linux_get(self) -> str:
        if self.linux_backend == "wayland":
            r = subprocess.run(
                ["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=2
            )
        else:
            r = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True, text=True, timeout=2
            )
        return r.stdout

    def _linux_set(self, text: str):
        if self.linux_backend == "wayland":
            subprocess.run(
                ["wl-copy"], input=text, text=True, timeout=2
            )
        else:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text, text=True, timeout=2
            )


# ──────────────────────────────────────────────
#  Ana istemci
# ──────────────────────────────────────────────

class ClipboardClient:
    def __init__(self, server_host: str, server_port: int, name: str):
        self.server_url = f"ws://{server_host}:{server_port}"
        self.name = name
        self.clipboard = ClipboardHandler()
        self.last_hash = ""
        self.remote_hash = ""  # döngü engelleme
        self.connected_clients = []
        self.running = True

    def content_hash(self, text: str) -> str:
        import hashlib
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    async def watch_clipboard(self, ws):
        """Yerel clipboard'u izle, değişince sunucuya gönder."""
        while self.running:
            try:
                current = self.clipboard.get()
                current_hash = self.content_hash(current)

                # Değişti mi? Ve uzaktan gelen son içerik değil mi?
                if current_hash != self.last_hash and current_hash != self.remote_hash:
                    self.last_hash = current_hash
                    await ws.send(json.dumps({
                        "type": "clipboard",
                        "content": current,
                    }))
                    preview = current[:50].replace("\n", "\\n")
                    print(f"  ⬆ Gönderildi: {preview}...")

                await asyncio.sleep(0.3)  # 300ms polling
            except websockets.exceptions.ConnectionClosed:
                break
            except Exception as e:
                await asyncio.sleep(1)

    async def listen_server(self, ws):
        """Sunucudan gelen mesajları dinle."""
        try:
            async for raw in ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")

                if msg_type == "clipboard_update":
                    content = data["content"]
                    sender = data.get("sender", "?")
                    content_hash = data.get("hash", "")

                    # Döngüyü engelle: bu hash'i "uzaktan geldi" olarak işaretle
                    self.remote_hash = content_hash
                    self.last_hash = content_hash

                    self.clipboard.set(content)
                    preview = content[:50].replace("\n", "\\n")
                    print(f"  ⬇ {sender}: {preview}...")

                elif msg_type == "client_list":
                    self.connected_clients = data.get("clients", [])
                    names = [c["name"] for c in self.connected_clients]
                    print(f"  👥 Bağlı cihazlar: {', '.join(names)}")

                elif msg_type == "pong":
                    pass  # keepalive yanıtı

        except websockets.exceptions.ConnectionClosed:
            pass

    async def keepalive(self, ws):
        """Bağlantıyı canlı tut."""
        while self.running:
            try:
                await ws.send(json.dumps({"type": "ping"}))
                await asyncio.sleep(30)
            except Exception:
                break

    async def connect(self):
        """Sunucuya bağlan, bağlantı koparsa tekrar dene."""
        while self.running:
            try:
                print(f"🔗 Bağlanılıyor: {self.server_url}")
                async with websockets.connect(self.server_url) as ws:
                    # Kendini tanıt
                    await ws.send(json.dumps({
                        "type": "register",
                        "name": self.name,
                        "os": platform.system(),
                    }))
                    print(f"✅ Bağlandı! ({self.name})")
                    print("   Clipboard paylaşımı aktif. Çıkmak için Ctrl+C\n")

                    # Paralel görevler
                    await asyncio.gather(
                        self.watch_clipboard(ws),
                        self.listen_server(ws),
                        self.keepalive(ws),
                    )
            except (ConnectionRefusedError, OSError) as e:
                print(f"⚠ Bağlantı hatası: {e}")
                print("  5 saniye sonra tekrar denenecek...")
                await asyncio.sleep(5)
            except websockets.exceptions.ConnectionClosed:
                print("⚠ Bağlantı koptu, tekrar bağlanılıyor...")
                await asyncio.sleep(2)


import os


def get_default_name() -> str:
    """Makine adını otomatik belirle."""
    hostname = socket.gethostname()
    system = platform.system()
    return f"{hostname}-{system}"


def main():
    parser = argparse.ArgumentParser(description="Shared Clipboard Client")
    parser.add_argument("--server", required=True, help="Sunucu IP adresi (ör: 192.168.1.100)")
    parser.add_argument("--port", type=int, default=8765, help="Port (varsayılan: 8765)")
    parser.add_argument("--name", default=None, help="Bu cihazın adı (varsayılan: hostname)")
    args = parser.parse_args()

    name = args.name or get_default_name()

    client = ClipboardClient(args.server, args.port, name)

    print(f"""
╔══════════════════════════════════════════╗
║       📋 Shared Clipboard Client        ║
╠══════════════════════════════════════════╣
║  Cihaz: {name:<32s}║
║  Sunucu: {args.server}:{args.port:<24}║
╚══════════════════════════════════════════╝
    """)

    def shutdown(sig, frame):
        print("\n👋 Kapatılıyor...")
        client.running = False
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    asyncio.run(client.connect())


if __name__ == "__main__":
    main()
