import asyncio
import copy
import json
import logging
import socket
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set

from aiohttp import web

logger = logging.getLogger("x32-midi-bridge")

WEB_DIR = Path(__file__).parent / "web"

_RESTART_REQUIRED_KEYS = {
    "web_host",
    "web_port",
    "web_enabled",
    "x32_port",
}
# Changing these no longer needs a full bridge restart - X32MidiBridge.restart_midi_input()
# tears down and rebuilds just the MIDI-input subsystem (RTP-MIDI server + zeroconf
# advertisement, or a local device listener) from the current config. The web UI still flags
# them (see midi_input_restart_required_for below) so the change is visibly not live yet, but
# the fix is a lightweight "MIDI-Eingang neu starten" action, not "restart the whole tool".
_MIDI_INPUT_RESTART_KEYS = {
    "midi_source",
    "rtp_local_port",
    "rtp_host_ip",
    "rtp_session_name",
}
_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
_CONFIG_SCHEMA = {
    "x32_ip": str,
    "x32_port": int,
    "rtp_session_name": str,
    "rtp_host_ip": str,
    "rtp_local_port": int,
    "allowed_peers": list,
    "double_send": bool,
    "undo_timeout_ms": int,
    "verify_delay_ms": int,
    "discovery_interval_s": (int, float),
    "log_level": str,
    "web_enabled": bool,
    "web_host": str,
    "web_port": int,
    "midi_source": str,
}


class _SSELogHandler(logging.Handler):
    """Buffers formatted log records and fans them out to connected
    Server-Sent-Events clients. emit() may be called from any thread (e.g.
    the pymidi server thread), so delivery to subscriber queues is marshalled
    onto the owning asyncio loop via call_soon_threadsafe."""

    def __init__(self, loop: asyncio.AbstractEventLoop, maxlen: int = 500):
        super().__init__()
        self.loop = loop
        self.buffer: Deque[str] = deque(maxlen=maxlen)
        self.subscribers: Set["asyncio.Queue[str]"] = set()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
        except Exception:
            return
        self.buffer.append(line)
        self.loop.call_soon_threadsafe(self._fanout, line)

    def _fanout(self, line: str) -> None:
        for queue in list(self.subscribers):
            queue.put_nowait(line)

    def subscribe(self) -> "asyncio.Queue[str]":
        queue: "asyncio.Queue[str]" = asyncio.Queue(maxsize=1000)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[str]") -> None:
        self.subscribers.discard(queue)


class _MappingEventBroadcaster:
    """Fans out tiny "a mapping just fired" events to connected SSE clients,
    so the web UI can briefly highlight the mapping in its list - purely a
    debugging/feedback aid, no state is kept between events. publish() is
    only ever called from the asyncio loop (handle_midi_event runs there
    directly, unlike the pymidi receive thread), so no thread-safety dance
    is needed here."""

    def __init__(self) -> None:
        self.subscribers: Set["asyncio.Queue[str]"] = set()

    def publish(self, name: str, kind: str) -> None:
        payload = json.dumps({"name": name, "kind": kind})
        for queue in list(self.subscribers):
            queue.put_nowait(payload)

    def subscribe(self) -> "asyncio.Queue[str]":
        queue: "asyncio.Queue[str]" = asyncio.Queue(maxsize=100)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: "asyncio.Queue[str]") -> None:
        self.subscribers.discard(queue)


def _validate_config(config: Dict[str, Any]) -> List[str]:
    errors = []
    for key, expected_type in _CONFIG_SCHEMA.items():
        if key in config and not isinstance(config[key], expected_type):
            errors.append(f"'{key}' must be of type {expected_type}")
    for port_key in ("x32_port", "rtp_local_port", "web_port"):
        value = config.get(port_key)
        if isinstance(value, int) and not (1 <= value <= 65535):
            errors.append(f"'{port_key}' must be between 1 and 65535")
    if "log_level" in config and str(config["log_level"]).upper() not in _VALID_LOG_LEVELS:
        errors.append(f"'log_level' must be one of {sorted(_VALID_LOG_LEVELS)}")
    return errors


