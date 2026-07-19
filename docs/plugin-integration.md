# Plan: Integration als "Plugin" in x32-recorder

[← Zurück zur README](../README.md)

**Status: überholt, nur noch historisch.** Die tatsächliche Integration lief anders als hier geplant: x32-recorder bekam einen generischen Plugin-Mechanismus (`django_app`/`external_process`), und diese Bridge läuft heute darüber als `external_process`-Plugin - x32-recorder startet/stoppt/überwacht sie per PID-Datei (ähnlich `manage_services.py`), statt sie nur per HTTP-Client read-only anzusprechen wie unten geplant. Bleibt dabei komplett eigenständig installier-/nutzbar, wie hier ursprünglich als Leitprinzip festgehalten. Der Rest dieses Dokuments ist unverändert als Aufzeichnung der damaligen Überlegungen erhalten.

## Leitprinzip

**x32-midi-bridge bleibt ein komplett eigenständiger Dienst.** Er wird weiterhin separat installiert (`uv venv`, `uv sync`), separat gestartet (`uv run main.py`) und hat keinerlei Code- oder Abhängigkeits-Verbindung zu x32-recorder. "Plugin" bedeutet hier: **x32-recorder verbindet sich optional zu einer bereits laufenden Bridge über deren bestehende HTTP/JSON-API** — nicht, dass x32-recorder die Bridge startet, stoppt oder einbettet. Läuft keine Bridge, zeigt x32-recorder einfach "nicht verbunden" und bleibt ansonsten voll funktionsfähig.

Diese Abgrenzung ist bewusst strenger als x32-recorders eigenes Muster (dort startet/stoppt `manage_services.py` beide eigenen Prozesse zentral) — die Bridge ist kein Teil von x32-recorder, sondern ein optionaler Nachbar.

## Ausgangslage (Rechercheergebnisse in x32-recorder, Stand dieser Planung)

- **Prozessverwaltung:** `manage_services.py` verwaltet Django/Waitress (Port 8000) und den C-Controller über PID-Dateien (`./pids/`) mit reinem OS-Level-Liveness-Check (`tasklist`/`os.kill(pid, 0)`) — **kein** HTTP-Health-Check. Produktion läuft über eine systemd-Unit, die dieses Skript einmalig aufruft.
- **Django-Struktur:** Nur eine App (`recorder`). Keine bestehende Anbindung an einen externen HTTP-Dienst — kein `requests`/`httpx` irgendwo im Code. Eine Integration wäre neue Infrastruktur, kein Ausbau von etwas Bestehendem.
- **Kein Backup-Mechanismus:** Weder für die eigene SQLite-DB noch sonst irgendwo im Projekt existiert heute eine Backup-Routine (kein Management-Command, kein Cron/Timer). Die früher notierte Idee, `system_config.json`/`midi_osc_mappings.json` "in die Django-DB zu spiegeln, damit sie automatisch mitgesichert werden", setzt also voraus, dass x32-recorder **zuerst überhaupt eine eigene DB-Backup-Mechanik bekommt** — das ist eine Vorbedingung außerhalb dieser Planung, keine Aufgabe der Bridge.
- **Bestehender Roadmap-Eintrag in x32-recorder** (`ROADMAP.md`, Abschnitt `# todo`): *"OSC integrieren für Playback/Record Mixer Konfiguration – zB via python-osc"*. Das beschreibt bisher **direkte** OSC-Anbindung (eigene `python-osc`-Abhängigkeit in x32-recorder), nicht "mit einer Sibling-Bridge sprechen". Diese Planung würde diesen Punkt **ersetzen/neu interpretieren**, nicht duplizieren.
- **Ports:** Django/Waitress 8000, Vite-Dev-Server 5173 (proxied `/api` → 8000) — beide bestätigt unverändert. Bridge-Port 8090 kollidiert mit keinem der beiden (war schon bei dessen Wahl der Grund).
- **Kein Plugin-/Extension-/Hook-Mechanismus** irgendeiner Art in x32-recorder vorhanden. Alles wäre neu zu bauen.

## Architektur-Entscheidung: Django-Backend als Client, nicht der Browser direkt

Zwei Optionen wurden abgewogen:

