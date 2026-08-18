function $(id) {
  return document.getElementById(id);
}

function showMessage(el, text, isError) {
  if (!text) {
    el.textContent = "";
    el.className = "message";
    return;
  }
  el.textContent = text;
  el.className = "message " + (isError ? "error" : "ok");
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  let body = null;
  try {
    body = await res.json();
  } catch (e) {
    body = null;
  }
  if (!res.ok) {
    const detail = body && body.details ? "\n" + body.details.join("\n") : "";
    throw new Error((body && body.error ? body.error : res.statusText) + detail);
  }
  return body;
}

// ---- Tabs ----
function initTabs() {
  const buttons = document.querySelectorAll(".tab-btn");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      $("tab-" + btn.dataset.tab).classList.add("active");
    });
  });
}

// ---- Status ----
async function refreshStatus() {
  try {
    const status = await fetchJson("/api/status");
    $("s-x32-ip").textContent = status.x32_ip || "(nicht aufgelöst)";
    $("s-x32-port").textContent = status.x32_port;
    $("s-x32-connected").textContent = status.x32_connected ? "Verbunden" : "Nicht erreichbar (Reconnect läuft)";
    $("s-rtp-status").textContent = status.midi_input_status;
    $("s-rtp-advertised").textContent = status.rtp_advertised_name
      ? `${status.rtp_advertised_name} (${status.rtp_advertised_host}:${status.rtp_advertised_port})`
      : "(nicht aktiv - midi_source ist nicht \"rtp\", oder Werbung ist noch nicht gestartet)";
    $("s-active-class").textContent = status.active_class;
    $("s-active-channels").textContent = JSON.stringify(status.class_selections, null, 2);
    $("s-peers").textContent = status.rtp_connected_peers.length ? status.rtp_connected_peers.join(", ") : "(keine)";
    $("s-web-port").textContent = status.web_port;
    $("s-undo-cache").textContent = JSON.stringify(status.undo_cache, null, 2);
  } catch (e) {
    // status tab is polled quietly; ignore transient errors
  }
}

// ---- Config ----
// A structured form instead of a raw-JSON textarea: every field has the
// right input type (number/checkbox/select), so typos, wrong types, or an
// accidentally-dropped key can't happen the way they can when editing the
// file by hand - the form always submits the complete, correctly-typed set
// of keys the bridge expects.

function setAutoToggle(checkboxId, rowId, valueInputId, value) {
  const isAuto = value === "auto" || value === "" || value == null;
  $(checkboxId).checked = isAuto;
  $(rowId).hidden = isAuto;
  if (!isAuto) $(valueInputId).value = value;
}

function readAutoToggle(checkboxId, valueInputId) {
  return $(checkboxId).checked ? "auto" : $(valueInputId).value.trim();
}

let currentAllowedPeers = [];

function renderAllowedPeers(peers) {
  currentAllowedPeers = [...peers];
  const container = $("cfg-allowed-peers-list");
  container.innerHTML = "";
  currentAllowedPeers.forEach((peer, i) => {
    const row = document.createElement("div");
    row.className = "peer-row";
    row.innerHTML =
      '<input type="text" class="peer-input" value="' + escapeHtml(peer) + '">' +
      '<button type="button" class="peer-remove">✕</button>';
    row.querySelector(".peer-remove").addEventListener("click", () => {
      renderAllowedPeers(readAllowedPeersFromDom().filter((_, idx) => idx !== i));
    });
    container.appendChild(row);
  });
}

function readAllowedPeersFromDom() {
  return Array.from($("cfg-allowed-peers-list").querySelectorAll(".peer-input"))
    .map((input) => input.value.trim())
    .filter((v) => v.length > 0);
}

async function loadMidiSourceOptions(selectedValue) {
  const select = $("cfg-midi-source");
  let devices = [];
  try {
    const result = await fetchJson("/api/midi/devices");
    devices = result.devices || [];
  } catch (e) {
    // rtp is always offered regardless of whether device enumeration works
  }
  select.innerHTML = "";
  const rtpOption = document.createElement("option");
  rtpOption.value = "rtp";
  rtpOption.textContent = "RTP-MIDI (Netzwerk)";
  select.appendChild(rtpOption);
  devices.forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    select.appendChild(opt);
  });
  const value = selectedValue || "rtp";
  if (value !== "rtp" && !devices.includes(value)) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = value + " (nicht verfügbar)";
    select.appendChild(opt);
  }
  select.value = value;
  $("cfg-rtp-settings").hidden = value !== "rtp";
}

// Shared by loadConfig (fetched from the running bridge) and importConfig (read from a file
// picked by the user) - either way, populates the form only. Nothing is written to disk until
// the user reviews it and clicks "Speichern", same as any other form edit.
async function applyConfigToForm(config) {
  setAutoToggle("cfg-x32-auto", "cfg-x32-ip-row", "cfg-x32-ip", config.x32_ip);
  $("cfg-x32-port").value = config.x32_port;
  await loadMidiSourceOptions(config.midi_source);
  $("cfg-rtp-session-name").value = config.rtp_session_name;
  $("cfg-rtp-local-port").value = config.rtp_local_port;
  setAutoToggle("cfg-rtp-host-auto", "cfg-rtp-host-ip-row", "cfg-rtp-host-ip", config.rtp_host_ip);
  $("cfg-web-host").value = config.web_host;
  $("cfg-web-port").value = config.web_port;
  $("cfg-double-send").checked = !!config.double_send;
  $("cfg-log-level").value = config.log_level || "INFO";
  $("cfg-undo-timeout").value = config.undo_timeout_ms;
  $("cfg-verify-delay").value = config.verify_delay_ms;
  $("cfg-discovery-interval").value = config.discovery_interval_s;
  renderAllowedPeers(config.allowed_peers || []);
}

async function loadConfig() {
  const config = await fetchJson("/api/config");
  await applyConfigToForm(config);
}

async function importConfig(file) {
  const msg = $("config-message");
  let config;
  try {
    config = JSON.parse(await file.text());
  } catch (e) {
    showMessage(msg, "Datei ist kein gültiges JSON.", true);
    return;
  }
  if (typeof config !== "object" || config === null || Array.isArray(config)) {
    showMessage(msg, "Datei muss ein JSON-Objekt sein.", true);
    return;
  }
  await applyConfigToForm(config);
  showMessage(msg, 'Konfiguration aus Datei geladen - bitte prüfen und "Speichern" klicken, um sie zu übernehmen.', false);
}

