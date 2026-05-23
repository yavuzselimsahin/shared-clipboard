"""
Shared Clipboard Server
=======================
Ağdaki tüm cihazlar arasında clipboard paylaşımı sağlayan WebSocket sunucusu.

Kullanım:
    pip install websockets
    python server.py [--host 0.0.0.0] [--port 8765]
"""

import asyncio
import json
import argparse
import hashlib
import time
from datetime import datetime

try:
    import websockets
except ImportError:
    print("websockets kütüphanesi gerekli: pip install websockets")
    exit(1)


class ClipboardServer:
    def __init__(self):
        self.clients = {}  # websocket -> client_info
        self.current_clipboard = ""
        self.current_hash = ""
        self.last_sender = None
        self.history = []  # son 50 clipboard kaydı

    def content_hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    async def register(self, websocket, client_info: dict):
        self.clients[websocket] = {
            "name": client_info.get("name", "Bilinmeyen"),
            "os": client_info.get("os", "?"),
            "connected_at": datetime.now().isoformat(),
        }
        print(f"[+] Bağlandı: {self.clients[websocket]['name']} ({self.clients[websocket]['os']}) — Toplam: {len(self.clients)}")

        # Yeni bağlanan istemciye mevcut clipboard'u gönder
        if self.current_clipboard:
            await websocket.send(json.dumps({
                "type": "clipboard_update",
                "content": self.current_clipboard,
                "hash": self.current_hash,
                "sender": self.last_sender or "sunucu",
            }))

        # Tüm istemcilere güncel bağlı cihaz listesini gönder
        await self.broadcast_client_list()

    async def unregister(self, websocket):
        info = self.clients.pop(websocket, None)
        if info:
            print(f"[-] Ayrıldı: {info['name']} — Toplam: {len(self.clients)}")
        await self.broadcast_client_list()

    async def broadcast_client_list(self):
        client_list = [
            {"name": info["name"], "os": info["os"]}
            for info in self.clients.values()
        ]
        message = json.dumps({"type": "client_list", "clients": client_list})
        await self.broadcast(message)

    async def broadcast(self, message, exclude=None):
        disconnected = []
        for ws in self.clients:
            if ws == exclude:
                continue
            try:
                await ws.send(message)
            except websockets.exceptions.ConnectionClosed:
                disconnected.append(ws)
        for ws in disconnected:
            await self.unregister(ws)

    async def handle_clipboard(self, websocket, data: dict):
        content = data.get("content", "")
        content_hash = self.content_hash(content)

        # Aynı içerik tekrar gelmesin
        if content_hash == self.current_hash:
            return

        sender_name = self.clients.get(websocket, {}).get("name", "?")
        self.current_clipboard = content
        self.current_hash = content_hash
        self.last_sender = sender_name

        # Geçmişe ekle (maks 50)
        self.history.append({
            "content": content[:200],  # önizleme için kısalt
            "sender": sender_name,
            "time": datetime.now().isoformat(),
        })
        if len(self.history) > 50:
            self.history = self.history[-50:]

        preview = content[:60].replace("\n", "\\n")
        print(f"[📋] {sender_name}: {preview}...")

        # Gönderen hariç herkese yayınla
        message = json.dumps({
            "type": "clipboard_update",
            "content": content,
            "hash": content_hash,
            "sender": sender_name,
        })
        await self.broadcast(message, exclude=websocket)

    async def handle_message(self, websocket, raw_message: str):
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type")

        if msg_type == "register":
            await self.register(websocket, data)
        elif msg_type == "clipboard":
            await self.handle_clipboard(websocket, data)
        elif msg_type == "ping":
            await websocket.send(json.dumps({"type": "pong"}))
        elif msg_type == "get_history":
            await websocket.send(json.dumps({
                "type": "history",
                "history": self.history[-20:],
            }))

    async def handler(self, websocket):
        try:
            async for message in websocket:
                await self.handle_message(websocket, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await self.unregister(websocket)


async def main():
    parser = argparse.ArgumentParser(description="Shared Clipboard Server")
    parser.add_argument("--host", default="0.0.0.0", help="Dinlenecek adres (varsayılan: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="Port (varsayılan: 8765)")
    args = parser.parse_args()

    server = ClipboardServer()

    print(f"""
╔══════════════════════════════════════════╗
║       📋 Shared Clipboard Server        ║
╠══════════════════════════════════════════╣
║  Adres: {args.host}:{args.port}              ║
║  İstemciler bağlanmayı bekliyor...       ║
╚══════════════════════════════════════════╝
    """)

    async with websockets.serve(server.handler, args.host, args.port):
        await asyncio.Future()  # sonsuza kadar çalış


if __name__ == "__main__":
    asyncio.run(main())