def _resolve_trigger_number(number: Any) -> Optional[int]:
    from main import note_name_to_midi_number

    if isinstance(number, str) and not number.lstrip("-").isdigit():
        return note_name_to_midi_number(number)
    try:
        return int(number)
    except (TypeError, ValueError):
        return None


def _validate_mappings(mappings: List[Any]) -> List[str]:
    errors = []
    seen_triggers: Dict[Any, List[str]] = {}

    for i, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            errors.append(f"Mapping #{i}: must be an object")
            continue
        label = mapping.get("name", f"#{i}")
        if not mapping.get("trigger"):
            errors.append(f"Mapping #{i} ('{label}'): missing 'trigger'")
        for trigger_key in ("trigger", "undo_trigger", "opposite_trigger"):
            trigger = mapping.get(trigger_key)
            if not trigger:
                continue
            trigger_type = trigger.get("type")
            if trigger_type not in ("note_on", "note_off", "control_change"):
                errors.append(f"Mapping #{i}: {trigger_key}.type must be note_on/note_off/control_change")
            number = trigger.get("number")
            resolved = _resolve_trigger_number(number)
            if resolved is None:
                errors.append(f"Mapping #{i}: {trigger_key}.number '{number}' is not a valid MIDI number or note name")
                continue
            # Duplicate detection: the same (type, resolved number) used more than
            # once means find_mapping()/find_undo_mapping() would only ever reach
            # the first match - the rest would silently never fire.
            key = (trigger_type, resolved)
            seen_triggers.setdefault(key, []).append(f"{label}.{trigger_key}")

    for (trigger_type, number), locations in seen_triggers.items():
        if len(locations) > 1:
            errors.append(f"Trigger {trigger_type} {number} wird mehrfach verwendet: {', '.join(locations)}")

    return errors


def _sse_pack(line: str) -> bytes:
    # Multi-line payloads (e.g. tracebacks) need one "data:" prefix per line
    # per the SSE spec, otherwise EventSource only delivers the first line.
    payload = "\n".join(f"data: {part}" for part in line.split("\n"))
    return (payload + "\n\n").encode("utf-8")


def _static_file_response(filename: str, content_type: str) -> web.Response:
    # Not web.FileResponse: it guesses Content-Type from the extension via
    # the stdlib mimetypes module with no charset, so browsers (Windows
    # ones especially) fall back to guessing an 8-bit encoding and mangle
    # every non-ASCII character in these UTF-8 files. Serving the bytes
    # ourselves lets us declare charset=utf-8 explicitly.
    text = (WEB_DIR / filename).read_text(encoding="utf-8")
    return web.Response(text=text, content_type=content_type, charset="utf-8")


async def _handle_index(request: web.Request) -> web.Response:
    return _static_file_response("index.html", "text/html")


async def _handle_app_js(request: web.Request) -> web.Response:
    return _static_file_response("app.js", "application/javascript")


async def _handle_style_css(request: web.Request) -> web.Response:
    return _static_file_response("style.css", "text/css")


async def _handle_status(request: web.Request) -> web.Response:
    bridge = request.app["bridge"]
    # Advertised RTP-MIDI (AppleMIDI/zeroconf) identity, if currently running - this is what
    # this bridge announces itself as on the network, so the user can check it against what
    # actually shows up as a discoverable session on the connecting device (e.g. a DAW's
    # "network MIDI" picker). None of these are meaningful when midi_source isn't "rtp", or
    # before advertise_rtp_midi() has run once at startup.
    service_info = getattr(bridge, "service_info", None)
    rtp_advertised_name = service_info.name if service_info else None
    rtp_advertised_host = None
    if service_info and service_info.addresses:
        try:
            rtp_advertised_host = socket.inet_ntoa(service_info.addresses[0])
        except (OSError, TypeError):
            rtp_advertised_host = None
    rtp_advertised_port = service_info.port if service_info else None

    return web.json_response({
        "x32_ip": bridge.x32_ip,
        "x32_port": bridge.x32_port,
        "x32_connected": bridge.x32_connected,
        "midi_source": bridge.config.get("midi_source", "rtp"),
        "midi_input_status": bridge.get_midi_input_status(),
        "active_channels": bridge.class_selections.get("ch", []),
        "active_class": bridge.active_class,
        "class_selections": bridge.class_selections,
        "undo_cache": bridge.undo_cache,
        "rtp_connected_peers": sorted(bridge.rtp_connected_peers.keys()),
        "rtp_advertised_name": rtp_advertised_name,
        "rtp_advertised_host": rtp_advertised_host,
        "rtp_advertised_port": rtp_advertised_port,
        "web_port": bridge.config.get("web_port", 8090),
    })


