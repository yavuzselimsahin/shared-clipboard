# Shared Clipboard

[English](README.md) · **Türkçe**

Aynı yerel ağ üzerindeki bilgisayarlar arasında pano (clipboard) içeriğini
otomatik olarak eşitleyen bir masaüstü yardımcı uygulamasıdır. Herhangi bir
cihazda kopyalanan metin, ağdaki diğer tüm cihazlarda anında erişilebilir
hâle gelir.

Uygulama tamamen yerel ağda çalışır: harici sunucu, kullanıcı hesabı veya
internet bağlantısı gerektirmez. Cihazlar birbirini mDNS (Bonjour) ile
keşfeder ve doğrudan WebSocket bağlantısı üzerinden iletişim kurar.

## İndirme

Resmî sürümler aşağıdaki adresten edinilebilir:

**<https://yavuzselimsahin.github.io/shared-clipboard/>**

Sayfa, ziyaretçinin işletim sistemine uygun derlemeyi otomatik olarak önerir.
Manuel indirme için
[GitHub Releases](https://github.com/yavuzselimsahin/shared-clipboard/releases)
sayfası kullanılabilir.

İlk çalıştırmada karşılaşılabilecek sistem uyarıları (macOS Gatekeeper ve
Yerel Ağ izni, Windows SmartScreen ve Defender Firewall) için ayrıntılı
yönergeler resmî web sayfasında platform bazında listelenmiştir.

## Mimari

Her istemci, başlatılmasının ardından şu adımları izler:

1. Kendisini `_sharedclipboard._tcp.local.` servis tipiyle mDNS üzerinde
   ilan eder.
2. Aynı servis tipini yayınlayan diğer cihazları sürekli olarak arar.
3. Keşfettiği her eşe ayrı bir WebSocket bağlantısı kurar (tam-örgü / mesh
   topoloji).
4. Yerel pano içeriği değiştiğinde, bağlı olduğu tüm eşlere yeni içeriği
   yayar.
5. Diğer eşlerden gelen mesajlardaki içeriği yerel panoya yazar.

```
   Cihaz A  ↔  Cihaz B
      ↕        ↕
      ────  Cihaz C ────
```

Trafiğin tamamı yerel ağ üzerinde **şifrelenmeden** akar. Bu nedenle uygulama
yalnızca güvenilir ev veya ofis ağlarında kullanılmalıdır; halka açık veya
parolasız Wi-Fi ağlarında çalıştırılmamalıdır.

## Platform Gereksinimleri

| Platform | Ek bağımlılık |
| --- | --- |
| macOS (Apple Silicon) | Yok. Bonjour işletim sistemiyle birlikte gelir. |
| Windows 10 / 11 (x64) | Yok. zeroconf saf Python ile çalışır. |
| Linux (X11) | `xclip`, `python3-tk`, `libappindicator3-1` |
| Linux (Wayland) | `wl-clipboard`, `python3-tk` |

İlk çalıştırmada işletim sistemi, yerel ağ erişimi için kullanıcı onayı
talep edebilir. Onay verilmediği takdirde diğer cihazlar keşfedilemez.

## Geliştirme

### Kaynak koddan çalıştırma

```bash
git clone https://github.com/yavuzselimsahin/shared-clipboard.git
cd shared-clipboard
pip install -r requirements.txt
python tray_client.py
```

### Tek makinede test

Mesh mimaride iki gerçek istemcinin aynı makinede aynı anda çalıştırılması
yankı (echo) döngüsüne neden olur. Bu durumdan kaçınmak için ikinci istemci
yerine depo içindeki `test_peer.py` betiği kullanılabilir. Bu yardımcı
betik kendi panosunu değiştirmeden mesajları zeroconf üzerinden alır ve
konsola yazdırır.

```bash
python tray_client.py     # gerçek istemci
python test_peer.py       # sahte ikinci cihaz (ayrı bir terminalde)
```

### Yerel derleme

```bash
python build.py
```

Çıktı arşivi `dist/SharedClipboard-<platform>-<arch>.zip` adıyla üretilir.


## Lisans

Bu proje MIT Lisansı ile yayımlanmıştır. Ayrıntılar için [LICENSE](LICENSE)
dosyasına bakılabilir.
