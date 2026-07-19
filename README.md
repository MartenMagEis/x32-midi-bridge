# X32 MIDI Bridge

Ein plattformunabhängiger, asynchroner MIDI-zu-OSC-Controller-Daemon für Behringer X32 Mischpulte.

Dieses Tool läuft als lokaler Hintergrunddienst (Daemon) und ermöglicht die latenz- und blockfreie Steuerung des X32 über RTP-MIDI (oder wahlweise ein lokal angeschlossenes MIDI-Interface). Es ist für den Betrieb in isolierten lokalen Netzwerken ohne Internetverbindung konzipiert.

## Systemarchitektur & Netzwerk-Setup

Das System vermittelt Signale zwischen einer MIDI-Quelle (z. B. einer DAW) und dem Mischpult über ein lokales Netzwerk.

```
+-------------------------------------------------------------+
|               PC / Mac (Ableton Live Session)               |
|  - Sendet MIDI-Signale über RTP-MIDI                        |
+-------------------------------------------------------------+
                               |
                    RTP-MIDI via Localhost / LAN
                               v
+-------------------------------------------------------------+
|             Asynchroner Python-Dienst (Daemon)              |
|  - Empfängt MIDI über RTP-MIDI (FIFO Event-Queue)           |
|  - Skaliert Werte mathematisch (z.B. Logarithmischer Fader) |
|  - Sichert Original-Pultwerte vor Änderungen (Undo Cache)   |
+-------------------------------------------------------------+
                               |
                   OSC over UDP (Port 10023)
                               v
+-------------------------------------------------------------+
|                     Behringer X32 Rack                      |
+-------------------------------------------------------------+
```

### Netzwerk-Voraussetzungen

Für die Kommunikation müssen sich der Steuerungs-PC, der Daemon und das X32-Mischpult im selben Subnetz befinden und IP-Pakete (UDP) bidirektional austauschen können. Eine Internetverbindung ist für den Betrieb nicht erforderlich.

## Dokumentation

- [Installation & Setup](docs/installation.md) — venv einrichten, RTP-MIDI-Sender konfigurieren, Bridge starten, Tests ausführen.
- [Konfiguration: system_config.json](docs/system-config.md) — vollständige Parameter-Referenz.
- [Mappings, Hybrid-Kanal-Modus & Undo](docs/mappings.md) — `midi_osc_mappings.json`, Kanal-/Bus-/DCA-Adressierung per Velocity, Undo-Konfiguration.
- [Web-Oberfläche](docs/web-ui.md) — Status/Config/Mappings/Logs-Tabs, technische Entscheidungen.
- [Plan: Integration als "Plugin" in x32-recorder](docs/plugin-integration.md) — historisches Planungsdokument; die tatsächliche Integration lief einfacher (siehe Roadmap unten).
- [Changelog](CHANGELOG.md) — alle bisherigen Änderungen, neueste zuerst.

## Roadmap

### Erledigt

- **x32-recorder-Integration:** läuft heute als `external_process`-Plugin über x32-recorders
  Plugin-System (GitHub-Import, Start/Stop/Logs über x32-recorders Settings-Seite) - einfacher als
  der ursprüngliche Plan in [docs/plugin-integration.md](docs/plugin-integration.md) (der einen
  reinen HTTP-Client ohne Prozessverwaltung vorsah, bevor es in x32-recorder überhaupt einen
  Plugin-Mechanismus gab). Diese Bridge bleibt dabei komplett eigenständig installier- und
  nutzbar - x32-recorder startet/stoppt sie nur bequemlichkeitshalber.

### 🚧 In Arbeit / ToDo

- **Bekannte Einschränkung:** `pymidi` implementiert kein Recovery-Journal (im Gegensatz zum ursprünglich anvisierten, aber nie funktionsfähigen `rtpmidi`-Journal). Auf verlustbehafteten Netzwerken gehen einzelne MIDI-Pakete daher ersatzlos verloren.
- **Bekannte Einschränkung:** Die Subnetz-Broadcast-Adresse wird unter der Annahme eines /24-Netzes berechnet (letztes Oktett → `.255`). In selteneren Netzwerken mit anderer Subnetzmaske könnte das nicht zutreffen — in dem Fall hilft weiterhin, `x32_ip` explizit zu setzen.

### 💡 Geplante Optimierungen

- **Intelligente Paket-Glättung** *(niedrige Priorität — aktuell keine komplexen Fader-Fahrten geplant, die das nötig machen würden)*: Optionale Reduzierung von aufeinanderfolgenden OSC-Befehlen (Throttling) bei schnellen Fader-Fahrten, um die Netzwerklast zu senken.