async def _handle_midi_devices(request: web.Request) -> web.Response:
    from main import list_local_midi_devices

    try:
        devices = list_local_midi_devices()
    except Exception:
        logger.exception("Failed to enumerate local MIDI devices")
        devices = []
    return web.json_response({"devices": devices})


async def _handle_get_config(request: web.Request) -> web.Response:
    bridge = request.app["bridge"]
    return web.json_response(bridge.config)


async def _handle_export_config(request: web.Request) -> web.Response:
    """Same data as _handle_get_config, just with a Content-Disposition header so a plain
    browser navigation (window.location.href, see app.js) downloads it as a file instead of
    rendering it - lets a user back up/transfer their setup between machines without needing to
    manually copy system_config.json off the filesystem."""
    bridge = request.app["bridge"]
    body = json.dumps(bridge.config, indent=2) + "\n"
    return web.Response(
        body=body,
        content_type="application/json",
        charset="utf-8",
        headers={"Content-Disposition": 'attachment; filename="system_config.json"'},
    )


async def _handle_put_config(request: web.Request) -> web.Response:
    from main import CONFIG_FILE

    bridge = request.app["bridge"]
    try:
        new_config = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(new_config, dict):
        return web.json_response({"error": "Config must be a JSON object"}, status=400)

    errors = _validate_config(new_config)
    if errors:
        return web.json_response({"error": "Validation failed", "details": errors}, status=400)

    # The web UI can only ever be reached while it's already running, so
    # blocking changes to web_enabled here can never trap someone in a
    # disabled state - it only prevents the one-way trip of disabling it
    # from within itself and then having no way back in short of hand-editing
    # the config file.
    current_web_enabled = bridge.config.get("web_enabled", True)
    web_enabled_locked = (
        "web_enabled" in new_config and bool(new_config["web_enabled"]) != bool(current_web_enabled)
    )
    new_config["web_enabled"] = current_web_enabled

    changed_restart_keys = sorted(
        key for key in _RESTART_REQUIRED_KEYS if bridge.config.get(key) != new_config.get(key)
    )
    changed_midi_input_keys = sorted(
        key for key in _MIDI_INPUT_RESTART_KEYS if bridge.config.get(key) != new_config.get(key)
    )

    CONFIG_FILE.write_text(json.dumps(new_config, indent=2) + "\n", encoding="utf-8")
    bridge.config.clear()
    bridge.config.update(new_config)
    if "log_level" in new_config:
        level = getattr(logging, str(new_config["log_level"]).upper(), None)
        if level is not None:
            logging.getLogger().setLevel(level)

    response: Dict[str, Any] = {
        "ok": True,
        "restart_required_for": changed_restart_keys,
        "midi_input_restart_required_for": changed_midi_input_keys,
    }
    if web_enabled_locked:
        response["web_enabled_locked"] = True
    return web.json_response(response)


async def _handle_restart_midi_input(request: web.Request) -> web.Response:
    """Tears down and rebuilds just the MIDI-input subsystem from the config already on disk
    (see _handle_put_config, which the web UI calls first to persist midi_source/rtp_* changes)
    - the web UI, X32 connection, and mappings are untouched, no full bridge restart."""
    bridge = request.app["bridge"]
    try:
        await bridge.restart_midi_input()
    except Exception:
        logger.exception("Failed to restart MIDI input")
        return web.json_response(
            {"error": "MIDI-Eingang konnte nicht neu gestartet werden - siehe Log"}, status=500
        )
    return web.json_response({"ok": True, "midi_input_status": bridge.get_midi_input_status()})