async function saveConfig() {
  const msg = $("config-message");
  const config = {
    x32_ip: readAutoToggle("cfg-x32-auto", "cfg-x32-ip"),
    x32_port: parseInt($("cfg-x32-port").value, 10),
    midi_source: $("cfg-midi-source").value,
    rtp_session_name: $("cfg-rtp-session-name").value.trim(),
    rtp_local_port: parseInt($("cfg-rtp-local-port").value, 10),
    rtp_host_ip: readAutoToggle("cfg-rtp-host-auto", "cfg-rtp-host-ip"),
    web_host: $("cfg-web-host").value.trim(),
    web_port: parseInt($("cfg-web-port").value, 10),
    double_send: $("cfg-double-send").checked,
    log_level: $("cfg-log-level").value,
    undo_timeout_ms: parseInt($("cfg-undo-timeout").value, 10),
    verify_delay_ms: parseInt($("cfg-verify-delay").value, 10),
    discovery_interval_s: Number($("cfg-discovery-interval").value),
    allowed_peers: readAllowedPeersFromDom(),
  };

  for (const [key, value] of Object.entries(config)) {
    if (typeof value === "number" && Number.isNaN(value)) {
      showMessage(msg, 'Feld "' + key + '" ist keine gültige Zahl.', true);
      return;
    }
  }

  try {
    const result = await fetchJson("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
    let text = result.restart_required_for && result.restart_required_for.length
      ? "Gespeichert. Neustart nötig für: " + result.restart_required_for.join(", ")
      : "Gespeichert.";
    if (result.web_enabled_locked) {
      text += " (Hinweis: web_enabled lässt sich nicht über die Web-Oberfläche ändern und wurde unverändert gelassen.)";
    }
    showMessage(msg, text, false);

    const midiKeys = result.midi_input_restart_required_for || [];
    if (midiKeys.length) {
      const proceed = confirm(
        "MIDI-Eingang-Einstellung(en) geändert (" + midiKeys.join(", ") + "). " +
        "Jetzt den MIDI-Eingang neu starten, um sie zu übernehmen? " +
        "Kurze Unterbrechung der MIDI-Verbindung, die Weboberfläche bleibt die ganze Zeit erreichbar."
      );
      if (proceed) {
        await restartMidiInput();
      }
    }
  } catch (e) {
    showMessage(msg, e.message, true);
  }
}

async function restartMidiInput() {
  const msg = $("config-message");
  try {
    const result = await fetchJson("/api/midi-input/restart", { method: "POST" });
    showMessage(msg, "MIDI-Eingang neu gestartet - Status: " + result.midi_input_status, false);
    refreshStatus();
  } catch (e) {
    showMessage(msg, "MIDI-Eingang-Neustart fehlgeschlagen: " + e.message, true);
  }
}

async function scanRtpMidiNetwork() {
  const btn = $("cfg-rtp-scan-btn");
  const resultsEl = $("cfg-rtp-scan-results");
  btn.disabled = true;
  resultsEl.textContent = "Scanne (ein paar Sekunden)...";
  try {
    const result = await fetchJson("/api/midi-input/scan", { method: "POST" });
    const sessions = result.sessions || [];
    if (!sessions.length) {
      resultsEl.textContent = "Keine anderen RTP-MIDI-Sitzungen im Netzwerk gefunden.";
    } else {
      resultsEl.innerHTML = "";
      const list = document.createElement("ul");
      for (const s of sessions) {
        const li = document.createElement("li");
        li.textContent = s.name + " (" + (s.host || "?") + ":" + (s.port || "?") + ")";
        list.appendChild(li);
      }
      resultsEl.appendChild(list);
    }
  } catch (e) {
    resultsEl.textContent = "Scan fehlgeschlagen: " + e.message;
  } finally {
    btn.disabled = false;
  }
}

function initConfigTab() {
  $("cfg-x32-auto").addEventListener("change", () => {
    $("cfg-x32-ip-row").hidden = $("cfg-x32-auto").checked;
  });
  $("cfg-rtp-host-auto").addEventListener("change", () => {
    $("cfg-rtp-host-ip-row").hidden = $("cfg-rtp-host-auto").checked;
  });
  $("cfg-allowed-peers-add").addEventListener("click", () => renderAllowedPeers([...readAllowedPeersFromDom(), ""]));
  $("cfg-midi-source").addEventListener("change", () => {
    $("cfg-rtp-settings").hidden = $("cfg-midi-source").value !== "rtp";
  });
  $("cfg-midi-refresh-devices").addEventListener("click", () => loadMidiSourceOptions($("cfg-midi-source").value));
  $("cfg-rtp-scan-btn").addEventListener("click", scanRtpMidiNetwork);
}

// ---- Note name <-> MIDI number conversion (client-side; mirrors main.py's
// note_name_to_midi_number exactly, plus the reverse direction for display).
// Done in JS on purpose: this form needs instant, no-network feedback while
// typing across many fields at once (conversion + duplicate highlighting),
// and the conversion rule itself is small/stable enough that duplicating it
// here is low-risk. /api/validate-note still exists server-side for anyone
// scripting against the API directly. ----
const NOTE_SEMITONES = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const NOTE_NAMES_BY_SEMITONE = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const NOTE_NAME_RE = /^([A-Ga-g])([#b]?)(-?\d+)$/;

function noteNameToMidiNumber(name) {
  const match = NOTE_NAME_RE.exec(name.trim());
  if (!match) return null;
  const [, letter, accidental, octaveStr] = match;
  let semitone = NOTE_SEMITONES[letter.toUpperCase()];
  if (accidental === "#") semitone += 1;
  else if (accidental === "b") semitone -= 1;
  // Ableton-style convention: C3 = MIDI note 60 (matches main.py).
  const midiNumber = (parseInt(octaveStr, 10) + 2) * 12 + semitone;
  return midiNumber >= 0 && midiNumber <= 127 ? midiNumber : null;
}

function midiNumberToNoteName(number) {
  if (number < 0 || number > 127) return null;
  const semitone = ((number % 12) + 12) % 12;
  const octave = Math.floor(number / 12) - 2;
  return NOTE_NAMES_BY_SEMITONE[semitone] + octave;
}

// Accepts either a note name ("A#3") or a plain MIDI number ("69") and
// returns { number, name } or null if neither parses / out of range.
function resolveNoteInput(raw) {
  const value = (raw || "").toString().trim();
  if (!value) return null;
  if (/^-?\d+$/.test(value)) {
    const n = parseInt(value, 10);
    if (n < 0 || n > 127) return null;
    return { number: n, name: midiNumberToNoteName(n) };
  }
  const n = noteNameToMidiNumber(value);
  if (n === null) return null;
  return { number: n, name: midiNumberToNoteName(n) };
}

// ---- Mappings: list + per-mapping form editor ----
let mappingsData = [];
let editingIndex = null; // index into mappingsData, or null when adding new
let currentActions = [];
// opposite_trigger is stored per-mapping (it's a MIDI trigger, not an action property), but
// edited inline on whichever toggle action row(s) it's relevant to (see renderActionsEditor) -
// stashed here across the openEditor -> renderActionsEditor call so the row(s) can pre-fill it.
let currentOppositeTriggerNumber = null;

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

// Every {type, number} pair currently in use across all mappings' trigger
// and undo_trigger, optionally skipping one specific (mappingIndex, field)
// location so a field doesn't flag itself as a duplicate of itself.
function collectUsedTriggers(excludeIndex, excludeField) {
  const used = [];
  mappingsData.forEach((mapping, index) => {
    if (mapping.trigger && !(index === excludeIndex && excludeField === "trigger")) {
      const resolved = resolveNoteInput(mapping.trigger.number);
      if (resolved) used.push({ type: mapping.trigger.type, number: resolved.number });
    }
    if (mapping.undo_trigger && !(index === excludeIndex && excludeField === "undo_trigger")) {
      const resolved = resolveNoteInput(mapping.undo_trigger.number);
      if (resolved) used.push({ type: mapping.undo_trigger.type, number: resolved.number });
    }
    if (mapping.opposite_trigger && !(index === excludeIndex && excludeField === "opposite_trigger")) {
      const resolved = resolveNoteInput(mapping.opposite_trigger.number);
      if (resolved) used.push({ type: mapping.opposite_trigger.type, number: resolved.number });
    }
  });
  return used;
}

function isDuplicateTrigger(type, number, excludeIndex, excludeField) {
  return collectUsedTriggers(excludeIndex, excludeField).some((t) => t.type === type && t.number === number);
}

function nextAvailableNumber(type, excludeIndex, excludeField) {
  const used = new Set(
    collectUsedTriggers(excludeIndex, excludeField)
      .filter((t) => t.type === type)
      .map((t) => t.number)
  );
  let candidate = used.size ? Math.max(...used) + 1 : 60;
  if (candidate > 127) candidate = 0;
  while (used.has(candidate) && candidate <= 127) candidate++;
  return Math.min(candidate, 127);
}

// Used specifically for the undo-trigger default: "the note right after the
// mapping's own trigger note" (e.g. trigger A3/69 -> undo suggestion A#3/70),
// not "the highest note used anywhere in the file" - matches the shipped
// example convention and is what people actually expect for an undo note.
function nextAvailableNumberAfter(afterNumber, type, excludeIndex, excludeField) {
  const used = new Set(
    collectUsedTriggers(excludeIndex, excludeField)
      .filter((t) => t.type === type)
      .map((t) => t.number)
  );
  let candidate = afterNumber + 1;
  if (candidate > 127) candidate = 0;
  while (used.has(candidate) && candidate <= 127) candidate++;
  return Math.min(candidate, 127);
}

function describeTrigger(trigger) {
  if (!trigger) return "-";
  const resolved = resolveNoteInput(trigger.number);
  const label = resolved ? `${resolved.number} (${resolved.name})` : trigger.number;
  return `${trigger.type} ${label}`;
}

// set_channel/add_channel/set_channel_class/set_send_bus are fixed, predefined
// mapping slots: always present in the list, not deletable, and not something a
// user can create another instance of - there is exactly one of each, and
// its action never changes. If you don't need one, point its note at
// something you never play; the slot itself always stays.
function isFixedMapping(mapping) {
  return !!(
    mapping &&
    (mapping.action === "set_channel" ||
      mapping.action === "add_channel" ||
      mapping.action === "set_channel_class" ||
      mapping.action === "set_send_bus")
  );
}

async function loadMappingsList() {
  mappingsData = await fetchJson("/api/mappings");
  await ensureFixedMappings();
  renderMappingsList();
}

// Unlike importConfig (stages into the form, "Speichern" commits it), a mappings file has no
// equivalent single-form staging area - it's replacing the whole list at once, so this asks for
// confirmation up front (same pattern as deleteMapping's confirm()) and then persists straight
// away through the existing, already-validated PUT /api/mappings path.
async function importMappings(file) {
  const msg = $("mappings-message");
  let parsed;
  try {
    parsed = JSON.parse(await file.text());
  } catch (e) {
    showMessage(msg, "Datei ist kein gültiges JSON.", true);
    return;
  }
  if (!Array.isArray(parsed)) {
    showMessage(msg, "Datei muss ein JSON-Array von Mappings sein.", true);
    return;
  }
  if (!confirm("Alle aktuellen Mappings (" + mappingsData.length + ") durch die " + parsed.length + " aus der Datei ersetzen?")) {
    return;
  }
  const previous = mappingsData;
  mappingsData = parsed;
  const ok = await persistMappings(msg, "Mappings importiert.");
  if (!ok) {
    mappingsData = previous;
    return;
  }
  await ensureFixedMappings();
  renderMappingsList();
}

async function ensureFixedMappings() {
  const hasSetChannel = mappingsData.some((m) => m.action === "set_channel");
  const hasAddChannel = mappingsData.some((m) => m.action === "add_channel");
  const hasSetClass = mappingsData.some((m) => m.action === "set_channel_class");
  const hasSetSendBus = mappingsData.some((m) => m.action === "set_send_bus");
  if (hasSetChannel && hasAddChannel && hasSetClass && hasSetSendBus) return;

  if (!hasSetChannel) {
    mappingsData.unshift({
      name: "global_set_channel",
      trigger: { type: "note_on", number: nextAvailableNumber("note_on", null, null) },
      action: "set_channel",
    });
  }
  if (!hasAddChannel) {
    mappingsData.push({
      name: "global_add_channel",
      trigger: { type: "note_on", number: nextAvailableNumber("note_on", null, null) },
      action: "add_channel",
    });
  }
  if (!hasSetClass) {
    mappingsData.push({
      name: "global_set_channel_class",
      trigger: { type: "note_on", number: nextAvailableNumber("note_on", null, null) },
      action: "set_channel_class",
    });
  }
  if (!hasSetSendBus) {
    mappingsData.push({
      name: "global_set_send_bus",
      trigger: { type: "note_on", number: nextAvailableNumber("note_on", null, null) },
      action: "set_send_bus",
    });
  }
  // Silent housekeeping: this runs automatically on every page load, not from a user action, so
  // a persistent "Feste Kanal-Mappings ergänzt." success banner just sat there with no context
  // for what it referred to. Still needs to persist the newly-added slot(s), just without the
  // user-facing message (showMessage no-ops on an empty string).
  await persistMappings($("mappings-message"), "");
}

// Fixed/global mappings (set_channel/add_channel/set_channel_class) always
// render grouped at the top, in this order, regardless of where they
// actually sit in mappingsData/the JSON file - ensureFixedMappings() adds a
// missing one whereever is easiest (unshift/push), so array position alone
// can't be relied on to keep them together.
const _FIXED_MAPPING_ORDER = ["set_channel", "add_channel", "set_channel_class", "set_send_bus"];

function renderMappingsList() {
  const list = $("mappings-list");
  list.innerHTML = "";
  const ordered = mappingsData
    .map((mapping, index) => ({ mapping, index }))
    .sort((a, b) => {
      const aFixed = isFixedMapping(a.mapping);
      const bFixed = isFixedMapping(b.mapping);
      if (aFixed && bFixed) {
        return _FIXED_MAPPING_ORDER.indexOf(a.mapping.action) - _FIXED_MAPPING_ORDER.indexOf(b.mapping.action);
      }
      if (aFixed !== bFixed) return aFixed ? -1 : 1;
      return 0; // stable sort: preserve existing relative order otherwise
    });
  ordered.forEach(({ mapping, index }) => {
    const li = document.createElement("li");
    li.className = "mapping-item";
    li.dataset.name = mapping.name || "";
    const fixed = isFixedMapping(mapping);
    let kind = "OSC-Aktion";
    if (fixed) {
      if (mapping.action === "set_channel") kind = "Kanal setzen (fest)";
      else if (mapping.action === "add_channel") kind = "Kanal hinzufügen (fest)";
      else if (mapping.action === "set_channel_class") kind = "Klasse wählen (fest)";
      else kind = "Send-Bus wählen (fest)";
    }
    const undoLine = mapping.undo_trigger
      ? '<span class="mapping-trigger-undo">Undo: ' + escapeHtml(describeTrigger(mapping.undo_trigger)) + "</span>"
      : "";
    const oppositeLine = mapping.opposite_trigger
      ? '<span class="mapping-trigger-undo">Gegenteil: ' + escapeHtml(describeTrigger(mapping.opposite_trigger)) + "</span>"
      : "";
    li.innerHTML =
      '<span class="mapping-name">' + escapeHtml(mapping.name || "(ohne Namen)") + "</span>" +
      '<span class="mapping-kind' + (fixed ? " mapping-kind-fixed" : "") + '">' + kind + "</span>" +
      '<span class="mapping-trigger-group">' +
        '<span class="mapping-trigger">' + escapeHtml(describeTrigger(mapping.trigger)) + "</span>" +
        undoLine +
        oppositeLine +
      "</span>" +
      '<button type="button" class="mapping-edit-btn" data-index="' + index + '">Bearbeiten</button>';
    list.appendChild(li);
  });
  list.querySelectorAll(".mapping-edit-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = btn.closest(".mapping-item");
      highlightEditingRow(row);
      openEditor(parseInt(btn.dataset.index, 10), row);
    });
  });
}

