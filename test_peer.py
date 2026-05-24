"""
Mesh test peer'ı — aynı makinede ikinci bir gerçek cihaz gibi davranır.

- mDNS ile kendini yayınlar (_sharedclipboard._tcp.local.)
- mDNS ile diğer peer'ları arar ve outbound bağlanır
- Aralıklarla sahte clipboard mesajı gönderir (uzak → Mac yön)
- Gelen mesajları terminale yazar (Mac → uzak yön)
- KENDİ panonu DEĞİŞTİRMEZ — bu sayede gerçek tray client ile
  aynı makinede çalışabilir, echo loop'a girmez.

Kullanım:
    python test_peer.py [--name FakePeer] [--interval 5] [--silent]
"""

import argparse
import asyncio
import json
import platform
import socket
import sys
import time
import uuid

import websockets
from zeroconf import ServiceInfo, ServiceStateChange, IPVersion
from zeroconf.asyncio import AsyncZeroconf, AsyncServiceBrowser


SERVICE_TYPE = "_sharedclipboard._tcp.local."


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def sanitize_label(name):
    out = []
    for c in name:
        if c.isalnum() or c in "-_":
            out.append(c)
        elif c == " ":
            out.append("-")
    return "".join(out).strip("-_") or "device"


class FakePeer:
    def __init__(self, device_name, interval, silent):
        self.device_name = device_name
        self.peer_id = uuid.uuid4().hex
        self.interval = interval
        self.silent = silent
        self.peers = {}  # peer_id -> {ws, name}
        self.aiozc = None
        self.service_info = None
        self.browser = None
        self.server = None
        self.port = None
        self.loop = None

    async def start(self):
        self.loop = asyncio.get_running_loop()

        self.server = await websockets.serve(self._handle_inbound, "0.0.0.0", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        print(f"[FakePeer] :{self.port} dinlemede (peer_id={self.peer_id[:8]})")

        self.aiozc = AsyncZeroconf(ip_version=IPVersion.V4Only)
        ip = get_local_ip()
        safe = f"{sanitize_label(self.device_name)}-{self.peer_id[:6]}"
        self.service_info = ServiceInfo(
            SERVICE_TYPE,
            f"{safe}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(ip)],
            port=self.port,
            properties={
                b"name": self.device_name.encode("utf-8"),
                b"id": self.peer_id.encode("utf-8"),
                b"os": platform.system().encode("utf-8"),
            },
            server=f"{safe}.local.",
        )
        await self.aiozc.async_register_service(self.service_info)
        print(f"[FakePeer] mDNS yayında: {safe} @ {ip}")

        self.browser = AsyncServiceBrowser(
            self.aiozc.zeroconf,
            SERVICE_TYPE,
            handlers=[self._on_state],
        )
        print(f"[FakePeer] mDNS keşif başladı")

    def _on_state(self, *, zeroconf, service_type, name, state_change):
        if state_change == ServiceStateChange.Added:
            asyncio.run_coroutine_threadsafe(
                self._handle_discovered(service_type, name), self.loop
            )

    async def _handle_discovered(self, service_type, name):
        info = await self.aiozc.async_get_service_info(service_type, name, timeout=3000)
        if not info or not info.properties:
            return
        peer_id = info.properties.get(b"id", b"").decode("utf-8", errors="replace")
        if not peer_id or peer_id == self.peer_id:
            return
        if self.peer_id >= peer_id:
            print(f"[FakePeer] {peer_id[:8]} bana bağlanacak (tie-break)")
            return
        if peer_id in self.peers:
            return

        addresses = []
        try:
            addresses = info.parsed_addresses()
        except Exception:
            for a in info.addresses or []:
                try:
                    addresses.append(socket.inet_ntoa(a))
                except Exception:
                    pass
        if not addresses:
            return

        peer_name = info.properties.get(b"name", b"?").decode("utf-8", errors="replace")
        host = addresses[0]
        port = info.port
        print(f"[FakePeer] outbound bağlanılıyor: {peer_name} @ {host}:{port}")

        try:
            ws = await asyncio.wait_for(
                websockets.connect(f"ws://{host}:{port}"), timeout=5
            )
        except Exception as e:
            print(f"[FakePeer] outbound başarısız: {e!r}")
            return

        await ws.send(json.dumps({
            "type": "hello",
            "id": self.peer_id,
            "name": self.device_name,
        }))
        print(f"[FakePeer] outbound bağlı: {peer_name}")
        self.peers[peer_id] = {"ws": ws, "name": peer_name}
        try:
            async for raw in ws:
                self._on_message(raw, peer_id)
        except Exception:
            pass
        finally:
            self.peers.pop(peer_id, None)
            print(f"[FakePeer] outbound koptu: {peer_name}")

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
        print(f"[FakePeer] inbound bağlandı: {peer_name}")
        self.peers[peer_id] = {"ws": ws, "name": peer_name}
        try:
            async for raw in ws:
                self._on_message(raw, peer_id)
        except Exception:
            pass
        finally:
            self.peers.pop(peer_id, None)
            print(f"[FakePeer] inbound koptu: {peer_name}")

    def _on_message(self, raw, peer_id):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        if data.get("type") == "clipboard":
            sender = self.peers.get(peer_id, {}).get("name", "?")
            content = data.get("content", "")
            print(f"[Mac→FakePeer] {sender}: {content[:120]!r}")
            # ÖNEMLİ: kendi panomu DEĞİŞTİRMİYORUM — echo loop olmasın.

    async def sender_loop(self):
        if self.silent or self.interval <= 0:
            return
        i = 0
        while True:
            await asyncio.sleep(self.interval)
            if not self.peers:
                continue
            msg = f"FakePeer'den merhaba #{i} ({time.strftime('%H:%M:%S')})"
            payload = json.dumps({
                "type": "clipboard",
                "content": msg,
                "sender": self.device_name,
            })
            dead = []
            for pid, info in list(self.peers.items()):
                try:
                    await info["ws"].send(payload)
                except Exception:
                    dead.append(pid)
            for pid in dead:
                self.peers.pop(pid, None)
            print(f"[FakePeer→Mac] gönderildi: {msg!r} ({len(self.peers)} peer)")
            i += 1


async def amain():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="FakePeer")
    parser.add_argument("--interval", type=float, default=5.0,
                        help="Gönderim aralığı (saniye). 0/--silent = sadece dinle.")
    parser.add_argument("--silent", action="store_true",
                        help="Hiç mesaj gönderme, sadece gelenleri logla.")
    args = parser.parse_args()

    peer = FakePeer(args.name, args.interval, args.silent)
    await peer.start()
    await peer.sender_loop()
    # sender_loop bittiğinde sonsuza kadar bekle
    await asyncio.Future()


def main():
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