async def _handle_scan_rtp_midi(request: web.Request) -> web.Response:
    """One-shot, on-demand network scan for other RTP-MIDI sessions - see
    X32MidiBridge.scan_rtp_midi_network for what "on demand" means (nothing runs continuously
    in the background, only while this request is in flight)."""
    bridge = request.app["bridge"]
    try:
        results = await bridge.scan_rtp_midi_network()
    except Exception:
        logger.exception("RTP-MIDI network scan failed")
        return web.json_response({"error": "Scan fehlgeschlagen - siehe Log"}, status=500)
    return web.json_response({"sessions": results})


async def _handle_get_mappings(request: web.Request) -> web.Response:
    from main import MAPPINGS_FILE, load_json

    return web.json_response(load_json(MAPPINGS_FILE))


async def _handle_export_mappings(request: web.Request) -> web.Response:
    """Same data as _handle_get_mappings (the on-disk file, with note names exactly as typed -
    not bridge.mappings, which is a normalized runtime copy), just downloadable - see
    _handle_export_config's docstring for why."""
    from main import MAPPINGS_FILE, load_json

    body = json.dumps(load_json(MAPPINGS_FILE), indent=2) + "\n"
    return web.Response(
        body=body,
        content_type="application/json",
        charset="utf-8",
        headers={"Content-Disposition": 'attachment; filename="midi_osc_mappings.json"'},
    )


async def _handle_put_mappings(request: web.Request) -> web.Response:
    from main import MAPPINGS_FILE, normalize_mappings

    bridge = request.app["bridge"]
    try:
        new_mappings = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(new_mappings, list):
        return web.json_response({"error": "Mappings must be a JSON array"}, status=400)

    errors = _validate_mappings(new_mappings)
    if errors:
        return web.json_response({"error": "Validation failed", "details": errors}, status=400)

    # Write the file with note names exactly as the user typed them; the
    # runtime copy is a separately-normalized deep copy so disk stays the
    # human-editable source of truth (normalize_mappings mutates in place).
    MAPPINGS_FILE.write_text(json.dumps(new_mappings, indent=2) + "\n", encoding="utf-8")
    bridge.mappings = normalize_mappings(copy.deepcopy(new_mappings))
    logger.info("Mappings reloaded via web UI (%d entries)", len(bridge.mappings))
    return web.json_response({"ok": True})


async def _handle_validate_note(request: web.Request) -> web.Response:
    from main import note_name_to_midi_number

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    note = str(body.get("note", "")).strip()
    if note.lstrip("-").isdigit():
        number = int(note)
        if 0 <= number <= 127:
            return web.json_response({"midi_number": number})
        return web.json_response({"error": "MIDI number must be between 0 and 127"}, status=400)
    number = note_name_to_midi_number(note)
    if number is None:
        return web.json_response({"error": f"Could not parse note name '{note}'"}, status=400)
    return web.json_response({"midi_number": number})