// The editor lives in a <li> (#mapping-editor-slot) normally parked, hidden, in
// #mapping-editor-holder - moving it to sit right after the row being edited (or to the end of
// the list for a brand-new mapping) is what makes it expand inline/"accordion-style" at that
// row's position instead of appearing in a fixed spot elsewhere on the page.
function moveEditorSlotTo(afterRow) {
  const slot = $("mapping-editor-slot");
  const list = $("mappings-list");
  if (afterRow && afterRow.parentElement === list) {
    list.insertBefore(slot, afterRow.nextSibling);
  } else {
    list.appendChild(slot);
  }
}

// Kept in addition to the accordion placement above: with the editor now expanding right at the
// row's own position, the highlight visually ties an inline-expanded panel back to "this is the
// row it belongs to" the same way an accordion's active-item styling would.
function highlightEditingRow(row) {
  document.querySelectorAll(".mapping-item-editing").forEach((el) => el.classList.remove("mapping-item-editing"));
  if (row) row.classList.add("mapping-item-editing");
}

function updateUndoVisibility() {
  $("m-undo-fields").hidden = !$("m-save-state").checked;
}

function applyNoteFieldDisplay(inputEl, spanEl, resolved, isDup) {
  if (!resolved) {
    spanEl.textContent = inputEl.value ? "ungültig" : "";
    spanEl.className = "note-resolved" + (inputEl.value ? " field-error" : "");
    inputEl.classList.toggle("field-error", !!inputEl.value);
    return;
  }
  spanEl.textContent = resolved.number + " (" + resolved.name + ")" + (isDup ? " – bereits verwendet!" : "");
  spanEl.className = "note-resolved" + (isDup ? " field-error" : "");
  inputEl.classList.toggle("field-error", isDup);
}

