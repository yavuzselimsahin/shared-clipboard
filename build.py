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
import plistlib
import zipfile

# Windows CI runner'larında stdout cp1252 olur ve emoji'li print'ler patlar.
# Python 3.7+ stream reconfigure desteği var.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


BUNDLE_ID = "com.yavuzselimsahin.sharedclipboard"


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

    # macOS-spesifik PyInstaller flag'leri:
    # - --osx-bundle-identifier: kararlı bundle ID → Yerel Ağ izinleri kaybolmaz
    # - --collect-all zeroconf: ifaddr ve C extension'lar dahil her şey
    # - AppKit/Foundation/objc: pystray + NSPasteboard için
    mac_extra = []
    if system == "Darwin":
        mac_extra = [
            "--osx-bundle-identifier", BUNDLE_ID,
            "--collect-all", "zeroconf",
            "--hidden-import", "AppKit",
            "--hidden-import", "Foundation",
            "--hidden-import", "objc",
        ]

    client_cmd = [
        sys.executable, "-m", "PyInstaller",
        package_mode,
        "--noconfirm",                      # eski build'i sor­madan üzerine yaz
        "--windowed",                       # konsolsuz GUI
        "--name", "SharedClipboard",
        "--collect-submodules", "zeroconf", # mDNS bağımlılıkları (non-mac için)
        "--hidden-import", "websockets.legacy",
        "--hidden-import", "websockets.legacy.client",
        "--hidden-import", "websockets.legacy.server",
        *mac_extra,
        *icon_arg,
        "--add-data", f"README.md{os.pathsep}.",
        "tray_client.py",
    ]
    subprocess.run(client_cmd, check=True)

    if system == "Darwin":
        print("\n🔧 Info.plist'e Yerel Ağ + Bonjour key'leri yazılıyor...")
        _patch_macos_info_plist()
        print("\n🔏 Ad-hoc codesign uygulanıyor...")
        _adhoc_codesign()

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


def _patch_macos_info_plist():
    """macOS 14+ Sonoma'da mDNS ve Yerel Ağ izni için Info.plist key'leri.

    NSLocalNetworkUsageDescription olmadan macOS, app'in mDNS/multicast
    yapma isteğini sessizce engeller — Yerel Ağ izin prompt'u çıkmaz,
    bonjour servisleri görünmez. NSBonjourServices listesinde olmayan
    servisleri de keşfedemezsin.
    """
    plist_path = "dist/SharedClipboard.app/Contents/Info.plist"
    if not os.path.exists(plist_path):
        print(f"  ⚠️  {plist_path} yok; atlanıyor")
        return
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)
    plist["CFBundleIdentifier"] = BUNDLE_ID
    plist["NSLocalNetworkUsageDescription"] = (
        "Aynı Wi-Fi'daki diğer cihazlarla pano içeriğini paylaşmak için."
    )
    plist["NSBonjourServices"] = ["_sharedclipboard._tcp"]
    # LSUIElement: Dock'ta ikon gösterme (tray uygulaması)
    plist["LSUIElement"] = True
    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)
    print(f"  ✓ {plist_path} güncellendi")


def _adhoc_codesign():
    """Ad-hoc (sertifika gerektirmeyen) imzalama.

    Apple Developer hesabı + notarization olmadan, sadece Gatekeeper'ın
    'damaged' mesajını engellemek için. Kullanıcı yine 'kimliği
    doğrulanamadı' uyarısı görür ama sağ tık → Aç ile geçebilir.
    """
    app_path = "dist/SharedClipboard.app"
    if not os.path.exists(app_path):
        print(f"  ⚠️  {app_path} yok; atlanıyor")
        return
    try:
        subprocess.run(
            ["codesign", "--force", "--deep", "--sign", "-", app_path],
            check=True,
        )
        print(f"  ✓ {app_path} ad-hoc imzalandı")
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️  codesign başarısız: {e}")


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
