# 📋 Shared Clipboard

Aynı Wi-Fi'daki bilgisayarlar arasında otomatik clipboard paylaşımı.
Birinde `Cmd/Ctrl+C` yaptığında içerik diğer tüm cihazlarda hazır olur.
**Sunucu yok, hesap yok, internete açılmıyor** — cihazlar birbirini mDNS ile
otomatik bulup doğrudan WebSocket'le konuşur.

## İndir

👉 **<https://yavuzselimsahin.github.io/shared-clipboard/>**

Sayfa işletim sistemine uygun yapıyı sana otomatik gösterir. Manuel indirme:
[GitHub Releases](https://github.com/yavuzselimsahin/shared-clipboard/releases)

İlk açılışta yapılması gerekenler (Gatekeeper, Yerel Ağ izni, SmartScreen)
landing page'de adım adım yazılı.

## Nasıl çalışır?

```
   Cihaz A  ↔  Cihaz B
      ↕        ↕
      ────  Cihaz C ────
```

Her cihaz:
1. Açıldığında kendini `_sharedclipboard._tcp.local.` servisi olarak mDNS'le ilan eder
2. Aynı servisi yayınlayan diğer cihazları arar
3. Bulduğu her cihaza WebSocket'le bağlanır (mesh)
4. Pano değişirse tüm bağlı peer'lere içeriği yayınlar

Her şey yerel ağda; trafik **şifresizdir** — açık/halka açık Wi-Fi'da kullanma.

## Platform notları

| Platform | Ekstra |
|---|---|
| macOS | Yok (Bonjour yerleşik) |
| Windows | Yok (zeroconf saf Python) |
| Linux X11 | `sudo apt install xclip python3-tk libappindicator3-1` |
| Linux Wayland | `sudo apt install wl-clipboard python3-tk` |

İlk açılışta Windows Defender Firewall ve macOS Yerel Ağ izni soracaktır;
onaylamadan diğer cihazları bulamaz.

## Geliştirici

### Kaynaktan çalıştır

```bash
git clone https://github.com/yavuzselimsahin/shared-clipboard.git
cd shared-clipboard
pip install -r requirements.txt
python tray_client.py
```

### Tek MacBook'la test

Mesh mimaride iki gerçek istemci aynı makinede echo loop yapar.
Sahte peer scripti onun yerine geçer:

```bash
python tray_client.py           # bir terminalde gerçek istemci
python test_peer.py             # başka terminalde sahte ikinci cihaz
```

`test_peer.py` kendi panosunu değiştirmez; sadece zeroconf ile keşfedip
mesajları rapor eder.

### Local build

```bash
python build.py
```

Çıktı `dist/SharedClipboard-<platform>-<arch>.zip` olarak hazırlanır.

### Yeni sürüm çıkarma

```bash
# 1) tray_client.py içinde __version__ değerini bump et
# 2) commit
git commit -am "release: v0.2.0"
# 3) tag at ve push
git tag v0.2.0
git push && git push --tags
```

GitHub Actions otomatik olarak macOS arm64 + macOS Intel + Windows x64 build'lerini
alır ve [Releases](https://github.com/yavuzselimsahin/shared-clipboard/releases) sayfasına
ZIP'leri ekler. Landing page de en son release'i otomatik gösterir.

CI tag adıyla `__version__`'ı karşılaştırır; eşleşmezse build başarısız olur.

## Lisans

MIT