// Channel-kind mappings only have one note field, no sibling to compare against.
function refreshChannelTriggerField() {
  const inputEl = $("m-trigger-number");
  const resolved = resolveNoteInput(inputEl.value);
  const dup = resolved ? isDuplicateTrigger("note_on", resolved.number, editingIndex, "trigger") : false;
  applyNoteFieldDisplay(inputEl, $("m-trigger-resolved"), resolved, dup);
}

// OSC-kind mappings have a trigger, an (optional) undo-trigger, and any number of toggle
// actions' (optional) opposite-note fields - all belong to the same mapping and must be
// checked against each other, not just against saved mappingsData, so "I just typed the same
// note into two of these fields before saving" is caught too (their current, possibly-unsaved
// values count as "used" here).
function refreshOscTriggerFields() {
  const triggerType = $("m-trigger-type").value;
  const triggerInput = $("m-osc-trigger-number");
  const undoInput = $("m-undo-number");
  const undoActive = $("m-save-state").checked;

  const triggerResolved = resolveNoteInput(triggerInput.value);
  const undoResolved = undoActive ? resolveNoteInput(undoInput.value) : null;

  const oppositeInputs = Array.from($("m-actions-list").querySelectorAll(".action-opposite-number")).filter(
    (input) => !input.hidden
  );
  const oppositeResolvedList = oppositeInputs.map((input) => (input.value.trim() ? resolveNoteInput(input.value) : null));
  const anyOppositeResolved = oppositeResolvedList.find((r) => r) || null;

  const pairConflict = (a, b) => !!(a && b && a.number === b.number);
  const siblingConflict =
    pairConflict(triggerResolved, undoResolved) ||
    pairConflict(triggerResolved, anyOppositeResolved) ||
    pairConflict(undoResolved, anyOppositeResolved);

  const triggerDup =
    siblingConflict || (!!triggerResolved && isDuplicateTrigger(triggerType, triggerResolved.number, editingIndex, "trigger"));
  applyNoteFieldDisplay(triggerInput, $("m-osc-trigger-resolved"), triggerResolved, triggerDup);

  if (undoActive) {
    const undoDup =
      siblingConflict || (!!undoResolved && isDuplicateTrigger(triggerType, undoResolved.number, editingIndex, "undo_trigger"));
    applyNoteFieldDisplay(undoInput, $("m-undo-resolved"), undoResolved, undoDup);
  }

  oppositeInputs.forEach((input, i) => {
    const span = input.nextElementSibling;
    const resolved = oppositeResolvedList[i];
    if (input.value.trim()) {
      const dup =
        siblingConflict || (!!resolved && isDuplicateTrigger(triggerType, resolved.number, editingIndex, "opposite_trigger"));
      applyNoteFieldDisplay(input, span, resolved, dup);
    } else {
      span.textContent = "";
      span.className = "note-resolved";
      input.classList.remove("field-error");
    }
    span.classList.add("action-opposite-resolved");
  });
}

