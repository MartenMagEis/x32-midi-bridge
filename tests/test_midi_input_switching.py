import asyncio
import socket

import pytest

import main


def _free_udp_port() -> int:
    """An ephemeral port genuinely free right now - good enough for a test that binds it
    immediately afterward (a small race exists in principle, but is not a practical problem
    for a local test run)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---- stop_midi_input / restart_midi_input: RTP-MIDI ----
# These exercise the real pymidi server + real sockets, not mocks - the whole point of this
# feature is that pymidi's serve_forever() has no public stop hook (see _StopServeForever's
# docstring), so what's actually being verified is that the wake-socket signal really does
# unblock the server thread's select() loop and let it exit. Worth calling out: an earlier
# version of this mechanism closed the server's own sockets instead, which passed this exact
# test suite on this dev machine (Windows) but was then found NOT to reliably unblock select()
# on real Linux hardware (the actual deployment target) - it left the thread alive past the
# join timeout and the next bind attempt failed with "address already in use". That's exactly
# why this is a real integration test and not a mock - and also why passing here is reassuring
# but not by itself sufficient; this whole feature was only actually confirmed by testing on
# the Pi directly.

def test_stop_midi_input_terminates_the_rtp_server_thread(bridge):
    port = _free_udp_port()
    bridge.config["midi_source"] = "rtp"
    bridge.config["rtp_local_port"] = port
    bridge.config["rtp_host_ip"] = "127.0.0.1"

    async def scenario():
        await bridge.start_midi_input()
        assert bridge.rtp_server_thread is not None
        assert bridge.rtp_server_thread.is_alive()

        await bridge.stop_midi_input()

        assert bridge.rtp_server is None
        assert bridge.rtp_server_thread is None
        assert bridge.service_info is None

    asyncio.run(scenario())


def test_restart_midi_input_can_rebind_the_same_port(bridge):
    """Proves the socket was actually released (not leaked) - a second bind to the exact same
    port only succeeds if the first one was properly closed."""
    port = _free_udp_port()
    bridge.config["midi_source"] = "rtp"
    bridge.config["rtp_local_port"] = port
    bridge.config["rtp_host_ip"] = "127.0.0.1"

    async def scenario():
        await bridge.start_midi_input()
        first_thread = bridge.rtp_server_thread

        await bridge.restart_midi_input()

        assert bridge.rtp_server_thread is not None
        assert bridge.rtp_server_thread is not first_thread
        assert bridge.rtp_server_thread.is_alive()

        await bridge.stop_midi_input()

    asyncio.run(scenario())


def test_stop_midi_input_is_a_noop_when_nothing_is_running(bridge):
    async def scenario():
        await bridge.stop_midi_input()  # must not raise

    asyncio.run(scenario())


# ---- stop_midi_input: local MIDI ----

def test_stop_midi_input_closes_local_listener(bridge, monkeypatch):
    opened = {}
    closed = {"called": False}

    class _FakeMidiIn:
        def get_ports(self):
            return ["Fake Device"]

        def open_port(self, index):
            opened["index"] = index

        def ignore_types(self, **kwargs):
            pass

        def set_callback(self, cb):
            pass

        def close_port(self):
            closed["called"] = True

    monkeypatch.setattr(main.rtmidi, "MidiIn", _FakeMidiIn)
    bridge.config["midi_source"] = "Fake Device"

    async def scenario():
        await bridge.start_midi_input()
        assert bridge.local_midi_listener is not None

        await bridge.stop_midi_input()

        assert bridge.local_midi_listener is None
        assert closed["called"] is True

    asyncio.run(scenario())


# ---- scan_rtp_midi_network: listener bookkeeping ----

def test_rtp_midi_scan_listener_tracks_add_update_remove():
    listener = main._RtpMidiScanListener(zc=object())

    class _FakeInfo:
        port = 5004

        def parsed_addresses(self):
            return ["192.168.1.42"]

    class _FakeZeroconf:
        def get_service_info(self, service_type, name, timeout=2000):
            return _FakeInfo()

    fake_zc = _FakeZeroconf()
    listener.add_service(fake_zc, "_apple-midi._udp.local.", "Some Session._apple-midi._udp.local.")
    assert listener.found["Some Session._apple-midi._udp.local."] == {
        "name": "Some Session._apple-midi._udp.local.",
        "host": "192.168.1.42",
        "port": 5004,
    }

    listener.remove_service(fake_zc, "_apple-midi._udp.local.", "Some Session._apple-midi._udp.local.")
    assert "Some Session._apple-midi._udp.local." not in listener.found


def test_rtp_midi_scan_listener_ignores_service_with_no_info():
    listener = main._RtpMidiScanListener(zc=object())

    class _FakeZeroconf:
        def get_service_info(self, service_type, name, timeout=2000):
            return None

    listener.add_service(_FakeZeroconf(), "_apple-midi._udp.local.", "Ghost._apple-midi._udp.local.")
    assert listener.found == {}


# ---- scan_rtp_midi_network: end-to-end against this bridge's own real zeroconf instance ----

def test_scan_rtp_midi_network_finds_a_session_advertised_on_the_same_zeroconf_instance(bridge):
    """Not mocked - registers a real service on the bridge's own Zeroconf instance and scans
    for it. mDNS is normally used across the network, but registering and browsing through the
    *same* local Zeroconf instance is a standard, well-supported way to verify the round trip
    without depending on real multicast network delivery."""
    port = _free_udp_port()
    bridge.config["rtp_session_name"] = "test-scan-session"
    bridge.config["rtp_local_port"] = port
    bridge.config["rtp_host_ip"] = "127.0.0.1"

    async def scenario():
        bridge.advertise_rtp_midi()
        try:
            results = await bridge.scan_rtp_midi_network(duration_s=2.0)
        finally:
            if bridge.service_info is not None:
                bridge.zeroconf.unregister_service(bridge.service_info)

        assert any("test-scan-session" in s["name"] for s in results)

    asyncio.run(scenario())
