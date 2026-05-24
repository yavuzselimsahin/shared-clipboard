"""
Shared Clipboard — Tek Dosya Paketleyici
==========================================
tray_client.py'yi tek bir çalıştırılabilir dosyaya/uygulamaya paketler.
Mesh + mDNS mimarisi olduğu için ayrı bir sunucuya gerek yok.

Kullanım:
    pip install -r requirements.txt
    python build.py

Sonuç:
    macOS  → dist/SharedClipboard.app
    Linux  → dist/SharedClipboard
    Windows → dist/SharedClipboard.exe
"""

import subprocess
import platform
import sys
import os


def build():
    system = platform.system()
    icon_arg = []

    if system == "Windows" and os.path.exists("icon.ico"):
        icon_arg = ["--icon=icon.ico"]
    elif system == "Darwin" and os.path.exists("icon.icns"):
        icon_arg = ["--icon=icon.icns"]

    print("=" * 50)
    print("📦 Shared Clipboard — Paketleme")
    print("=" * 50)

    print("\n🔨 İstemci paketleniyor...")
    # macOS'ta .app bundle yapacaksak --onedir kullanmak şart (PyInstaller >=6 uyarısı)
    package_mode = "--onedir" if system == "Darwin" else "--onefile"

    client_cmd = [
        sys.executable, "-m", "PyInstaller",
        package_mode,
        "--windowed",                       # konsolsuz GUI
        "--name", "SharedClipboard",
        "--collect-submodules", "zeroconf", # mDNS bağımlılıkları
        "--hidden-import", "websockets.legacy",
        "--hidden-import", "websockets.legacy.client",
        "--hidden-import", "websockets.legacy.server",
        *icon_arg,
        "--add-data", f"README.md{os.pathsep}.",
        "tray_client.py",
    ]
    subprocess.run(client_cmd, check=True)

    print("\n" + "=" * 50)
    print("✅ Paketleme tamamlandı!")
    print(f"   Çıktı: {os.path.abspath('dist')}")
    print("=" * 50)

    print("""
Dağıtım:
  1. dist/SharedClipboard(.app/.exe) → arkadaşına gönder
  2. Aynı Wi-Fi'a bağlı her cihazda aç — birbirini otomatik bulur
  3. macOS'ta ilk açılışta "İnternetten gelen yazılım" uyarısı çıkabilir,
     sağ tık → Aç ile geç (veya Sistem Ayarları → Gizlilik & Güvenlik)
""")


if __name__ == "__main__":
    build()