// Picks the opposite_trigger value to persist for the whole mapping out of however many toggle
// action rows currently have the field populated (usually 0 or 1 - a mapping with more than one
// toggle action is an edge case, and they all share a single mapping-level opposite_trigger
// anyway, so the first populated one wins).
function collectOppositeTriggerNumberFromActions() {
  const inputs = $("m-actions-list").querySelectorAll(".action-opposite-number");
  for (const input of inputs) {
    if (!input.hidden && input.value.trim()) return input.value.trim();
  }
  return "";
}

function renderActionsEditor(actions) {
  currentActions = actions.map((a) => ({ ...a }));
  const container = $("m-actions-list");
  container.innerHTML = "";
  const oppositeHint = oppositeNoteHint();
  const oppositeValue = currentOppositeTriggerNumber != null ? String(currentOppositeTriggerNumber) : "";
  currentActions.forEach((action, i) => {
    const mode =
      action.value === "midi_value" ? "midi_value" :
      action.value === "toggle" ? "toggle" :
      action.value === "relative_db" ? "relative_db" : "fixed";
    // relative_db has its own nested "where does the dB amount come from" choice - a fixed
    // number (same amount every trigger) or "midi_value" (velocity-proportional, see db_scale).
    const dbDeltaMode = action.db_delta === "midi_value" ? "midi_value" : "fixed";
    const row = document.createElement("div");
    row.className = "action-row";
    row.innerHTML =
      '<input type="text" class="action-path" placeholder="/ch/{active_channels}/mix/pan" value="' + escapeHtml(action.path || "") + '">' +
      '<select class="action-value-mode">' +
        '<option value="fixed">Fester Wert</option>' +
        '<option value="midi_value">Velocity (dynamisch)</option>' +
        '<option value="toggle">Toggle (An/Aus umschalten)</option>' +
        '<option value="relative_db">Relativ (dB-Offset)</option>' +
      "</select>" +
      '<input type="number" class="action-fixed-value" step="any" value="' + (mode === "fixed" ? (action.value ?? 1) : 1) + '" ' + (mode === "fixed" ? "" : "hidden") + ">" +
      '<select class="action-scale" ' + (mode === "midi_value" ? "" : "hidden") + ">" +
        '<option value="">(keine Skalierung)</option>' +
        '<option value="midi_to_pan">midi_to_pan</option>' +
        '<option value="midi_to_fader">midi_to_fader</option>' +
        '<option value="invert">invert</option>' +
      "</select>" +
      '<input type="number" class="action-toggle-on" step="any" placeholder="An-Wert" title="An-Wert" value="' + (action.toggle_on_value ?? 1) + '" ' + (mode === "toggle" ? "" : "hidden") + ">" +
      '<input type="number" class="action-toggle-off" step="any" placeholder="Aus-Wert" title="Aus-Wert" value="' + (action.toggle_off_value ?? 0) + '" ' + (mode === "toggle" ? "" : "hidden") + ">" +
      '<input type="text" class="action-opposite-number" placeholder="Gegenteil-Note (optional)" title="' + escapeHtml(oppositeHint) + '" value="' + escapeHtml(oppositeValue) + '" ' + (mode === "toggle" ? "" : "hidden") + ">" +
      '<span class="action-opposite-resolved note-resolved" ' + (mode === "toggle" ? "" : "hidden") + "></span>" +
      '<select class="action-db-delta-mode" title="Woher kommt der dB-Betrag" ' + (mode === "relative_db" ? "" : "hidden") + ">" +
        '<option value="fixed">Fest</option>' +
        '<option value="midi_value">Nach Velocity</option>' +
      "</select>" +
      '<input type="number" class="action-db-delta-fixed" step="any" placeholder="+10 oder -10 (dB)" title="dB-Änderung pro Trigger" value="' + (typeof action.db_delta === "number" ? action.db_delta : 10) + '" ' + (mode === "relative_db" && dbDeltaMode === "fixed" ? "" : "hidden") + ">" +
      '<input type="number" class="action-db-max-velocity" step="1" min="1" max="127" placeholder="Max. Velocity" title="Velocity, ab der der volle dB-Betrag erreicht ist" value="' + (action.db_scale?.max_velocity ?? 127) + '" ' + (mode === "relative_db" && dbDeltaMode === "midi_value" ? "" : "hidden") + ">" +
      '<input type="number" class="action-db-max-db" step="any" placeholder="dB bei Max. Velocity" title="dB-Änderung bei maximaler Velocity (negativ = leiser)" value="' + (action.db_scale?.max_db ?? 10) + '" ' + (mode === "relative_db" && dbDeltaMode === "midi_value" ? "" : "hidden") + ">" +
      '<button type="button" class="action-remove">✕</button>';
    row.querySelector(".action-value-mode").value = mode;
    row.querySelector(".action-scale").value = action.scale || "";
    row.querySelector(".action-db-delta-mode").value = dbDeltaMode;
    const updateDbDeltaFieldVisibility = () => {
      const valueMode = row.querySelector(".action-value-mode").value;
      const deltaMode = row.querySelector(".action-db-delta-mode").value;
      row.querySelector(".action-db-delta-mode").hidden = valueMode !== "relative_db";
      row.querySelector(".action-db-delta-fixed").hidden = !(valueMode === "relative_db" && deltaMode === "fixed");
      row.querySelector(".action-db-max-velocity").hidden = !(valueMode === "relative_db" && deltaMode === "midi_value");
      row.querySelector(".action-db-max-db").hidden = !(valueMode === "relative_db" && deltaMode === "midi_value");
    };
    row.querySelector(".action-value-mode").addEventListener("change", (e) => {
      const newMode = e.target.value;
      row.querySelector(".action-fixed-value").hidden = newMode !== "fixed";
      row.querySelector(".action-scale").hidden = newMode !== "midi_value";
      row.querySelector(".action-toggle-on").hidden = newMode !== "toggle";
      row.querySelector(".action-toggle-off").hidden = newMode !== "toggle";
      row.querySelector(".action-opposite-number").hidden = newMode !== "toggle";
      row.querySelector(".action-opposite-resolved").hidden = newMode !== "toggle";
      updateDbDeltaFieldVisibility();
      refreshOscTriggerFields();
    });
    row.querySelector(".action-db-delta-mode").addEventListener("change", updateDbDeltaFieldVisibility);
    row.querySelector(".action-opposite-number").addEventListener("input", refreshOscTriggerFields);
    row.querySelector(".action-remove").addEventListener("click", () => {
      renderActionsEditor(readActionsFromDom().filter((_, idx) => idx !== i));
    });
    container.appendChild(row);
  });
  refreshOscTriggerFields();
}

