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
import zipfile


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

    print("\n🗜️  ZIP paketleniyor...")
    asset = _package_asset(system)

    print("\n" + "=" * 50)
    print("✅ Paketleme tamamlandı!")
    print(f"   Çıktı: dist/{asset}")
    print("=" * 50)

    print("""
Dağıtım:
  1. dist/<asset>.zip → arkadaşına gönder (AirDrop/WeTransfer/Drive)
  2. Aynı Wi-Fi'a bağlı her cihazda aç — birbirini otomatik bulur
  3. macOS'ta ilk açılışta "İnternetten gelen yazılım" uyarısı çıkabilir,
     sağ tık → Aç ile geç (veya Sistem Ayarları → Gizlilik & Güvenlik)
""")


def _package_asset(system: str) -> str:
    """PyInstaller çıktısını platform-named ZIP'e koyar.

    macOS: sistem `zip -ry` kullanılır; .app içindeki symlink + exec bit'leri
    Python `zipfile` taşımıyor, bundle bozulur.
    Windows/Linux: tek dosyalık çıktı; `zipfile.ZIP_DEFLATED` yeterli.
    """
    machine = platform.machine().lower()

    if system == "Darwin":
        arch = "arm64" if machine == "arm64" else "x86_64"
        asset = f"SharedClipboard-macos-{arch}.zip"
        subprocess.run(
            ["zip", "-ry", asset, "SharedClipboard.app"],
            cwd="dist", check=True,
        )
        return asset

    if system == "Windows":
        asset = "SharedClipboard-windows-x64.zip"
        src = os.path.join("dist", "SharedClipboard.exe")
        dst = os.path.join("dist", asset)
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(src, arcname="SharedClipboard.exe")
        return asset

    # Linux
    arch = "x86_64" if machine in ("x86_64", "amd64") else machine
    asset = f"SharedClipboard-linux-{arch}.zip"
    src = os.path.join("dist", "SharedClipboard")
    dst = os.path.join("dist", asset)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(src, arcname="SharedClipboard")
    return asset


if __name__ == "__main__":
    build()
