# Konfiguration: `system_config.json`

[← Zurück zur README](../README.md)

Diese Datei steuert die Hardware-Schnittstellen, IP-Verbindungen und Protokoll-Parameter der Bridge. Für die Mapping-Konfiguration (`midi_osc_mappings.json`) siehe stattdessen [Mappings, Hybrid-Kanal-Modus & Undo](mappings.md).

| Parameter | Typ | Beschreibung |
|---|---|---|
| `x32_ip` | String | Feste IP-Adresse des X32 (z. B. `"192.168.178.50"`) oder `"auto"` für automatische Suche. |
| `x32_port` | Integer | Der OSC-Port des X32 (Standard: 10023). |
| `midi_source` | String | `"rtp"` (Standard) für RTP-MIDI/AppleMIDI, oder der exakte Name eines lokalen MIDI-Eingangsports (siehe `/api/midi/devices`) für ein direkt angeschlossenes Interface. Nur eine Quelle gleichzeitig aktiv. |
| `rtp_session_name` | String | Name, mit dem sich die Bridge im Bonjour-Netzwerk (`_apple-midi._udp`) anmeldet. |
| `rtp_host_ip` | String | IP-Adresse/Interface, unter der die Bridge ihren RTP-MIDI-Dienst ankündigt, oder `"auto"` zur automatischen Erkennung. |
| `rtp_local_port` | Integer | AppleMIDI-Control-Port der Bridge (Standard: 5004). Der Data-Port wird automatisch als `rtp_local_port + 1` gebunden. |
| `double_send` | Boolean | Aktiviert redundantes Senden jedes kritischen Befehls (Abstand: 5 ms) bei unzuverlässigen Netzwerkverbindungen. |
| `verify_delay_ms` | Integer | Zeitspanne (in ms), nach der das Skript den Zustand des Mischpults abfragt, um den Erfolg der Übertragung zu prüfen (Standard: 50). |
| `undo_timeout_ms` | Integer | Timeout für asynchrone State-Abfragen an das X32 (Standard: 100). |
| `discovery_interval_s` | Integer/Float | Intervall zwischen `/xinfo`-Broadcast-Versuchen während der Auto-Discovery, und Takt der Reconnect-Keep-Alive-Prüfung (siehe [Mappings & Undo](mappings.md)) (Standard: 5). |
| `web_enabled` | Boolean | Aktiviert die Web-Oberfläche (siehe [Web-Oberfläche](web-ui.md)). Standard: `true`. Lässt sich aus Sicherheitsgründen nicht über die Web-Oberfläche selbst deaktivieren — nur direkt in dieser Datei. |
| `web_host` | String | Interface, an das der Webserver gebunden wird (Standard: `"0.0.0.0"`, alle Interfaces). |
| `web_port` | Integer | Port der Web-Oberfläche (Standard: `8090`). |
| `allowed_peers` | Liste | Optionale Liste erlaubter Adressen (derzeit von der Bridge selbst noch nicht ausgewertet, nur in der Web-Oberfläche editierbar). |
| `log_level` | String | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` (Standard: `INFO`). |