function readActionsFromDom() {
  const rows = $("m-actions-list").querySelectorAll(".action-row");
  const actions = [];
  rows.forEach((row) => {
    const path = row.querySelector(".action-path").value.trim();
    const mode = row.querySelector(".action-value-mode").value;
    const scale = row.querySelector(".action-scale").value;
    const action = { path };
    if (mode === "midi_value") {
      action.value = "midi_value";
      if (scale) action.scale = scale;
    } else if (mode === "toggle") {
      action.value = "toggle";
      const onRaw = row.querySelector(".action-toggle-on").value;
      const offRaw = row.querySelector(".action-toggle-off").value;
      action.toggle_on_value = onRaw === "" ? 1 : Number(onRaw);
      action.toggle_off_value = offRaw === "" ? 0 : Number(offRaw);
    } else if (mode === "relative_db") {
      action.value = "relative_db";
      const deltaMode = row.querySelector(".action-db-delta-mode").value;
      if (deltaMode === "midi_value") {
        action.db_delta = "midi_value";
        const maxVelocityRaw = row.querySelector(".action-db-max-velocity").value;
        const maxDbRaw = row.querySelector(".action-db-max-db").value;
        action.db_scale = {
          max_velocity: maxVelocityRaw === "" ? 127 : Number(maxVelocityRaw),
          max_db: maxDbRaw === "" ? 10 : Number(maxDbRaw),
        };
      } else {
        const fixedRaw = row.querySelector(".action-db-delta-fixed").value;
        action.db_delta = fixedRaw === "" ? 10 : Number(fixedRaw);
      }
    } else {
      const fixedRaw = row.querySelector(".action-fixed-value").value;
      action.value = fixedRaw === "" ? 1 : Number(fixedRaw);
    }
    actions.push(action);
  });
  return actions;
}

