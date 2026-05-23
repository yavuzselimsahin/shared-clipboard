# 📋 Shared Clipboard — Ağ İçi Ortak Pano

Aynı yerel ağdaki bilgisayarlar arasında clipboard (pano) paylaşımı.
Bir cihazda Ctrl+C yaptığınızda içerik tüm bağlı cihazlarda anında görünür.

## Gereksinimler

- Python 3.8+
- `websockets` kütüphanesi

### Platforma Özel

| Platform | Ek Gereksinim |
|----------|---------------|
| Windows  | Yok (ctypes ile çalışır) |
| macOS    | Yok (pbcopy/pbpaste zaten var) |
| Linux X11| `sudo apt install xclip` |
| Linux Wayland | `sudo apt install wl-clipboard` |

## Kurulum (Her Makinede)

```bash
git clone <repo> shared-clipboard   # veya dosyaları kopyalayın
cd shared-clipboard
pip install -r requirements.txt
```

## Kullanım

### 1. Sunucuyu Başlatın (bir makine seçin)

```bash
python server.py
```

Varsayılan olarak `0.0.0.0:8765` dinler. Port değiştirmek için:

```bash
python server.py --port 9000
```

### 2. İstemcileri Başlatın (tüm makinelerde)

```bash
# Sunucu IP adresini belirtin
python client.py --server 192.168.1.100

# Özel isim verin
python client.py --server 192.168.1.100 --name "Ofis-PC"

# Farklı port
python client.py --server 192.168.1.100 --port 9000
```

> 💡 Sunucu IP adresini öğrenmek için:
> - Windows: `ipconfig`
> - Linux/macOS: `ip addr` veya `ifconfig`

### 3. Kullanın!

Herhangi bir cihazda bir şey kopyalayın (Ctrl+C) → Tüm cihazlarda yapıştırabilirsiniz (Ctrl+V).

## Mimari

```
┌──────────┐     WebSocket     ┌──────────────┐     WebSocket     ┌──────────┐
│ Client A ├───────────────────┤    Server    ├───────────────────┤ Client B │
│ (Win)    │                   │ (herhangi   │                   │ (Linux)  │
└──────────┘                   │  bir makine)│                   └──────────┘
                               └──────┬───────┘
                                      │ WebSocket
                               ┌──────┴───────┐
                               │   Client C   │
                               │   (macOS)    │
                               └──────────────┘
```

- İstemci, clipboard'u her 300ms'de kontrol eder
- Değişiklik varsa sunucuya gönderir
- Sunucu tüm diğer istemcilere broadcast eder
- Döngü engelleme: sunucudan gelen içerik tekrar gönderilmez

## Güvenlik Uyarısı

⚠️ Bu proje **yerel ağ** kullanımı için tasarlanmıştır.
Trafik şifrelenmemiştir (ws://, wss:// değil).
İnternete açmayın. Güvenli olmayan ağlarda kullanmayın.

Şifreleme eklemek isterseniz:
- SSL sertifikası oluşturun
- `websockets.serve` ve `websockets.connect` çağrılarına `ssl` parametresi ekleyin

## Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| `ConnectionRefused` | Sunucu çalışıyor mu? IP doğru mu? Firewall port 8765'i engelliyor mu? |
| Linux'ta clipboard çalışmıyor | `xclip` veya `wl-clipboard` yükleyin |
| Sürekli kopuyor | Ağ bağlantınızı kontrol edin, farklı port deneyin |
| İçerik geç geliyor | Polling aralığını `client.py`'de `asyncio.sleep(0.3)` satırından ayarlayın |
