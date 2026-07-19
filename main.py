import argparse
import asyncio
import errno
import json
import logging
import logging.handlers
import re
import socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from pythonosc.udp_client import SimpleUDPClient
from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder
from pymidi.server import Handler as PymidiHandler, Server as PymidiServer
from zeroconf import ServiceInfo, Zeroconf
import rtmidi

CONFIG_FILE = Path("system_config.json")
MAPPINGS_FILE = Path("midi_osc_mappings.json")
LOG_FILE = Path("bridge.log")

logger = logging.getLogger("x32-midi-bridge")
CHANNEL_MIN = 1
CHANNEL_MAX = 32
AUTO_DISCOVERY_BROADCAST = "255.255.255.255"
X32_DEFAULT_DISCOVERY_PORT = 10023

# Consecutive missed /xinfo keep-alive replies before the X32 is considered
# disconnected. UDP drops the occasional packet even on a healthy network, so
# a single miss isn't treated as a real outage.
X32_KEEPALIVE_FAILURE_THRESHOLD = 3

# Velocity -> OSC address-space class for the set_channel_class action. Fixed
# and small on purpose: an arbitrary but stable lookup, not something that
# needs to be tunable per mapping.
CLASS_BY_VELOCITY: Dict[int, str] = {
    1: "ch",
    2: "bus",
    3: "auxin",
    4: "fxrtn",
    5: "mtx",
    6: "dca",
}

# Per-class (min, max, zero-padding width) in the X32's own OSC address
# space - hardware facts, not a user preference. Unknown class names fall
# back to the ch values (today's behavior, unchanged).
CLASS_ADDRESS_INFO: Dict[str, "tuple[int, int, int]"] = {
    "ch": (1, 32, 2),
    "bus": (1, 16, 2),
    "auxin": (1, 8, 2),
    "fxrtn": (1, 8, 2),
    "mtx": (1, 6, 2),
    "dca": (1, 8, 1),
}

NOTE_NAME_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)$")
_NOTE_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def note_name_to_midi_number(name: str) -> Optional[int]:
    match = NOTE_NAME_RE.match(name.strip())
    if not match:
        return None
    letter, accidental, octave = match.groups()
    semitone = _NOTE_SEMITONES[letter.upper()]
    if accidental == "#":
        semitone += 1
    elif accidental == "b":
        semitone -= 1
    # Ableton-style convention: C3 = MIDI note 60.
    midi_number = (int(octave) + 2) * 12 + semitone
    return midi_number if 0 <= midi_number <= 127 else None