function openEditor(index, anchorRow) {
  editingIndex = index;
  const mapping = index === null ? null : mappingsData[index];
  const fixed = isFixedMapping(mapping);

  moveEditorSlotTo(anchorRow || null);
  $("mapping-editor-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
  $("mapping-editor-title").textContent = mapping ? "Mapping bearbeiten: " + mapping.name : "Neues Mapping";
  $("mapping-editor-message").textContent = "";
  $("mapping-delete").hidden = index === null || fixed;
  $("m-name").value = mapping ? mapping.name || "" : "neues_mapping";

  $("m-channel-fields").hidden = !fixed;
  $("m-osc-fields").hidden = fixed;

  if (fixed) {
    if (mapping.action === "set_channel") {
      $("m-channel-label").textContent =
        "Kanal setzen (set_channel): löscht die aktive Auswahl der aktuellen Klasse und wählt exklusiv den über die Velocity übergebenen Kanal.";
    } else if (mapping.action === "add_channel") {
      $("m-channel-label").textContent =
        "Kanal hinzufügen (add_channel): ergänzt den über die Velocity übergebenen Kanal zur aktiven Auswahl der aktuellen Klasse.";
    } else if (mapping.action === "set_channel_class") {
      $("m-channel-label").textContent =
        "Klasse wählen (set_channel_class): legt fest, auf welche Sektion sich set_channel/add_channel als Nächstes beziehen - " +
        "Velocity 1 = Kanäle, 2 = Busse, 3 = Aux In, 4 = FX Return, 5 = Matrix, 6 = DCA. " +
        "Für Sends EINES Kanals auf einen Mixbus (z. B. Channel 2 auf Bus 10 muten) NICHT hierüber lösen - dafür gibt es die " +
        "separate Aktion 'Send-Bus wählen' (set_send_bus) weiter unten in der Mapping-Liste, plus den Pfad-Platzhalter " +
        "{active_send_bus} in der Aktion selbst, z. B. /ch/{active_channels}/mix/{active_send_bus}/on.";
    } else {
      $("m-channel-label").textContent =
        "Send-Bus wählen (set_send_bus): legt fest, auf welchen Mixbus sich der Platzhalter {active_send_bus} in Mapping-Aktionen " +
        "bezieht - Velocity 1-16 = Bus 1-16 (Werte darüber/darunter werden geklemmt). Unabhängig von Klasse/Kanalauswahl: " +
        "z. B. 'Channel 2 auf Bus 10 muten' = zuerst set_send_bus mit Velocity 10, dann set_channel mit Velocity 2, dann ein " +
        "Mapping mit Pfad /ch/{active_channels}/mix/{active_send_bus}/on.";
    }
    $("m-trigger-number").value = mapping.trigger.number;
  } else {
    const triggerType = mapping ? mapping.trigger.type : "note_on";
    const triggerNumber = mapping ? mapping.trigger.number : nextAvailableNumber("note_on", index, "trigger");
    $("m-trigger-type").value = triggerType;
    $("m-osc-trigger-number").value = triggerNumber;
    $("m-save-state").checked = mapping ? !!mapping.save_state : false;

    const undo = mapping ? mapping.undo_trigger : null;
    if (undo) {
      $("m-undo-number").value = undo.number;
    } else {
      $("m-undo-number").value = nextAvailableNumberAfter(Number(triggerNumber), triggerType, index, "undo_trigger");
    }

    currentOppositeTriggerNumber = mapping && mapping.opposite_trigger ? mapping.opposite_trigger.number : null;
    renderActionsEditor(mapping ? mapping.actions || [] : [{ path: "", value: "midi_value" }]);
  }

  updateUndoVisibility();
  updateUndoTypeHint();
  refreshChannelTriggerField();
  refreshOscTriggerFields();
}

function updateUndoTypeHint() {
  const hint = $("m-undo-type-hint");
  if (hint) hint.textContent = $("m-trigger-type").value;
}

// Tooltip for a toggle action's opposite-note field (see renderActionsEditor) - includes the
// same "next free note" suggestion nextAvailableNumberAfter gives undo_trigger, just as a title
// rather than a pre-filled value: the field must stay empty by default, since empty is what
// keeps a toggle action query-based/single-note.
function oppositeNoteHint() {
  const triggerType = $("m-trigger-type").value;
  const triggerResolved = resolveNoteInput($("m-osc-trigger-number").value);
  const base = triggerResolved ? triggerResolved.number : 59;
  const suggestion = nextAvailableNumberAfter(base, triggerType, editingIndex, "opposite_trigger");
  return (
    "Optional: zweite Note, die garantiert toggle_off_value sendet (Haupt-Note oben sendet dann garantiert " +
    "toggle_on_value) - ohne Pult-Abfrage. Leer lassen = echter Toggle mit einer Note (fragt den Pultzustand ab). " +
    `Vorschlag für eine freie Note: ${suggestion} (${midiNumberToNoteName(suggestion)}).`
  );
}

function closeEditor() {
  editingIndex = null;
  $("mapping-editor-holder").appendChild($("mapping-editor-slot"));
  highlightEditingRow(null);
}

async function persistMappings(msgEl, successText) {
  try {
    await fetchJson("/api/mappings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(mappingsData),
    });
    showMessage(msgEl, successText, false);
    return true;
  } catch (e) {
    showMessage(msgEl, e.message, true);
    return false;
  }
}

async function saveMapping() {
  const msg = $("mapping-editor-message");
  const originalMapping = editingIndex !== null ? mappingsData[editingIndex] : null;
  const fixed = isFixedMapping(originalMapping);
  const name = $("m-name").value.trim();
  if (!name) {
    showMessage(msg, "Name darf nicht leer sein.", true);
    return;
  }

  const mapping = { name };

  if (fixed) {
    const resolved = resolveNoteInput($("m-trigger-number").value);
    if (!resolved) {
      showMessage(msg, "Ungültige Note/Nummer.", true);
      return;
    }
    if (isDuplicateTrigger("note_on", resolved.number, editingIndex, "trigger")) {
      showMessage(msg, "Diese Note wird bereits von einem anderen Mapping verwendet.", true);
      return;
    }
    mapping.trigger = { type: "note_on", number: resolved.number };
    mapping.action = originalMapping.action;
  } else {
    const triggerType = $("m-trigger-type").value;
    const resolved = resolveNoteInput($("m-osc-trigger-number").value);
    if (!resolved) {
      showMessage(msg, "Ungültige Note/Nummer für den Trigger.", true);
      return;
    }
    if (isDuplicateTrigger(triggerType, resolved.number, editingIndex, "trigger")) {
      showMessage(msg, "Dieser Trigger wird bereits von einem anderen Mapping verwendet.", true);
      return;
    }
    mapping.trigger = { type: triggerType, number: resolved.number };
    mapping.save_state = $("m-save-state").checked;
    mapping.actions = readActionsFromDom();
    if (!mapping.actions.length || !mapping.actions[0].path) {
      showMessage(msg, "Mindestens eine Aktion mit OSC-Pfad ist erforderlich.", true);
      return;
    }
    if (mapping.save_state) {
      // Undo trigger always shares the main trigger's type - see updateUndoTypeHint().
      const undoResolved = resolveNoteInput($("m-undo-number").value);
      if (!undoResolved) {
        showMessage(msg, "Ungültige Undo-Note/Nummer.", true);
        return;
      }
      if (isDuplicateTrigger(triggerType, undoResolved.number, editingIndex, "undo_trigger")) {
        showMessage(msg, "Dieser Undo-Trigger wird bereits von einem anderen Mapping verwendet.", true);
        return;
      }
      mapping.undo_trigger = { type: triggerType, number: undoResolved.number };
    }

    const oppositeRaw = collectOppositeTriggerNumberFromActions();
    if (oppositeRaw) {
      const oppositeResolved = resolveNoteInput(oppositeRaw);
      if (!oppositeResolved) {
        showMessage(msg, "Ungültige Gegenteil-Note/Nummer.", true);
        return;
      }
      if (
        oppositeResolved.number === resolved.number ||
        (mapping.undo_trigger && oppositeResolved.number === mapping.undo_trigger.number) ||
        isDuplicateTrigger(triggerType, oppositeResolved.number, editingIndex, "opposite_trigger")
      ) {
        showMessage(msg, "Diese Gegenteil-Note wird bereits von einem anderen Feld oder Mapping verwendet.", true);
        return;
      }
      mapping.opposite_trigger = { type: triggerType, number: oppositeResolved.number };
    }
  }

  if (editingIndex === null) {
    mappingsData.push(mapping);
  } else {
    mappingsData[editingIndex] = mapping;
  }

  if (await persistMappings(msg, "Gespeichert.")) {
    // closeEditor() first: it moves #mapping-editor-slot back out of #mappings-list, which
    // renderMappingsList()'s list.innerHTML = "" would otherwise destroy (the slot is currently
    // a child of the list while the editor is open - see openEditor/moveEditorSlotTo).
    closeEditor();
    renderMappingsList();
  }
}

