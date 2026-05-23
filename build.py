"""
Shared Clipboard — Tek Dosya Paketleyici
==========================================
Bu script, tray_client.py ve server.py dosyalarını
tek çalıştırılabilir dosyalara (.exe / binary) dönüştürür.

Kullanım:
    pip install pyinstaller
    python build.py

Sonuç:
    dist/SharedClipboard      (veya .exe)  — İstemci uygulaması
    dist/SharedClipboardServer (veya .exe)  — Sunucu
"""

import subprocess
import platform
import sys
import os

def build():
    system = platform.system()
    icon_arg = []

    # Windows'ta icon dosyası varsa ekle
    if system == "Windows" and os.path.exists("icon.ico"):
        icon_arg = ["--icon=icon.ico"]

    print("=" * 50)
    print("📦 Shared Clipboard — Paketleme")
    print("=" * 50)

    # 1) İstemci (Tray uygulaması)
    print("\n🔨 İstemci paketleniyor...")
    client_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",                    # konsolsuz (GUI)
        "--name", "SharedClipboard",
        *icon_arg,
        "--add-data", f"README.md{os.pathsep}.",
        "tray_client.py",
    ]
    subprocess.run(client_cmd, check=True)

    # 2) Sunucu
    print("\n🔨 Sunucu paketleniyor...")
    server_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",                     # konsol uygulaması
        "--name", "SharedClipboardServer",
        *icon_arg,
        "server.py",
    ]
    subprocess.run(server_cmd, check=True)

    print("\n" + "=" * 50)
    print("✅ Paketleme tamamlandı!")
    print(f"   Dosyalar: {os.path.abspath('dist')}")
    print("=" * 50)

    if system == "Windows":
        print("""
Dağıtım:
  1. dist/SharedClipboardServer.exe → Sunucu makinesine kopyala
  2. dist/SharedClipboard.exe → Tüm makinelere kopyala
  3. Önce sunucuyu başlat, sonra istemcileri çalıştır
        """)
    else:
        print("""
Dağıtım:
  1. dist/SharedClipboardServer → Sunucu makinesine kopyala
  2. dist/SharedClipboard → Tüm makinelere kopyala
  3. chmod +x ile çalıştırılabilir yap
  4. Önce sunucuyu başlat, sonra istemcileri çalıştır
        """)


if __name__ == "__main__":
    build()
