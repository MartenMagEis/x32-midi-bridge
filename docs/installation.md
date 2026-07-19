# Installation & Setup

[← Zurück zur README](../README.md)

Dieses Projekt verwendet [uv](https://docs.astral.sh/uv/) als Paketmanager für Python.

## Schritt 1: Lokale Umgebung vorbereiten

Erstelle eine virtuelle Python-Umgebung im Projektverzeichnis, um die Abhängigkeiten isoliert zu verwalten:

```
uv venv
```

Aktiviere die Umgebung je nach Betriebssystem im Terminal:

- **Windows (CMD/PowerShell):** `.venv\Scripts\activate`
- **macOS / Linux (bash/zsh):** `source .venv/bin/activate`

## Schritt 2: RTP-MIDI-Verbindung herstellen (Sender-Konfiguration)

Die Bridge fungiert als eigenständiger RTP-MIDI-Server (AppleMIDI-Protokoll), der einen Netzwerk-Port (Standard: 5004, konfigurierbar über `rtp_local_port`) öffnet und sich via Bonjour/mDNS als `_apple-midi._udp` im Netzwerk ankündigt.

Der MIDI-Sender (z. B. ein PC mit Ableton Live) muss sich aktiv mit dieser Netzwerksession verbinden:

- **Windows (Sender-PC):** Windows verfügt standardmäßig über keinen nativen RTP-MIDI-Treiber. Auf dem sendenden PC wird ein Treiber wie [rtpMIDI](https://www.tobias-erichsen.de/software/rtpmidi.html) (von Tobias Erichsen) benötigt, um eine virtuelle Netzwerksitzung zu erstellen und die Verbindung zur Bridge aufzubauen.
- **macOS (Sender-PC):** Nutzt den nativen Netzwerk-MIDI-Dienst im Betriebssystem (konfigurierbar über das Audio-MIDI-Setup unter MIDI-Studio > Netzwerk).

Alternativ kann statt RTP-MIDI auch ein lokal an diesen Rechner angeschlossenes MIDI-Interface direkt verwendet werden (`midi_source` in `system_config.json`) — siehe [Konfiguration: system_config.json](system-config.md).

> **Hinweis:** Läuft die Bridge auf demselben Windows-PC, auf dem bereits der rtpMIDI-Treiber/-Dienst (`rtpMIDISvc`) installiert ist, belegt dieser standardmäßig ebenfalls die Ports 5004/5005. In diesem Fall meldet die Bridge beim Start `OSError: ... Adresse wird bereits verwendet` — setze `rtp_local_port` in `system_config.json` auf einen freien Port (z. B. `5008`).

## Schritt 3: Die Bridge starten

Um die MIDI-Bridge im normalen Modus zu starten:

```
uv run main.py
```

Um den interaktiven Test- & Diagnosemodus zu aktivieren (zum Testen von Mappings direkt über die Tastatur und zum Einsehen farbiger Feedback-Protokolle):

```
uv run main.py --test
```

## Für Entwicklung: Tests ausführen

Dieser Schritt ist **nur relevant, wenn du selbst am Code der Bridge arbeitest** — für den normalen Betrieb (Schritte 1-3) wird er nicht gebraucht.

Das Projekt hat eine automatisierte Testsuite (`pytest`, als Dev-Abhängigkeit), die die komplexere Logik der Bridge ohne echtes X32, echte MIDI-Hardware oder Netzwerkzugriff absichert — u. a. Hybrid-Kanal-Modus/klassenübergreifende Auswahl, die Velocity-0-Note-Off-Normalisierung (für RTP-MIDI *und* lokales MIDI), den Reconnect-Keep-Alive-Zustandsautomat sowie Mapping-/Config-Validierung inkl. der `web_enabled`-Sperre:

```
uv run pytest
```

Läuft in unter 2 Sekunden komplett offline durch (52 Tests zum Zeitpunkt der letzten Aktualisierung dieses Abschnitts) — sinnvoll nach jeder Änderung an `main.py`/`webui.py`, um Regressionen frühzeitig zu bemerken.