async function deleteMapping() {
  if (editingIndex === null) return;
  if (isFixedMapping(mappingsData[editingIndex])) return; // fixed slots are never deletable
  if (!confirm("Dieses Mapping wirklich löschen?")) return;
  mappingsData.splice(editingIndex, 1);
  if (await persistMappings($("mapping-editor-message"), "Gelöscht.")) {
    closeEditor(); // see saveMapping() - must happen before renderMappingsList()
    renderMappingsList();
  }
}

function initMappingsTab() {
  $("mapping-add").addEventListener("click", () => {
    highlightEditingRow(null);
    openEditor(null);
  });
  $("mappings-export").addEventListener("click", () => { window.location.href = "/api/mappings/export"; });
  $("mappings-import-btn").addEventListener("click", () => $("mappings-import-file").click());
  $("mappings-import-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (file) importMappings(file);
  });
  $("mapping-cancel").addEventListener("click", closeEditor);
  $("mapping-save").addEventListener("click", saveMapping);
  $("mapping-delete").addEventListener("click", deleteMapping);
  $("m-action-add").addEventListener("click", () => renderActionsEditor([...readActionsFromDom(), { path: "", value: "midi_value" }]));

  $("m-save-state").addEventListener("change", () => {
    updateUndoVisibility();
    if ($("m-save-state").checked && !$("m-undo-number").value) {
      const triggerType = $("m-trigger-type").value;
      const triggerResolved = resolveNoteInput($("m-osc-trigger-number").value);
      const base = triggerResolved ? triggerResolved.number : 59;
      $("m-undo-number").value = nextAvailableNumberAfter(base, triggerType, editingIndex, "undo_trigger");
    }
    refreshOscTriggerFields();
  });

  $("m-trigger-number").addEventListener("input", refreshChannelTriggerField);
  $("m-osc-trigger-number").addEventListener("input", refreshOscTriggerFields);
  $("m-trigger-type").addEventListener("change", () => {
    updateUndoTypeHint();
    refreshOscTriggerFields();
  });
  $("m-undo-number").addEventListener("input", refreshOscTriggerFields);
}

// ---- Test panel ----
async function sendTestMidi() {
  const msg = $("test-message");
  try {
    const result = await fetchJson("/api/test/midi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type: $("test-type").value,
        number: $("test-number").value,
        velocity: parseInt($("test-velocity").value || "0", 10),
      }),
    });
    showMessage(msg, "Gesendet (aufgelöste Nummer: " + result.resolved_number + ")", false);
  } catch (e) {
    showMessage(msg, e.message, true);
  }
}

async function queryOsc() {
  const msg = $("osc-message");
  try {
    const result = await fetchJson("/api/test/osc-query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: $("osc-path").value }),
    });
    if (result.value === null) {
      showMessage(msg, result.note || "Keine Antwort", true);
    } else {
      showMessage(msg, result.path + " = " + JSON.stringify(result.value), false);
    }
  } catch (e) {
    showMessage(msg, e.message, true);
  }
}

// ---- Logs ----
const MAX_LOG_LINES = 1000;

async function initLogs() {
  const view = $("log-view");
  try {
    const initial = await fetchJson("/api/logs?tail=200");
    view.textContent = initial.lines.join("\n") + (initial.lines.length ? "\n" : "");
  } catch (e) {
    view.textContent = "(Logs konnten nicht geladen werden: " + e.message + ")\n";
  }
  view.scrollTop = view.scrollHeight;

  const source = new EventSource("/api/logs/stream");
  source.onmessage = (event) => {
    view.textContent += event.data + "\n";
    const lines = view.textContent.split("\n");
    if (lines.length > MAX_LOG_LINES) {
      view.textContent = lines.slice(lines.length - MAX_LOG_LINES).join("\n");
    }
    view.scrollTop = view.scrollHeight;
  };
}

// ---- Mapping activity flash ----
// Briefly highlights a mapping's row in the list when it actually fires -
// a lightweight debugging aid. Cost-wise this is the same mechanism as the
// log stream above (one persistent SSE connection, tiny JSON payloads only
// when a mapping fires), so it doesn't add meaningful overhead.
function initMappingEvents() {
  const source = new EventSource("/api/mappings/events");
  source.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    const li = $("mappings-list").querySelector('[data-name="' + CSS.escape(data.name) + '"]');
    if (!li) return;
    const flashClass = data.kind === "undo" ? "mapping-flash-undo" : "mapping-flash-trigger";
    li.classList.remove("mapping-flash-undo", "mapping-flash-trigger");
    void li.offsetWidth; // restart the CSS transition if it fires again quickly
    li.classList.add(flashClass);
    setTimeout(() => li.classList.remove(flashClass), 900);
  };
}

// ---- Init ----
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initMappingsTab();
  initConfigTab();

  $("config-reload").addEventListener("click", loadConfig);
  $("config-save").addEventListener("click", saveConfig);
  $("config-export").addEventListener("click", () => { window.location.href = "/api/config/export"; });
  $("config-import-btn").addEventListener("click", () => $("config-import-file").click());
  $("config-import-file").addEventListener("change", (e) => {
    const file = e.target.files[0];
    e.target.value = ""; // allow re-picking the same file name later
    if (file) importConfig(file);
  });
  $("test-send").addEventListener("click", sendTestMidi);
  $("osc-query").addEventListener("click", queryOsc);

  refreshStatus();
  setInterval(refreshStatus, 2000);
  loadConfig();
  loadMappingsList();
  initLogs();
  initMappingEvents();
});
