# Mappings, Hybrid-Kanal-Modus & Undo

[← Zurück zur README](../README.md)

Diese Datei (`midi_osc_mappings.json`) verknüpft MIDI-Eingänge (Noten und CC-Befehle) mit OSC-Befehlen des X32. Für die Netzwerk-/Systemkonfiguration siehe stattdessen [Konfiguration: system_config.json](system-config.md).

## Grundstruktur

**Trigger-Typen:**

- **Note On/Off:** Nutze `"type": "note_on"` oder `"type": "note_off"`. Für die Noten-Nummer kannst du sowohl Ganzzahlen (z. B. `60`) als auch Klartext-Noten (z. B. `"C3"`, `"F#4"`) eintragen — Klartext-Noten werden beim Start automatisch in MIDI-Nummern umgerechnet (Ableton-Oktavkonvention, C3 = 60). Seit der Web-Oberfläche (siehe [Web-Oberfläche](web-ui.md)) ist die Konvention für neu über den Browser angelegte Mappings, direkt die Nummer in der Datei zu speichern (die Web-Oberfläche zeigt trotzdem immer auch den Notennamen an) — von Hand geschriebene Klartext-Noten funktionieren aber weiterhin genauso.
- **Control Change (CC):** Nutze `"type": "control_change"` mit der entsprechenden CC-Nummer (z. B. `"10"` für Pan).

**Die Kern-Aktionen im Überblick:**