async def _handle_test_midi(request: web.Request) -> web.Response:
    from main import MidiEvent, note_name_to_midi_number

    bridge = request.app["bridge"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    event_type = body.get("type")
    if event_type not in ("note_on", "note_off", "control_change"):
        return web.json_response({"error": "type must be note_on, note_off, or control_change"}, status=400)

    raw_number = body.get("number")
    if isinstance(raw_number, str) and not raw_number.lstrip("-").isdigit():
        number = note_name_to_midi_number(raw_number)
        if number is None:
            return web.json_response({"error": f"Could not parse note name '{raw_number}'"}, status=400)
    else:
        try:
            number = int(raw_number)
        except (TypeError, ValueError):
            return web.json_response({"error": "number must be an integer or note name"}, status=400)

    try:
        velocity = int(body.get("velocity", 0))
    except (TypeError, ValueError):
        return web.json_response({"error": "velocity must be an integer"}, status=400)

    event = MidiEvent(
        type=event_type,
        number=str(number),
        velocity=velocity,
        timestamp=time.time(),
        peer="web-ui-test",
        raw=None,
    )
    await bridge.handle_midi_event(event)
    return web.json_response({"ok": True, "resolved_number": number})


async def _handle_test_osc_query(request: web.Request) -> web.Response:
    bridge = request.app["bridge"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    path = str(body.get("path", "")).strip()
    if not path.startswith("/"):
        return web.json_response({"error": "path must start with /"}, status=400)
    value = await bridge.query_osc_value(path)
    if value is None:
        return web.json_response({"path": path, "value": None, "note": "No reply (timeout or X32 not reachable)"})
    return web.json_response({"path": path, "value": value})


async def _handle_logs_tail(request: web.Request) -> web.Response:
    log_handler: _SSELogHandler = request.app["log_handler"]
    try:
        tail = int(request.query.get("tail", 200))
    except ValueError:
        tail = 200
    lines = list(log_handler.buffer)[-tail:]
    return web.json_response({"lines": lines})


async def _handle_logs_stream(request: web.Request) -> web.StreamResponse:
    log_handler: _SSELogHandler = request.app["log_handler"]
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)
    queue = log_handler.subscribe()
    try:
        for line in list(log_handler.buffer)[-50:]:
            await response.write(_sse_pack(line))
        while True:
            line = await queue.get()
            await response.write(_sse_pack(line))
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        log_handler.unsubscribe(queue)
    return response


async def _handle_mapping_events_stream(request: web.Request) -> web.StreamResponse:
    broadcaster: _MappingEventBroadcaster = request.app["mapping_events"]
    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)
    queue = broadcaster.subscribe()
    try:
        while True:
            payload = await queue.get()
            await response.write(_sse_pack(payload))
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        broadcaster.unsubscribe(queue)
    return response


def _add_routes(app: web.Application) -> None:
    app.router.add_get("/", _handle_index)
    app.router.add_get("/app.js", _handle_app_js)
    app.router.add_get("/style.css", _handle_style_css)
    app.router.add_get("/api/status", _handle_status)
    app.router.add_get("/api/config", _handle_get_config)
    app.router.add_get("/api/config/export", _handle_export_config)
    app.router.add_get("/api/midi/devices", _handle_midi_devices)
    app.router.add_put("/api/config", _handle_put_config)
    app.router.add_post("/api/midi-input/restart", _handle_restart_midi_input)
    app.router.add_post("/api/midi-input/scan", _handle_scan_rtp_midi)
    app.router.add_get("/api/mappings", _handle_get_mappings)
    app.router.add_get("/api/mappings/export", _handle_export_mappings)
    app.router.add_put("/api/mappings", _handle_put_mappings)
    app.router.add_post("/api/validate-note", _handle_validate_note)
    app.router.add_post("/api/test/midi", _handle_test_midi)
    app.router.add_post("/api/test/osc-query", _handle_test_osc_query)
    app.router.add_get("/api/logs", _handle_logs_tail)
    app.router.add_get("/api/logs/stream", _handle_logs_stream)
    app.router.add_get("/api/mappings/events", _handle_mapping_events_stream)


async def start_web_server(bridge: Any) -> "tuple[web.AppRunner, logging.Handler]":
    """Starts the web UI for the given X32MidiBridge instance. Returns the
    aiohttp runner and the logging handler so the caller can clean both up
    on shutdown."""
    loop = asyncio.get_running_loop()
    log_handler = _SSELogHandler(loop)
    log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(log_handler)
    mapping_events = _MappingEventBroadcaster()
    bridge.on_mapping_fired = mapping_events.publish

    app = web.Application()
    app["bridge"] = bridge
    app["log_handler"] = log_handler
    app["mapping_events"] = mapping_events
    _add_routes(app)

    host = bridge.config.get("web_host", "0.0.0.0")
    port = bridge.config.get("web_port", 8090)
    # access_log=None: aiohttp's per-request access log otherwise propagates
    # to the root logger (and thus into the SSE log stream / buffer above),
    # drowning out application events with e.g. every 2s status poll.
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Web UI listening on http://%s:%s", host, port)
    return runner, log_handler


async def stop_web_server(runner: Optional[web.AppRunner], log_handler: Optional[logging.Handler], bridge: Any = None) -> None:
    if bridge is not None:
        bridge.on_mapping_fired = None
    if log_handler is not None:
        logging.getLogger().removeHandler(log_handler)
    if runner is not None:
        await runner.cleanup()