def normalize_mappings(mappings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def normalize_trigger(trigger: Optional[Dict[str, Any]]) -> None:
        if not trigger or trigger.get("type") not in ("note_on", "note_off"):
            return
        number = trigger.get("number")
        if isinstance(number, str) and not number.lstrip("-").isdigit():
            midi_number = note_name_to_midi_number(number)
            if midi_number is not None:
                trigger["number"] = str(midi_number)
            else:
                logger.warning("Could not parse note name %r in mapping trigger", number)

    for mapping in mappings:
        normalize_trigger(mapping.get("trigger"))
        normalize_trigger(mapping.get("undo_trigger"))
    return mappings


@dataclass
class MidiEvent:
    type: str
    number: str
    velocity: int
    timestamp: float
    peer: str
    raw: Any


class X32MidiBridge:
    def __init__(self, config: Dict[str, Any], mappings: List[Dict[str, Any]], test_mode: bool = False):
        self.config = config
        self.mappings = mappings
        self.test_mode = test_mode
        self.event_queue: asyncio.Queue[MidiEvent] = asyncio.Queue()
        self.active_class: str = "ch"
        self.class_selections: Dict[str, List[int]] = {}
        self.undo_cache: Dict[str, Any] = {}
        self.x32_ip: Optional[str] = None
        self.x32_port: int = config.get("x32_port", 10023)
        self.x32_connected: bool = False
        self.udp_client: Optional[SimpleUDPClient] = None
        self.udp_broadcast_socket: Optional[socket.socket] = None
        self.osc_reply_socket: Optional[socket.socket] = None
        self.osc_reply_task: Optional[asyncio.Task[Any]] = None
        self.pending_queries: Dict[str, List["asyncio.Future[Any]"]] = {}
        self.zeroconf = Zeroconf()
        self.running = True
        self.rtp_server: Optional[PymidiServer] = None
        self.rtp_server_thread: Optional[threading.Thread] = None
        self.rtp_handler: Optional["_BridgeMidiHandler"] = None
        self.rtp_connected_peers: Dict[str, Any] = {}
        self.local_midi_listener: Optional["_LocalMidiListener"] = None
        self.service_info: Optional[ServiceInfo] = None
        self.tasks: List[asyncio.Task[Any]] = []
        self.discovery_task: Optional[asyncio.Task[Any]] = None
        self.auto_discovery_task: Optional[asyncio.Task[Any]] = None
        self.last_rtp_status: Optional[str] = None
        self.web_runner: Optional[Any] = None
        self.web_log_handler: Optional[logging.Handler] = None
        self.on_mapping_fired: Optional[Any] = None
        self._warned_velocity_zero_note_on = False  # see build_midi_event()

    async def start(self):
        self.setup_logging()
        await self.open_osc_client()
        await self.start_midi_input()
        await self.start_web_server()
        self.tasks.append(asyncio.create_task(self.process_events()))
        self.tasks.append(asyncio.create_task(self.monitor_rtp_status()))
        self.tasks.append(asyncio.create_task(self.monitor_x32_connection()))
        if self.test_mode:
            self.tasks.append(asyncio.create_task(self.cli_test_mode()))
        await self._run_forever()

    async def start_web_server(self) -> None:
        if not self.config.get("web_enabled", True):
            logger.info("Web UI disabled via config (web_enabled: false)")
            return
        import webui
        try:
            self.web_runner, self.web_log_handler = await webui.start_web_server(self)
        except Exception:
            logger.exception("Failed to start web UI")

    async def _run_forever(self) -> None:
        try:
            while self.running:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    def setup_logging(self):
        level_name = self.config.get("log_level", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")
        try:
            # A rotating file survives a crashed process or a closed terminal
            # window - the console and the web UI's 500-line ring buffer
            # otherwise lose all history the moment either goes away, which
            # is exactly when you'd want to look back at what happened
            # (e.g. after a problem during a show).
            file_handler = logging.handlers.RotatingFileHandler(
                LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            logging.getLogger().addHandler(file_handler)
        except OSError:
            logging.getLogger("x32-midi-bridge").warning(
                "Could not open %s for logging - continuing with console-only logging", LOG_FILE
            )

    async def open_osc_client(self):
        self._create_osc_reply_socket()
        self.osc_reply_task = asyncio.create_task(self._listen_for_osc_replies())
        self.tasks.append(self.osc_reply_task)
        if self.config.get("x32_ip", "auto") != "auto":
            self.x32_ip = self.config["x32_ip"]
            self.udp_client = SimpleUDPClient(self.x32_ip, self.x32_port)
            self.x32_connected = True
        else:
            self._create_broadcast_socket()
            self.discovery_task = asyncio.create_task(self._listen_for_discovery_replies())
            self.auto_discovery_task = asyncio.create_task(self.auto_discover_x32())
            self.tasks.append(self.discovery_task)
            self.tasks.append(self.auto_discovery_task)

    async def monitor_rtp_status(self):
        while self.running:
            await asyncio.sleep(1)
            status = self.get_midi_input_status()
            if status and status != self.last_rtp_status:
                self.last_rtp_status = status
                logger.info("MIDI input status: %s", status)

    async def auto_discover_x32(self):
        while self.running and self.x32_ip is None:
            logger.info("Auto-discovering X32 via /xinfo broadcast")
            await self._send_osc_broadcast("/xinfo", [])
            await asyncio.sleep(self.config.get("discovery_interval_s", 5))

    async def monitor_x32_connection(self):
        # Once discovered (or configured with a fixed IP), the bridge never
        # re-checked whether the X32 was still there - a dropped WiFi link,
        # power cycle, or unplugged cable would go unnoticed and OSC commands
        # would silently vanish into the void until someone restarted the
        # bridge. This periodically re-queries /xinfo on the known address
        # and, for auto-discovered consoles, re-triggers discovery once it's
        # confirmed missing.
        consecutive_failures = 0
        while self.running:
            await asyncio.sleep(self.config.get("discovery_interval_s", 5))
            if self.x32_ip is None:
                continue
            reply = await self.query_osc_value("/xinfo")
            if reply is not None:
                if not self.x32_connected:
                    logger.info("X32 connection re-established at %s", self.x32_ip)
                consecutive_failures = 0
                self.x32_connected = True
                continue

            consecutive_failures += 1
            if consecutive_failures < X32_KEEPALIVE_FAILURE_THRESHOLD or not self.x32_connected:
                # Below the threshold, or already flagged and handled - don't
                # re-log/re-trigger reconnection on every subsequent tick.
                continue

            self.x32_connected = False
            if self.config.get("x32_ip", "auto") == "auto":
                logger.warning(
                    "X32 at %s not responding after %d keep-alive attempts - "
                    "assuming disconnected, restarting auto-discovery",
                    self.x32_ip, consecutive_failures,
                )
                self.x32_ip = None
                self.udp_client = None
                consecutive_failures = 0
                if self.auto_discovery_task is None or self.auto_discovery_task.done():
                    self.auto_discovery_task = asyncio.create_task(self.auto_discover_x32())
                    self.tasks.append(self.auto_discovery_task)
            else:
                logger.warning(
                    "X32 at fixed address %s not responding after %d keep-alive attempts - "
                    "will keep retrying at that address",
                    self.x32_ip, consecutive_failures,
                )

    async def start_midi_input(self) -> None:
        midi_source = self.config.get("midi_source", "rtp")
        if midi_source == "rtp":
            logger.info("Starting RTP-MIDI (AppleMIDI) server and zeroconf advertisement")
            self.advertise_rtp_midi()
            self._start_rtp_server()
        else:
            self._start_local_midi(midi_source)

    def _start_local_midi(self, device_name: str) -> None:
        loop = asyncio.get_running_loop()
        self.local_midi_listener = _LocalMidiListener(self, loop, device_name)
        try:
            self.local_midi_listener.start()
        except Exception:
            logger.exception("Failed to open local MIDI device '%s'", device_name)
            self.local_midi_listener = None

    def advertise_rtp_midi(self):
        base_name = self.config.get('rtp_session_name', 'x32-midi-bridge')
        service_type = "_apple-midi._udp.local."
        service_name = f"{base_name}.{service_type}"
        local_ip = self._resolve_rtp_host_ip()
        control_port = self.config.get("rtp_local_port", 5004)
        for attempt in range(1, 6):
            self.service_info = ServiceInfo(
                service_type,
                service_name,
                addresses=[socket.inet_aton(local_ip)],
                port=control_port,
                properties={"name": base_name},
                server="x32-midi-bridge.local.",
            )
            try:
                self.zeroconf.register_service(self.service_info)
                logger.info("Announced RTP-MIDI (AppleMIDI) service %s", self.service_info.name)
                return
            except Exception as exc:
                if 'NonUniqueNameException' in type(exc).__name__ or 'NonUniqueNameException' in str(exc):
                    service_name = f"{base_name}-{attempt}.{service_type}"
                    logger.warning("RTP-MIDI service name conflict, retrying with %s", service_name)
                    continue
                raise
        logger.error("Failed to register RTP-MIDI service after multiple attempts")

    def _resolve_rtp_host_ip(self) -> str:
        address = self.config.get("rtp_host_ip", "auto")
        if address in ("auto", "", None):
            address = self._discover_local_ip()
            logger.info("Auto-selected RTP host IP %s for zeroconf advertisement", address)
        return address

    def get_local_ip_bytes(self) -> bytes:
        return socket.inet_aton(self._resolve_rtp_host_ip())

    def _discover_local_ip(self) -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"

    def _create_broadcast_socket(self) -> None:
        if self.udp_broadcast_socket is not None:
            return
        listen_port = self.config.get("discovery_listen_port", self.x32_port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", listen_port))
        sock.setblocking(False)
        self.udp_broadcast_socket = sock

    def _close_broadcast_socket(self) -> None:
        if self.udp_broadcast_socket is not None:
            try:
                self.udp_broadcast_socket.close()
            except OSError:
                pass
            self.udp_broadcast_socket = None

    def _create_osc_reply_socket(self) -> None:
        if self.osc_reply_socket is not None:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", 0))
        sock.setblocking(False)
        self.osc_reply_socket = sock

    def _close_osc_reply_socket(self) -> None:
        if self.osc_reply_socket is not None:
            try:
                self.osc_reply_socket.close()
            except OSError:
                pass
            self.osc_reply_socket = None

    async def _listen_for_osc_replies(self) -> None:
        if self.osc_reply_socket is None:
            return
        loop = asyncio.get_running_loop()
        while self.running and self.osc_reply_socket is not None:
            try:
                data, addr = await loop.sock_recvfrom(self.osc_reply_socket, 4096)
            except OSError:
                break
            try:
                message = OscMessage(data)
            except Exception:
                logger.exception("Failed to parse OSC reply from %s", addr)
                continue
            self._resolve_pending_query(message.address, list(message.params))

    def _resolve_pending_query(self, path: str, params: List[Any]) -> None:
        futures = self.pending_queries.pop(path, None)
        if not futures:
            return
        value = params[0] if params else None
        for future in futures:
            if not future.done():
                future.set_result(value)

    async def _listen_for_discovery_replies(self) -> None:
        if self.udp_broadcast_socket is None:
            return
        loop = asyncio.get_running_loop()
        while self.running and self.udp_broadcast_socket is not None:
            try:
                # sock_recvfrom (not run_in_executor) is required here: the socket is
                # non-blocking, so a plain recvfrom() in a worker thread would raise
                # BlockingIOError immediately instead of waiting for data whenever no
                # reply happens to already be buffered.
                data, addr = await loop.sock_recvfrom(self.udp_broadcast_socket, 4096)
            except OSError:
                break
            try:
                message = OscMessage(data)
                self._handle_discovery_response(addr, message.address, *message.params)
            except Exception:
                logger.exception("Failed to parse discovery response")

    def _handle_discovery_response(self, client_address: tuple[str, int], address: str, *args: Any) -> None:
        if self.x32_ip is not None:
            return
        if address != "/xinfo" or not args:
            # A genuine X32 /xinfo reply always carries several string fields
            # (IP, console name, model, firmware). An empty-args "/xinfo" is our
            # own outgoing broadcast query looping back to this socket (observed
            # on Windows, where a broadcast can be delivered back to the sender)
            # - not a real reply, so it must be ignored rather than mistaken for
            # a discovered console.
            logger.debug("Ignoring implausible discovery reply from %s: %s %s", client_address, address, args)
            return
        self.x32_ip = client_address[0]
        logger.info("Discovered X32 at %s via OSC reply to %s", self.x32_ip, address)
        self.udp_client = SimpleUDPClient(self.x32_ip, self.x32_port)
        self.x32_connected = True
        if self.auto_discovery_task is not None:
            self.auto_discovery_task.cancel()
            self.auto_discovery_task = None

    def _broadcast_targets(self) -> List[str]:
        # 255.255.255.255 (the "limited broadcast" address) is not reliably
        # delivered to other stations on every WiFi AP/router - observed in
        # practice to get zero replies on some networks where the directed
        # subnet broadcast (e.g. 192.168.1.255) works every time. Sending to
        # both costs one extra small UDP packet and covers either behavior.
        # Assumes a /24 subnet, the common case for home/office/stage LANs.
        targets = [AUTO_DISCOVERY_BROADCAST]
        local_ip = self._discover_local_ip()
        parts = local_ip.split(".")
        if len(parts) == 4:
            subnet_broadcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
            if subnet_broadcast not in targets:
                targets.append(subnet_broadcast)
        return targets

    async def _send_osc_broadcast(self, path: str, args: Iterable[Any]) -> None:
        if self.udp_broadcast_socket is None:
            self._create_broadcast_socket()
        message = OscMessageBuilder(address=path)
        for arg in args:
            message.add_arg(arg)
        packet = message.build().dgram
        port = self.config.get("x32_port", X32_DEFAULT_DISCOVERY_PORT)
        for target in self._broadcast_targets():
            try:
                self.udp_broadcast_socket.sendto(packet, (target, port))
                logger.debug("Broadcasted OSC %s to %s", path, target)
            except Exception:
                logger.exception("Failed to broadcast OSC discovery message to %s", target)

    def _start_rtp_server(self) -> None:
        control_port = self.config.get("rtp_local_port", 5004)
        try:
            self.rtp_handler = _BridgeMidiHandler(self, asyncio.get_running_loop())
            self.rtp_server = PymidiServer([("0.0.0.0", control_port)])
            self.rtp_server.add_handler(self.rtp_handler)
            self.rtp_server_thread = threading.Thread(
                target=self._run_rtp_server, name="pymidi-server", daemon=True,
            )
            self.rtp_server_thread.start()
            logger.info(
                "RTP-MIDI (AppleMIDI) server listening on 0.0.0.0:%s (data port %s)",
                control_port, control_port + 1,
            )
        except Exception:
            logger.exception("Failed to start RTP-MIDI server")

    def _run_rtp_server(self) -> None:
        try:
            self.rtp_server.serve_forever()
        except OSError as exc:
            control_port = self.config.get("rtp_local_port", 5004)
            if exc.errno == errno.EADDRINUSE:
                logger.error(
                    "RTP-MIDI server could not start: port %s or %s is already in use "
                    "(e.g. by another RTP-MIDI service/driver, or another instance of this "
                    "bridge). Set a different 'rtp_local_port' in system_config.json and restart.",
                    control_port, control_port + 1,
                )
            else:
                logger.exception("RTP-MIDI server thread crashed")
        except Exception:
            logger.exception("RTP-MIDI server thread crashed")

    def _on_rtp_peer_connected(self, peer: Any) -> None:
        self.rtp_connected_peers[str(peer)] = peer
        logger.info("RTP-MIDI peer connected: %s", peer)

    def _on_rtp_peer_disconnected(self, peer: Any) -> None:
        self.rtp_connected_peers.pop(str(peer), None)
        logger.info("RTP-MIDI peer disconnected: %s", peer)

    def get_rtp_status(self) -> str:
        if self.rtp_server is None:
            return "RTP-MIDI server not started"
        if not self.rtp_connected_peers:
            return "RTP-MIDI server listening; no peers connected"
        return "RTP-MIDI peers connected: " + ", ".join(sorted(self.rtp_connected_peers))

    def get_midi_input_status(self) -> str:
        if self.config.get("midi_source", "rtp") == "rtp":
            return self.get_rtp_status()
        if self.local_midi_listener is None or self.local_midi_listener.midi_in is None:
            return "Lokales MIDI nicht gestartet"
        return f"Lokales MIDI aktiv: {self.local_midi_listener.device_name}"

    async def shutdown(self) -> None:
        logger.info("Shutting down bridge")
        self.running = False
        if self.local_midi_listener is not None:
            self.local_midi_listener.stop()
        if self.auto_discovery_task is not None:
            self.auto_discovery_task.cancel()
        if self.discovery_task is not None:
            self.discovery_task.cancel()
        await asyncio.gather(*(self.tasks + ([self.discovery_task] if self.discovery_task else []) + ([self.auto_discovery_task] if self.auto_discovery_task else [])), return_exceptions=True)
        try:
            if self.service_info is not None:
                self.zeroconf.unregister_service(self.service_info)
        except Exception:
            pass
        try:
            self.zeroconf.close()
        except Exception:
            pass
        self._close_broadcast_socket()
        self._close_osc_reply_socket()
        if self.web_runner is not None:
            import webui
            try:
                await webui.stop_web_server(self.web_runner, self.web_log_handler, self)
            except Exception:
                logger.exception("Failed to stop web UI cleanly")
        if self.rtp_server_thread is not None and self.rtp_server_thread.is_alive():
            # pymidi's Server.serve_forever() has no public stop/shutdown hook, so the
            # daemon thread is simply abandoned here; it will not prevent process exit.
            logger.debug("RTP-MIDI server thread left running as daemon (pymidi has no stop hook)")

    async def process_events(self):
        logger.info("Starting MIDI event processor")
        while self.running:
            event = await self.event_queue.get()
            try:
                await self.handle_midi_event(event)
            except Exception:
                logger.exception("Error processing MIDI event")
            finally:
                self.event_queue.task_done()

    async def handle_midi_event(self, event: MidiEvent):
        undo_mapping = self.find_undo_mapping(event)
        if undo_mapping is not None:
            self._notify_mapping_fired(undo_mapping.get("name", "?"), "undo")
            await self.restore_undo(undo_mapping)
            return

        mapping = self.find_mapping(event)
        if not mapping:
            logger.debug("No mapping for event %s", event)
            return

        self._notify_mapping_fired(mapping.get("name", "?"), "trigger")

        if mapping.get("action") in ("set_channel", "add_channel", "set_channel_class"):
            self.handle_channel_action(mapping, event)
            return

        for action_desc in mapping.get("actions", []):
            await self.execute_mapping_action(action_desc, event, mapping.get("save_state", False))

    def _notify_mapping_fired(self, name: str, kind: str) -> None:
        # Optional hook the web UI wires up (see webui.start_web_server) to
        # briefly highlight the mapping in its list when it actually fires -
        # a no-op when the web UI is disabled.
        if self.on_mapping_fired is not None:
            self.on_mapping_fired(name, kind)

    def find_mapping(self, event: MidiEvent) -> Optional[Dict[str, Any]]:
        for mapping in self.mappings:
            if self.match_trigger(mapping.get("trigger", {}), event):
                return mapping
        return None

    def find_undo_mapping(self, event: MidiEvent) -> Optional[Dict[str, Any]]:
        for mapping in self.mappings:
            undo_trigger = mapping.get("undo_trigger")
            if undo_trigger and self.match_trigger(undo_trigger, event):
                return mapping
        return None

    def match_trigger(self, trigger: Dict[str, Any], event: MidiEvent) -> bool:
        if trigger.get("type") != event.type:
            return False
        return str(trigger.get("number")) == event.number

    def handle_channel_action(self, mapping: Dict[str, Any], event: MidiEvent):
        action = mapping["action"]
        if action == "set_channel_class":
            new_class = CLASS_BY_VELOCITY.get(event.velocity, "ch")
            self.active_class = new_class
            logger.info("Active channel class set to %s", new_class)
            return

        min_c, max_c, _padding = CLASS_ADDRESS_INFO.get(self.active_class, (CHANNEL_MIN, CHANNEL_MAX, 2))
        channel = max(min_c, min(max_c, event.velocity))
        selection = self.class_selections.setdefault(self.active_class, [])
        if action == "set_channel":
            selection.clear()
            selection.append(channel)
            logger.info("Active channels (class=%s) set to %s", self.active_class, selection)
        elif action == "add_channel":
            if channel not in selection:
                selection.append(channel)
            logger.info("Added channel %s to class %s -> %s", channel, self.active_class, selection)

    async def restore_undo(self, mapping: Dict[str, Any]):
        if not mapping.get("save_state", False):
            logger.debug("Undo trigger ignored because save_state is false")
            return
        for action_desc in mapping.get("actions", []):
            pattern = self._resolved_path_pattern(action_desc["path"])
            for path in [p for p in self.undo_cache if pattern.match(p)]:
                value = self.undo_cache.pop(path)
                await self.send_osc_message(path, [value])
                logger.info("Restored undo for %s", path)

    def _resolved_path_pattern(self, path_template: str) -> "re.Pattern[str]":
        escaped = re.escape(path_template)
        escaped = escaped.replace(re.escape("{active_class}"), r"[a-z]+")
        escaped = escaped.replace(re.escape("{active_channels}"), r"\d+")
        return re.compile(f"^{escaped}$")

    async def execute_mapping_action(self, action_desc: Dict[str, Any], event: MidiEvent, save_state: bool):
        path_template = action_desc["path"]
        uses_midi_value = action_desc.get("value") == "midi_value"

        if uses_midi_value:
            await self.send_to_active_channels(path_template, action_desc, event, save_state)
            return

        if self.is_hybrid_single_channel(event.velocity, action_desc):
            if "{active_class}" in path_template:
                min_c, max_c, padding = CLASS_ADDRESS_INFO.get(self.active_class, (CHANNEL_MIN, CHANNEL_MAX, 2))
                channel = max(min_c, min(max_c, event.velocity))
                path = path_template.replace("{active_class}", self.active_class).replace(
                    "{active_channels}", f"{channel:0{padding}d}"
                )
            else:
                channel = max(CHANNEL_MIN, min(CHANNEL_MAX, event.velocity))
                path = path_template.replace("{active_channels}", f"{channel:02d}")
            await self._save_state_if_needed(path, save_state)
            value = await self._resolve_action_value(action_desc, event, path)
            await self.send_osc_message(path, [value])
            return

        if self.is_hybrid_multi_channel(event.velocity, action_desc):
            await self.send_to_active_channels(path_template, action_desc, event, save_state)
            return

        await self.send_to_active_channels(path_template, action_desc, event, save_state)

    async def _resolve_action_value(self, action_desc: Dict[str, Any], event: MidiEvent, path: str) -> Any:
        raw_value = action_desc.get("value", 1)
        if raw_value == "midi_value":
            return self.scale(event.velocity, action_desc.get("scale"))
        if raw_value == "toggle":
            on_value = action_desc.get("toggle_on_value", 1)
            off_value = action_desc.get("toggle_off_value", 0)
            current = await self.query_osc_value(path)
            if current is None:
                logger.warning(
                    "Toggle: could not read current value for %s (query timed out) - defaulting to on-value %s",
                    path, on_value,
                )
                return on_value
            is_on = abs(current - on_value) <= abs(current - off_value)
            return off_value if is_on else on_value
        return raw_value

    async def _save_state_if_needed(self, path: str, save_state: bool) -> None:
        if not save_state or path in self.undo_cache:
            return
        current = await self.query_osc_value(path)
        if current is not None:
            self.undo_cache[path] = current
            logger.debug("Saved state for %s = %s", path, current)

    async def query_osc_value(self, path: str) -> Optional[Any]:
        if not self.x32_ip or self.osc_reply_socket is None:
            logger.debug("Cannot query OSC state for %s: X32 IP not resolved yet", path)
            return None
        loop = asyncio.get_running_loop()
        future: "asyncio.Future[Any]" = loop.create_future()
        self.pending_queries.setdefault(path, []).append(future)
        try:
            builder = OscMessageBuilder(address=path)
            self.osc_reply_socket.sendto(builder.build().dgram, (self.x32_ip, self.x32_port))
            logger.debug("Querying OSC state for %s", path)
            timeout = self.config.get("undo_timeout_ms", 100) / 1000.0
            try:
                return await asyncio.wait_for(future, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for OSC reply to %s", path)
                return None
        except Exception:
            logger.exception("Failed to query OSC state for %s", path)
            return None
        finally:
            pending = self.pending_queries.get(path)
            if pending and future in pending:
                pending.remove(future)
                if not pending:
                    self.pending_queries.pop(path, None)

    def is_hybrid_single_channel(self, velocity: int, action_desc: Dict[str, Any]) -> bool:
        if action_desc.get("value") == "midi_value":
            return False
        return velocity not in (0, 127)

    def is_hybrid_multi_channel(self, velocity: int, action_desc: Dict[str, Any]) -> bool:
        if action_desc.get("value") == "midi_value":
            return False
        return velocity in (0, 127)

    async def send_to_active_channels(
        self, path_template: str, action_desc: Dict[str, Any], event: MidiEvent, save_state: bool = False
    ):
        if "{active_class}" in path_template:
            entries = [(cls, idx) for cls, indices in self.class_selections.items() for idx in indices]
            if not entries:
                logger.warning("No active channels configured in any class, defaulting to ch 1")
                self.class_selections.setdefault("ch", []).append(1)
                entries = [("ch", 1)]
            for cls, idx in entries:
                _min_c, _max_c, padding = CLASS_ADDRESS_INFO.get(cls, (CHANNEL_MIN, CHANNEL_MAX, 2))
                path = path_template.replace("{active_class}", cls).replace(
                    "{active_channels}", f"{idx:0{padding}d}"
                )
                await self._save_state_if_needed(path, save_state)
                value = await self._resolve_action_value(action_desc, event, path)
                await self.send_osc_message(path, [value])
            return

        channels = self.class_selections.get("ch")
        if not channels:
            logger.warning("No active channels configured, defaulting to channel 1")
            channels = [1]
            self.class_selections["ch"] = channels
        for channel in channels:
            path = path_template.replace("{active_channels}", f"{channel:02d}")
            await self._save_state_if_needed(path, save_state)
            value = await self._resolve_action_value(action_desc, event, path)
            await self.send_osc_message(path, [value])

    def scale(self, midi_value: int, scale_type: Optional[str]) -> Any:
        if scale_type == "midi_to_pan":
            return (midi_value / 127.0) * 2.0 - 1.0
        if scale_type == "midi_to_fader":
            return (midi_value / 127.0) ** 2
        if scale_type == "invert":
            return 127 - midi_value
        return midi_value

    async def send_osc_message(self, path: str, args: Iterable[Any]):
        if not self.udp_client:
            if self.x32_ip:
                self.udp_client = SimpleUDPClient(self.x32_ip, self.x32_port)
            else:
                logger.warning("Dropping OSC message because X32 IP is not set: %s", path)
                return

        if self.config.get("double_send", False):
            await self._send_osc_message(path, args)
            await asyncio.sleep(0.005)
            await self._send_osc_message(path, args)
            return
        await self._send_osc_message(path, args)

    async def _send_osc_message(self, path: str, args: Iterable[Any]):
        logger.info("Sending OSC %s %s", path, list(args))
        try:
            builder = OscMessageBuilder(address=path)
            for arg in args:
                builder.add_arg(arg)
            self.udp_client.send(builder.build())
        except Exception:
            logger.exception("Failed to send OSC message")

    async def cli_test_mode(self):
        logger.info("CLI test mode activated")
        while self.running:
            await asyncio.sleep(1)


class _BridgeMidiHandler(PymidiHandler):
    def __init__(self, bridge: X32MidiBridge, loop: asyncio.AbstractEventLoop):
        self.bridge = bridge
        self.loop = loop

    def on_peer_connected(self, peer: Any) -> None:
        self.loop.call_soon_threadsafe(self.bridge._on_rtp_peer_connected, peer)

    def on_peer_disconnected(self, peer: Any) -> None:
        self.loop.call_soon_threadsafe(self.bridge._on_rtp_peer_disconnected, peer)

    def on_midi_commands(self, peer: Any, command_list: Iterable[Any]) -> None:
        for command in command_list:
            logger.debug("Received raw MIDI command from %s: %s", peer, command.command)
            event = self._translate(peer, command)
            if event is not None:
                logger.debug("Translated to %s", event)
                self.loop.call_soon_threadsafe(self.bridge.event_queue.put_nowait, event)

    def _translate(self, peer: Any, command: Any) -> Optional[MidiEvent]:
        if command.command in ("note_on", "note_off"):
            type_str = str(command.command)
            number = int(command.params.key)
            velocity = int(command.params.velocity)
        elif command.command == "control_mode_change":
            # pymidi names Control Change 'control_mode_change'; translated here to
            # 'control_change' so existing mapping JSON / README wording stays valid.
            type_str = "control_change"
            number = int(command.params.controller)
            velocity = int(command.params.value)
        else:
            logger.debug("Ignoring unsupported MIDI command type %s", command.command)
            return None
        return build_midi_event(self.bridge, type_str, number, velocity, str(peer), raw=command)


def build_midi_event(
    bridge: "X32MidiBridge", type_str: str, number: int, velocity: int, peer: str, raw: Any = None
) -> MidiEvent:
    """Builds a MidiEvent from an already-parsed note/CC message, shared by
    every MIDI input source (RTP-MIDI, local MIDI interfaces, ...) so the
    velocity-0-note-on normalization below only has to live in one place."""
    if type_str == "note_on" and velocity == 0:
        # Some MIDI sources signal "key released" as a note_on with velocity 0
        # instead of a real note_off message (a common running-status
        # bandwidth optimization). Normalizing it here means it is treated as
        # a release everywhere downstream - notably, it can no longer be
        # misread as a deliberate velocity-0 "whole channel group" signal in
        # the hybrid channel mode (see docs/mappings.md).
        type_str = "note_off"
        if not bridge._warned_velocity_zero_note_on:
            bridge._warned_velocity_zero_note_on = True
            logger.info(
                "Note-On mit Velocity 0 (Note %s) empfangen und als Note-Off behandelt "
                "(Standard-MIDI-Konvention einiger Sender). Weitere Vorkommen werden nicht "
                "mehr geloggt.",
                number,
            )
    return MidiEvent(
        type=type_str,
        number=str(number),
        velocity=velocity,
        timestamp=time.time(),
        peer=peer,
        raw=raw,
    )


def list_local_midi_devices() -> List[str]:
    midi_in = rtmidi.MidiIn()
    try:
        return list(midi_in.get_ports())
    finally:
        del midi_in


class _LocalMidiListener:
    """Reads MIDI from a local hardware/virtual MIDI input port via
    python-rtmidi, translating messages into the same MidiEvent shape as the
    RTP-MIDI path (see build_midi_event) so mapping/hybrid-channel logic
    doesn't need to know which transport a note came from."""

    def __init__(self, bridge: "X32MidiBridge", loop: asyncio.AbstractEventLoop, device_name: str):
        self.bridge = bridge
        self.loop = loop
        self.device_name = device_name
        self.midi_in: Optional["rtmidi.MidiIn"] = None

    def start(self) -> None:
        self.midi_in = rtmidi.MidiIn()
        ports = self.midi_in.get_ports()
        try:
            port_index = ports.index(self.device_name)
        except ValueError:
            self.midi_in = None
            raise RuntimeError(
                f"Local MIDI device '{self.device_name}' not found. Available: {ports}"
            )
        self.midi_in.open_port(port_index)
        self.midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
        self.midi_in.set_callback(self._on_message)
        logger.info("Local MIDI input opened: %s", self.device_name)

    def stop(self) -> None:
        if self.midi_in is not None:
            self.midi_in.close_port()
            self.midi_in = None

    def _on_message(self, event: Any, data: Any = None) -> None:
        message, _delta_time = event
        if len(message) < 3:
            return
        status, data1, data2 = message[0], message[1], message[2]
        kind = status & 0xF0
        if kind == 0x90:
            type_str = "note_on"
        elif kind == 0x80:
            type_str = "note_off"
        elif kind == 0xB0:
            type_str = "control_change"
        else:
            logger.debug("Ignoring unsupported local MIDI status byte 0x%02x", status)
            return
        midi_event = build_midi_event(
            self.bridge, type_str, data1, data2, f"local:{self.device_name}", raw=list(message)
        )
        logger.debug("Translated local MIDI message to %s", midi_event)
        self.loop.call_soon_threadsafe(self.bridge.event_queue.put_nowait, midi_event)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_json_or_exit(path: Path) -> Any:
    try:
        return load_json(path)
    except FileNotFoundError:
        print(f"Fehler: Datei '{path}' wurde nicht gefunden.", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(f"Fehler: '{path}' enthält ungültiges JSON: {exc}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Async X32 MIDI-to-OSC Controller Daemon")
    parser.add_argument("--test", action="store_true", help="Enable CLI test mode")
    args = parser.parse_args()

    config = _load_json_or_exit(CONFIG_FILE)
    mappings = normalize_mappings(_load_json_or_exit(MAPPINGS_FILE))
    bridge = X32MidiBridge(config, mappings, test_mode=args.test)
    try:
        asyncio.run(bridge.start())
    except KeyboardInterrupt:
        print("\nBridge gestoppt (Strg+C).")


if __name__ == "__main__":
    main()