- **`set_channel`** (Kanalauswahl der aktuellen Klasse überschreiben): Löscht die aktive Auswahl der aktuellen Klasse und setzt den über die MIDI-Velocity übergebenen Index als exklusive Auswahl.
- **`add_channel`** (Index zur Auswahl der aktuellen Klasse hinzufügen): Behält bestehende Indizes bei und fügt den über die Velocity definierten Index hinzu.
- **`set_channel_class`** (Klasse wechseln): Legt über die Velocity fest, auf welche X32-Sektion (Kanäle/Bus/Aux In/FX Return/Matrix/DCA) sich `set_channel`/`add_channel` als Nächstes beziehen — siehe die Velocity-Tabelle weiter unten. Auswahlen anderer Klassen bleiben dabei erhalten. **Nicht** zu verwechseln mit `set_send_bus` (siehe [Sends](#sends-ein-kanal-auf-einen-bestimmten-mixbus-set_send_bus-active_send_bus) weiter unten) — das ist eine komplett eigene, zweite Auswahl-Dimension für den Ziel-Bus eines Kanal-Sends, keine weitere Klasse.
- **`set_send_bus`** (Send-Ziel-Bus wählen): Legt über die Velocity (1-16 = Bus 1-16) fest, welchen Mixbus der Platzhalter `{active_send_bus}` in Mapping-Aktionen adressiert — für Sends eines Kanals auf einen bestimmten Mixbus, siehe [Sends](#sends-ein-kanal-auf-einen-bestimmten-mixbus-set_send_bus-active_send_bus) weiter unten.
- **Statische Mappings** (z. B. Mutes): Senden feste OSC-Werte an die Zielkanäle. `"value"` ist eine Zahl.
- **Dynamische Werte** (z. B. Volume / Pan): Verwenden `"value": "midi_value"`, um den MIDI-Eingangswert (0-127) dynamisch einzulesen und zu skalieren.
- **Toggle** (z. B. Mute per einem einzigen Befehl an-/ausschalten): `"value": "toggle"` fragt vor dem Senden den aktuellen Ist-Wert am Zielpfad ab (`query_osc_value`) und sendet den jeweils anderen der beiden konfigurierten Werte zurück — standardmäßig `"toggle_on_value": 1` / `"toggle_off_value": 0`, beide über die Aktion anpassbar. Unterliegt denselben Hybrid-Kanal-Regeln wie ein fester Wert (Velocity wählt den Kanal, nicht den Wert) — ein Toggle ist nur eine andere "welchen Wert senden"-Strategie, kein eigener Adressierungsmodus. Schlägt die Abfrage fehl (Timeout), wird `toggle_on_value` gesendet und eine Warnung geloggt.

  **Toggle vs. zwei getrennte Befehle:** Ein Toggle braucht nur eine MIDI-Note, hat aber ein Risiko — wird der Zustand direkt am Pult geändert (nicht über die Bridge), bleibt das für den nächsten Toggle unsichtbar; da aber immer der *aktuelle* Wert live abgefragt wird (nicht ein intern gemerkter Zustand), bleibt ein Toggle trotzdem korrekt zum tatsächlichen Pultzustand — nur eben einen OSC-Roundtrip langsamer als ein fester Wert. Wer ganz sichergehen will, dass ein Befehl *garantiert* mutet und ein anderer *garantiert* entmutet (z. B. für eine Show-Automation, die nie "raten" soll), definiert stattdessen zwei separate Mappings mit demselben Pfad — eines mit `"value": 1`, eines mit `"value": 0`, verschiedene Trigger-Noten. Beides ist schon heute ohne weitere Voraussetzungen möglich.

  **`opposite_trigger`: Toggle mit zwei Noten statt einer** — verbindet die beiden obigen Ansätze zu einer dritten Option, ohne einen neuen Wert-Modus zu brauchen. Ein Mapping mit `"value": "toggle"` kann optional eine zweite Trigger-Note bekommen:
  ```json
  {
    "name": "fx_mute",
    "trigger": { "type": "note_on", "number": 72 },
    "opposite_trigger": { "type": "note_on", "number": 73 },
    "actions": [{ "path": "/config/mute/3", "value": "toggle" }]
  }
  ```
  `opposite_trigger` fehlt/leer (Standard) → unverändert der echte, einzeln-notige Toggle von oben (fragt bei jedem Auslösen live den Pultzustand ab). `opposite_trigger` gesetzt → **keine** Abfrage mehr: die Note oben (`trigger`) sendet immer `toggle_on_value`, `opposite_trigger` sendet immer `toggle_off_value` — zwei feste, garantiert richtige Tasten statt einer, die den aktuellen Zustand erraten muss. Praktisch dasselbe Ergebnis wie "zwei getrennte Mappings mit demselben Pfad" oben, nur als eine einzige Mapping-Definition mit einer zweiten Note statt zwei komplett eigenständigen Mappings — im Web-UI-Editor deshalb auch nur ein zusätzliches optionales Feld direkt bei der jeweiligen Toggle-Aktion (neben An-/Aus-Wert), statt eines zweiten ganzen Mapping-Eintrags oder eines mapping-weiten Felds ohne erkennbaren Bezug. `opposite_trigger` hat immer denselben Trigger-Typ wie `trigger` (wie schon bei `undo_trigger`) und nimmt an derselben Duplikat-Prüfung/Notenvorschlag-Logik teil. Bei einer Mapping-Aktion, die nicht `"value": "toggle"` ist, hat `opposite_trigger` keinen besonderen Effekt — beide Noten lösen dann einfach identisch dieselbe(n) Aktion(en) aus.

- **Relativer dB-Offset** (z. B. "Kanal um 10dB lauter machen"): `"value": "relative_db"` fragt den aktuellen Fader-Wert am Zielpfad ab (`query_osc_value`, wie beim Toggle), rechnet ihn über die X32-Faderkurve (`FADER_CURVE_BREAKPOINTS`/`x32_float_to_db`/`x32_db_to_float`, siehe unten) in dB um, addiert `db_delta`, rechnet zurück und sendet den neuen (auf 0.0-1.0 geklemmten) Fader-Wert. Bewusst **kein** Prozent-Modus: der X32-Fader ist intern nicht linear, ein Prozent-Schritt auf dem rohen OSC-Wert würde je nach aktueller Position eine völlig unterschiedliche wahrgenommene Lautstärkeänderung bedeuten — dB ist dagegen unabhängig vom Startpunkt konsistent.

  **`db_delta` als feste Zahl** — jeder Trigger ändert den Pegel immer um denselben Betrag:
  ```json
  { "path": "/ch/{active_channels}/mix/fader", "value": "relative_db", "db_delta": 10 }
  ```
  Für "leiser machen" reicht ein negativer Wert (`"db_delta": -10`) in einem zweiten, eigenen Mapping — kein Richtungsparameter nötig, gleiches Muster wie "zwei getrennte Mappings für garantiertes Mute/Unmute" oben. Unterliegt denselben Hybrid-Kanal-Regeln wie Toggle/ein fester Wert (Velocity wählt den Kanal).

  **`db_delta: "midi_value"`** — die Velocity bestimmt den Betrag proportional (für einen Regler/Fader statt eines einfachen Tasters), skaliert über `"db_scale": {"max_velocity": ..., "max_db": ...}`:
  ```json
  {
    "path": "/ch/{active_channels}/mix/fader",
    "value": "relative_db",
    "db_delta": "midi_value",
    "db_scale": { "max_velocity": 100, "max_db": 20 }
  }
  ```
  Linear ab Velocity 0 (= 0dB Änderung) bis `max_velocity` (= `max_db` Änderung), bei höherer tatsächlicher Velocity auf `max_db` geklemmt. `max_velocity` muss nicht 127 sein — z. B. `max_velocity: 100, max_db: 20` macht den Kopfrechnung einfacher (Velocity 50 = +10dB, Velocity 100 = +20dB). Velocity kann hier nicht gleichzeitig zur Kanalwahl verwendet werden (wie bei `"value": "midi_value"`) — der Befehl geht an alle aktuell vorausgewählten Kanäle (`active_channels`).

  **Kein Fallback bei Query-Timeout, anders als Toggle:** schlägt die Abfrage des aktuellen Werts fehl, wird — anders als beim Toggle, der dann `toggle_on_value` sendet — **gar nichts** gesendet (nur eine Warnung geloggt). Ein geratener Sprung auf einen falschen Pegel wäre schlimmer als ein einmalig ausbleibender Tastendruck.

  **Die X32-Faderkurve:** OSC transportiert einen Fader-Wert als Float `0.0-1.0`, keine dB direkt — die Umrechnung folgt einer stückweise linearen (in dB) Kurve mit unterschiedlicher Steigung je Bereich:

  | Float | dB |
  |---|---|
  | 0.0 | -90 (praktischer Boden/"aus") |
  | 0.0625 | -60 |
  | 0.25 | -30 |
  | 0.375 | -19 |
  | 0.5 | -10 |
  | 0.75 | 0 |
  | 1.0 | +10 |

  Community-Standard-Eckpunkte, gegen ein echtes X32-Rack verifiziert (siehe CHANGELOG für das Datum) — bei Abweichungen einfach `FADER_CURVE_BREAKPOINTS` in `main.py` anpassen.

## Der Hybrid-Kanal-Modus

Der Hybrid-Kanal-Modus nutzt die Anschlagstärke (Velocity) einer MIDI-Note nicht für den Wert (z. B. Lautstärke), sondern zur direkten Adressierung des Zielkanals. Er ist vollständig implementiert (`is_hybrid_single_channel`/`is_hybrid_multi_channel` in `execute_mapping_action`) und gilt für die Aktionen *innerhalb* eines Mappings — nicht für `set_channel`/`add_channel` selbst, siehe Hinweis unten.

**Regeln:**

- **Dynamischer Wert (Hybrid-Modus INAKTIV):** Braucht der OSC-Befehl einen variablen Wert (`"value": "midi_value"`, z. B. Pan oder Fader), wird die Velocity über `scale` zur Berechnung dieses Werts genutzt. Der Befehl geht an alle aktuell vorausgewählten Kanäle (`active_channels`) — die Velocity kann hier nicht gleichzeitig für die Kanalwahl verwendet werden, da sie für den Wert selbst gebraucht wird.
- **Statischer Wert (Hybrid-Modus AKTIV):** Ist der OSC-Wert fest (z. B. Mute an = `1`), wird die Velocity stattdessen als Kanalnummer interpretiert:

  | Velocity | Ziel-Kanal | Verhalten |
  |---|---|---|
  | 1-126 | Einzelauswahl: nur dieser eine Kanal, geklammert auf 1-32 (z. B. Velocity 9 → Kanal 09; Velocity 50 → Kanal 32, da das X32 nur 32 Kanäle hat) | Die globale Kanalauswahl (`active_channels`) bleibt unberührt. |
  | 127 | Gruppenauswahl: alle aktuell selektierten Kanäle (`active_channels`) | Befehl wird simultan an die ganze Gruppe gesendet. |

  Velocity 0 löst bewusst **keine** Aktion aus (weder Einzel- noch Gruppenauswahl) — siehe Begründung unten.

> **Wichtig:** Diese Velocity-als-Kanal-Logik gilt nur für die Aktionen *innerhalb* eines Mappings (z. B. Mute). Für `set_channel`/`add_channel` selbst wird die Velocity immer direkt (geklammert auf 1-32) als Kanalnummer übernommen — Velocity 127 setzt dort schlicht Kanal 32, es gibt keinen Gruppen-Sonderfall.

**Praxis-Vergleich (Mute vs. Pan):**

- **Szenario A — Mute (Hybrid-Modus AKTIV):** MIDI-Note G3 (Mute-Befehl, fester OSC-Wert `1`). Velocity 12 schaltet sofort und exklusiv Kanal 12 stumm; Velocity 127 schaltet alle Kanäle stumm, die vorher als Gruppe ausgewählt wurden.
- **Szenario B — Pan (Hybrid-Modus INAKTIV):** MIDI-Note A3 (Pan-Befehl, `"value": "midi_value"`, Skala `midi_to_pan`). Velocity 64 setzt den Pan-Wert auf Mitte (≈0.5) für die zuvor ausgewählten Kanäle — die Velocity kann hier nicht zusätzlich für die Kanalwahl genutzt werden.

**Vorteile:**

- **Effizienz:** Keine 32 einzelnen Noten für "Mute Kanal 1 bis 32" nötig — eine einzige Note reicht, der Kanal wird über die Anschlagstärke bestimmt.
- **Auswahl-Schutz:** Kanal 12 lässt sich zwischendurch stummschalten (Velocity 12), ohne die zuvor ausgewählte Fader-Gruppe (z. B. Kanäle 3 und 4) aufzulösen.

### Erweiterung auf Bus/Aux In/FX Return/Matrix/DCA

Der Hybrid-Kanal-Modus war ursprünglich fest auf `/ch/`-Eingangskanäle (1-32, zweistellig nullaufgefüllt) zugeschnitten. Das ist inzwischen auf weitere X32-Adressbereiche erweitert, ohne bestehende `/ch/`-Mappings zu verändern:

| Klasse (intern) | X32-Adressbereich | Bereich | Padding |
|---|---|---|---|
| `ch` (Eingangskanäle) | `/ch/01-32/...` | 1-32 | 2-stellig — Standard/Fallback |
| `bus` (Mixbusse) | `/bus/01-16/...` | 1-16 | 2-stellig |
| `auxin` (Aux In) | `/auxin/01-08/...` | 1-8 | 2-stellig |
| `fxrtn` (FX Return) | `/fxrtn/01-08/...` | 1-8 | 2-stellig |
| `mtx` (Matrix) | `/mtx/01-06/...` | 1-6 | 2-stellig |
| `dca` (DCA-Gruppen) | `/dca/1-8/...` | 1-8 | keine Nullauffüllung (`5`, nicht `05`) |

Bereich und Padding sind für jede Klasse fest im Code hinterlegt (`CLASS_ADDRESS_INFO` in `main.py`) — bewusst **nicht** pro Mapping konfigurierbar, da das Hardware-Fakten des X32 sind, keine Geschmacksfrage. **Main/LR** (`/main/st/...`, `/main/m/...`) hat gar keine Kanalnummer und braucht daher keinen Eintrag — ein Mapping mit festem Pfad ohne `{active_channels}`-Platzhalter (z. B. `"path": "/main/st/mix/on"`) funktioniert dafür bereits unverändert.

**Neue feste Aktion `set_channel_class`:** Legt fest, auf welche Klasse sich `set_channel`/`add_channel` als Nächstes beziehen — über die Velocity, nach einer fest hinterlegten Tabelle (bewusst hardcodiert, siehe Begründung oben):

| Velocity | Klasse |
|---|---|
| 1 | `ch` (Standard) |
| 2 | `bus` |
| 3 | `auxin` |
| 4 | `fxrtn` |
| 5 | `mtx` |
| 6 | `dca` |

Wie `set_channel`/`add_channel` ist `set_channel_class` ein fester, nicht löschbarer Eintrag in der Mappings-Liste (wird beim Laden automatisch ergänzt, falls er fehlt).

**Die Auswahl bleibt über Klassen hinweg erhalten:** Intern ist aus der einen, `/ch/`-exklusiven `active_channels`-Liste eine Zuordnung Klasse → Liste geworden (`class_selections` in `main.py`). `set_channel`/`add_channel` wirken dabei immer nur auf die *aktuell aktive* Klasse — ein Wechsel der Klasse per `set_channel_class` löscht nicht die Auswahl der anderen Klassen. Damit lässt sich z. B. eine Auswahl aus einzelnen Kanälen, einer DCA und einem Bus gleichzeitig aufbauen (`set_channel_class` → Kanäle wählen, `set_channel_class` → DCA wählen, `add_channel`, `set_channel_class` → Bus wählen, `add_channel`, ...).

**Eine Mapping-Definition für alle Klassen:** Damit nicht jede Aktion (Mute, Fader, ...) einmal pro Klasse dupliziert werden muss, gibt es einen zusätzlichen Platzhalter `{active_class}` für den OSC-Pfad, z. B. `"path": "/{active_class}/{active_channels}/mix/on"`. Eine so definierte Aktion iteriert beim Auslösen über **alle** Klassen mit nicht-leerer Auswahl gleichzeitig und sendet pro Element einen eigenen OSC-Befehl (ein einziges "Mute"-Mapping kann so in einem Rutsch ein paar Kanäle, eine DCA und einen Bus gleichzeitig muten). Bestehende Mappings mit hartkodiertem `/ch/...`-Pfad (ohne `{active_class}`) sind davon komplett unberührt — sie beziehen sich weiterhin ausschließlich auf die `ch`-Auswahl, unabhängig davon, welche Klasse gerade über `set_channel_class` aktiv ist.

**Echte Grenze, die bleibt:** Eine klassenübergreifende Aktion funktioniert nur für OSC-Felder, die es in jeder beteiligten Klasse gibt (Mute/Fader: überall vorhanden). Pan gibt es z. B. bei DCA nicht — eine `{active_class}`-Pan-Aktion, deren Auswahl eine DCA enthält, würde für den DCA-Eintrag einen ungültigen OSC-Pfad erzeugen. Für Mute/Fader ist das unproblematisch.

### Sends: ein Kanal auf einen bestimmten Mixbus (`set_send_bus`, `{active_send_bus}`)

`{active_class}`/`{active_channels}` wählen immer nur **eine** Nummer (welcher Kanal/welche Klasse). Ein Channel-Send auf einen Mixbus braucht aber **zwei** unabhängige Nummern im selben OSC-Pfad — den Quellkanal *und* den Ziel-Bus, z. B. `/ch/02/mix/10/on` (Kanal 2, Send auf Bus 10). Dafür bewusst **keine** Erweiterung von `set_channel_class` (dessen Velocity-Tabelle wählt eine *Adressfamilie*, keine zweite Zahl) — stattdessen eine eigene, unabhängige Aktion und ein eigener Platzhalter, analog zu `set_channel_class`:

**Neue feste Aktion `set_send_bus`:** Legt über die Velocity fest, welchen Mixbus der Platzhalter `{active_send_bus}` als Nächstes adressiert — direkt Velocity = Busnummer, keine Umwege über eine Tabelle:

| Velocity | Bus |
|---|---|
| 1 | Mix 1 |
| ... | ... |
| 16 | Mix 16 |

Werte außerhalb 1-16 werden geklemmt (0 → 1, 127 → 16). Wie `set_channel`/`add_channel`/`set_channel_class` ist `set_send_bus` ein fester, nicht löschbarer Eintrag in der Mappings-Liste (wird beim Laden automatisch ergänzt, falls er fehlt) — unabhängig von `active_class`/`class_selections`, es gibt kein `add_send_bus`, da ein Send-Ziel immer genau ein Bus zur Zeit ist (kein Mehrfach-Ziel wie bei der Kanalauswahl).

**Verwendung im Mapping:** `{active_send_bus}` einfach zusätzlich zu `{active_channels}` im Pfad verwenden, z. B. um den Send von Kanal 2 auf Bus 10 zu muten:
```json
{ "path": "/ch/{active_channels}/mix/{active_send_bus}/on", "value": "toggle" }
```
Ablauf: `set_send_bus` (Velocity 10) → `set_channel` (Velocity 2) → obiges Mapping auslösen. Funktioniert mit allen Wert-Modi (fest/`midi_value`/Toggle/`relative_db`) und dem Hybrid-Einzel-/Gruppen-Modus genau wie `{active_channels}` allein — nur dass zusätzlich der Send-Ziel-Bus in den Pfad eingesetzt wird. Ist `{active_send_bus}` im Pfad, `set_send_bus` aber noch nie ausgelöst worden, wird auf Bus 1 zurückgefallen (mit einer Log-Warnung) — analog zum "keine Kanäle ausgewählt"-Fallback von `{active_channels}`.

### Note-On mit Velocity 0 wird wie ein echtes Note-Off behandelt

Das MIDI-1.0-Protokoll erlaubt es Sendern, ein Note-Off als Note-On mit Velocity 0 zu kodieren (eine verbreitete Bandbreiten-Optimierung per Running Status), statt eine echte Note-Off-Nachricht (Statusbyte `0x8n`) zu senden — beide Varianten bedeuten "Taste losgelassen", nicht "neues, absichtliches Ereignis". Da der Hybrid-Kanal-Modus Velocity 0 zwischenzeitlich selbst als eigenständiges Signal genutzt hat, gab es hier einen Konflikt: Sendet ein MIDI-Ausgang Velocity-0-Note-On für "Taste losgelassen" statt einer echten Note-Off-Nachricht, hätte jedes Loslassen einer Note ungewollt eine Gruppen-Aktion ausgelöst. Die Bridge normalisiert ein `note_on` mit Velocity 0 daher bereits bei der Übersetzung des rohen MIDI-Kommandos (`build_midi_event`, gemeinsam genutzt von RTP-MIDI- und lokalem MIDI-Pfad) zu einem `note_off`-Ereignis — dadurch verhält es sich exakt wie eine echte Note-Off-Nachricht (keine der beiden Varianten löst je ein Mapping aus, sofern keine explizite `"type": "note_off"`-Mapping existiert) und der Konflikt mit der Gruppen-Logik ist strukturell ausgeschlossen. Das erste Vorkommen pro Lauf wird informativ geloggt, damit sichtbar bleibt, wenn ein MIDI-Sender diese Konvention nutzt. Betrifft ausschließlich `note_on`/`note_off` — bei `control_change` ist der Wert `0` unzweideutig ein normaler, gültiger Reglerwert und wird unverändert für den Hybrid-Modus ausgewertet.

## OSC-Queries & Undo-Konfiguration (Zustandswiederherstellung)

Ein besonderes Merkmal dieses Daemons ist die First-Write-Wins Undo-Logik. Sie sorgt dafür, dass automatische Spur-Aktionen des Rechners die manuellen Einstellungen am Pult nicht unumkehrbar überschreiben.

**Wie funktioniert ein OSC-Query auf dem X32?**

Das X32 arbeitet über das UDP-Protokoll. Um den aktuellen Zustand eines Reglers (z. B. Fader oder Pan) zu erfahren, sendet der Daemon eine leere OSC-Nachricht an den entsprechenden Pfad (z. B. `/ch/01/mix/pan`). Das X32 antwortet asynchron über dieselbe UDP-Verbindung mit dem aktuellen Wert (z. B. `0.5`).

> Dieses Query/Reply-Verfahren (leere Nachricht rein, Wert per UDP zurück) ist im Daemon implementiert (`query_osc_value`, über einen dedizierten UDP-Socket mit `undo_timeout_ms`-Timeout) und wurde end-to-end gegen ein echtes X32-Rack verifiziert: lesende Abfrage, First-Write-Wins-Sicherung beim ersten Schreibvorgang, und vollständige Wiederherstellung des Originalwerts per Undo-Trigger funktionieren zuverlässig.

**Reconnect-Keep-Alives:** Bis vor Kurzem gab es nach der initialen X32-Erkennung keinerlei laufende Überprüfung mehr, ob das Pult noch erreichbar ist — ein WLAN-Aussetzer, Stromausfall am Pult oder ein gezogenes Kabel wäre unbemerkt geblieben, OSC-Befehle wären danach einfach ins Leere gelaufen, bis jemand die Bridge neu startet. `monitor_x32_connection()` fragt seitdem periodisch (im Takt von `discovery_interval_s`) per `query_osc_value("/xinfo")` beim aktuell bekannten `x32_ip` nach, ob das Pult noch antwortet. Erst nach 3 aufeinanderfolgenden ausbleibenden Antworten (nicht schon beim ersten verlorenen UDP-Paket, das auf einem gesunden Netzwerk gelegentlich vorkommt) gilt die Verbindung als verloren:

- Bei `"x32_ip": "auto"`: `x32_ip` wird zurückgesetzt und die `/xinfo`-Broadcast-Erkennung automatisch neu gestartet — sobald das Pult wieder antwortet, greift dieselbe Logik wie beim ursprünglichen Start.
- Bei einer fest eingetragenen IP: die Bridge fragt einfach weiter an genau dieser Adresse an, bis das Pult wieder antwortet.

Der Verbindungsstatus (`x32_connected`) ist über `/api/status` und den Status-Tab der Web-Oberfläche sichtbar ("X32-Verbindung: Verbunden" / "Nicht erreichbar (Reconnect läuft)"); Zustandswechsel werden einmalig geloggt, nicht bei jedem einzelnen Ping-Versuch.

**So konfigurierst du Undo-Befehle in deinen Mappings:**

Wenn du möchtest, dass ein Wert vor der Änderung abgefragt und später per MIDI-Befehl wieder auf den Originalzustand zurückgesetzt werden kann, musst du drei Parameter im Mapping-Objekt definieren:

- `"save_state": true` — Signalisiert dem Daemon, dass er vor dem ersten Schreibvorgang den aktuellen Ist-Wert vom X32 abfragen muss.
- `"undo_trigger"` — Definiert die MIDI-Note, die den Wiederherstellungs-Befehl auslöst.
- `"scale"` — Bestimmt das Umrechnungsverfahren, damit die Werte korrekt verarbeitet werden.

Beispiel für ein Panning-Mapping mit Undo-Sicherung:

```json
{
  "name": "vocal_pan_with_undo",
  "trigger": { "type": "note_on", "number": "A3" },
  "save_state": true,
  "actions": [
    {
      "path": "/ch/{active_channels}/mix/pan",
      "value": "midi_value",
      "scale": "midi_to_pan"
    }
  ],
  "undo_trigger": { "type": "note_on", "number": "A#3" }
}
```

**Ablauf der Undo-Logik im Daemon:**

1. **Trigger A3 geht ein:** Der Daemon prüft, ob im In-Memory `undo_cache` bereits ein Wert für `/ch/09/mix/pan` existiert.
2. **Erster Schreibvorgang (First-Write):** Da der Cache leer ist, sendet der Daemon asynchron eine OSC-Anfrage an das X32, wartet maximal 100 ms auf die Antwort, sichert den Originalwert (z. B. `0.5`) im Cache und führt danach die programmierte Änderung auf den neuen Wert aus.
3. **Folgende Änderungen:** Solange kein Undo ausgeführt wurde, bleibt der originale Wert im Cache unberührt. Nachfolgende Automationen überschreiben den Mix nicht weiter im Cache.
4. **Trigger A#3 (Undo) geht ein:** Der Daemon liest den gecachten Originalwert (`0.5`) aus und sendet ihn zurück an das X32. Anschließend wird der Cache-Eintrag für diesen Pfad gelöscht.

**Unterstützte Skalierungen (`scale`):**

- **`midi_to_pan`**: Skaliert linear von `[0, 127]` → `[0.0, 1.0]`. Die MIDI-Mitte 64 wird exakt zu 0.5 (Pan Center).
- **`midi_to_fader`**: Rechnet den MIDI-Wert über eine quadratische Kurve `OSC = (MIDI / 127.0)^2` um, um die logarithmische Fader-Kurve des X32 abzubilden.
- **`invert`**: Invertiert den MIDI-Eingangsbereich (z. B. für Mute-Schalter).
