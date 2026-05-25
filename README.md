# Shared Clipboard

**English** · [Türkçe](README.tr.md)

A desktop utility that automatically synchronises clipboard contents between
computers on the same local network. Text copied on one device becomes
instantly available on every other device on the network.

The application runs entirely on the local network: no external server, user
account, or internet connection is required. Devices discover each other via
mDNS (Bonjour) and communicate directly over WebSocket.

## Download

Official builds are available at:

**<https://yavuzselimsahin.github.io/shared-clipboard/>**

The landing page automatically suggests the build appropriate for the
visitor's operating system. For manual downloads, see
[GitHub Releases](https://github.com/yavuzselimsahin/shared-clipboard/releases).

Detailed first-run guidance for system prompts (macOS Gatekeeper and Local
Network permission, Windows SmartScreen and Defender Firewall) is provided
per platform on the official web page.

## Architecture

Once launched, each client performs the following steps:

1. Advertises itself over mDNS under the service type
   `_sharedclipboard._tcp.local.`
2. Continuously browses for other devices advertising the same service type.
3. Opens a dedicated WebSocket connection to every discovered peer
   (full-mesh topology).
4. Broadcasts new local clipboard content to all connected peers.
5. Writes incoming messages from peers into the local clipboard.

```
   Device A  ↔  Device B
      ↕         ↕
      ────  Device C ────
```

All traffic flows over the local network **without encryption**. The
application should therefore only be used on trusted home or office
networks; it must not be run on public or unprotected Wi-Fi.

## System Requirements

| Platform | Extra dependencies |
| --- | --- |
| macOS (Apple Silicon) | None. Bonjour ships with the operating system. |
| Windows 10 / 11 (x64) | None. zeroconf runs in pure Python. |
| Linux (X11) | `xclip`, `python3-tk`, `libappindicator3-1` |
| Linux (Wayland) | `wl-clipboard`, `python3-tk` |

On first launch the operating system may prompt for local network access.
If the prompt is declined, other devices cannot be discovered.

## Development

### Running from source

```bash
git clone https://github.com/yavuzselimsahin/shared-clipboard.git
cd shared-clipboard
pip install -r requirements.txt
python tray_client.py
```

### Testing on a single machine

In a mesh topology, running two real clients on the same machine creates an
echo loop. To avoid this, the bundled `test_peer.py` helper can be used in
place of a second device. The helper does not modify its own clipboard; it
only receives messages over zeroconf and logs them to the console.

```bash
python tray_client.py     # real client
python test_peer.py       # mock second device (in a separate terminal)
```

### Local build

```bash
python build.py
```

## License

This project is released under the MIT License. See [LICENSE](LICENSE) for
details.