1. **(Empfohlen) x32-recorders Django-Backend ruft die Bridge-API serverseitig auf** (`requests`, neue Abhängigkeit in x32-recorder) und reicht relevante Daten über x32-recorders **eigene** `/api/...`-Endpunkte an dessen Frontend weiter. Passt zum bestehenden Muster (das Vite-Frontend spricht heute ausschließlich mit Djangos eigener API, nicht mit mehreren Backend-Origins) und braucht auf Bridge-Seite **keine CORS-Änderung**, da es sich um einen Server-zu-Server-Aufruf handelt, keinen Browser-Aufruf.
2. **(Alternative, nicht empfohlen) Das Vite-Frontend ruft `http://localhost:8090/api/...` direkt aus dem Browser auf.** Würde CORS-Header auf Bridge-Seite erfordern und zwei unabhängige Backend-Origins im selben Frontend mischen — mehr Kopplung, ohne einen klaren Vorteil gegenüber Option 1.

## Phasenplan

### Phase 0 — Erkennung ("läuft gerade eine Bridge?")

x32-recorder fragt periodisch `GET http://localhost:8090/api/status`. Antwortet das, ist eine Bridge da; sonst nicht. Das ist der einzige nötige "Health-Check" — die Bridge braucht dafür keine Änderung, `/api/status` existiert bereits und liefert schon alles Nötige (X32-IP, Verbindungsstatus, MIDI-Quelle).

### Phase 1 — Read-only Statusanzeige in x32-recorder

Ein kleines Widget/Panel in x32-recorders Oberfläche zeigt die von der Bridge gemeldeten Werte an (verbundenes X32, MIDI-Quelle, aktive Klasse/Auswahl) — rein informativ, keine Rückwirkung auf die Bridge. Kleinster sinnvoller erster Schritt mit echtem Nutzwert.

### Phase 2 — Config-/Mappings-Sicherung

Setzt voraus: x32-recorder hat inzwischen eine eigene DB-Backup-Mechanik (siehe oben, Vorbedingung). Erst dann: ein neues Django-Modell speichert Snapshots von `/api/config` und `/api/mappings` (z. B. bei jedem Aufruf eines "Jetzt sichern"-Buttons, oder periodisch) — die JSON-Inhalte werden dadurch Teil der normalen DB-Sicherung, ohne dass die Bridge selbst etwas davon weiß oder tun muss (sie beantwortet nur zwei GET-Requests, die es schon gibt).

### Phase 3 — Steuerung aus x32-recorder heraus (optional, ggf. nie nötig)

Falls gewünscht: Mappings/Config auch aus x32-recorders Oberfläche heraus bearbeitbar machen (PUT-Aufrufe gegen die Bridge-API). Deutlich mehr Aufwand für wenig zusätzlichen Nutzen, solange die Bridge ihre eigene, schon fertige Weboberfläche hat — nur verfolgen, falls sich ein konkreter Bedarf zeigt (z. B. eine gemeinsame Oberfläche für Front-of-House während einer Show).

## Was sich auf dieser Seite (x32-midi-bridge) ändern müsste

Erfreulich wenig — die bestehende Architektur ist schon integrationsfreundlich:

- **Nichts Strukturelles.** Die HTTP/JSON-API existiert bereits vollständig für die eigene Weboberfläche.
- Optional: die für eine Integration relevanten Endpunkte (`/api/status`, `/api/config`, `/api/mappings`, jeweils GET) als "stabile, für externe Nutzung gedachte" Oberfläche kennzeichnen (z. B. hier in dieser Doku), damit spätere Änderungen an internen/UI-spezifischen Endpunkten (Test-MIDI, OSC-Query, SSE-Streams) nicht versehentlich als Breaking Change für eine externe Integration missverstanden werden.
- Nur falls doch Option 2 (direkter Browser-Zugriff) gewählt wird: CORS-Header ergänzen. Aktuell nicht vorgesehen.

## Was auf x32-recorder-Seite gebaut werden müsste (dort, nicht hier)

- Neue Django-App (Arbeitsname z. B. `midi_bridge_client`) mit `requests` als neuer Abhängigkeit.
- Health-Check + Statusanzeige (Phase 1).
- Eigene DB-Backup-Mechanik (Vorbedingung für Phase 2, unabhängig von dieser Bridge nötig).
- Anpassung/Ersetzung des `ROADMAP.md`-Eintrags "OSC integrieren ... via python-osc" durch einen Verweis auf diesen Plan.

## Offene Punkte

- Zeitpunkt: kein aktueller Bedarf, beide Projekte laufen unabhängig weiter nutzbar. Diese Planung liegt bereit, wenn der Bedarf entsteht.
- Sollte x32-recorder irgendwann doch einen echten Plugin-/Extension-Mechanismus bekommen (aktuell keiner vorhanden), wäre diese Planung entsprechend anzupassen — aktuell ist "HTTP-Client gegen eine laufende Sibling-Instanz" der pragmatischste Weg ohne Vorarbeiten auf x32-recorder-Seite vorauszusetzen.
