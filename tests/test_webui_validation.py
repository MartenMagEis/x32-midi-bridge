import asyncio
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import main
import webui


# ---- _validate_config ----

def test_validate_config_accepts_a_well_formed_config():
    config = {
        "x32_ip": "auto",
        "x32_port": 10023,
        "midi_source": "rtp",
        "rtp_session_name": "x32-midi-bridge",
        "rtp_host_ip": "auto",
        "rtp_local_port": 5004,
        "allowed_peers": [],
        "double_send": False,
        "undo_timeout_ms": 100,
        "verify_delay_ms": 50,
        "discovery_interval_s": 5,
        "log_level": "INFO",
        "web_enabled": True,
        "web_host": "0.0.0.0",
        "web_port": 8090,
    }
    assert webui._validate_config(config) == []


def test_validate_config_rejects_wrong_types():
    errors = webui._validate_config({"x32_port": "not-a-number"})
    assert any("x32_port" in e for e in errors)


def test_validate_config_rejects_out_of_range_ports():
    errors = webui._validate_config({"x32_port": 70000})
    assert any("x32_port" in e for e in errors)


def test_validate_config_rejects_invalid_log_level():
    errors = webui._validate_config({"log_level": "VERBOSE"})
    assert any("log_level" in e for e in errors)


def test_validate_config_accepts_float_discovery_interval():
    assert webui._validate_config({"discovery_interval_s": 2.5}) == []


# ---- _validate_mappings ----

def test_validate_mappings_accepts_the_shipped_example_mappings():
    mappings = main.load_json(main.MAPPINGS_EXAMPLE_FILE)
    assert webui._validate_mappings(mappings) == []


def test_validate_mappings_flags_missing_trigger():
    errors = webui._validate_mappings([{"name": "broken", "action": "set_channel"}])
    assert any("missing 'trigger'" in e for e in errors)


def test_validate_mappings_flags_invalid_trigger_type():
    mapping = {"name": "m", "trigger": {"type": "bogus", "number": 60}}
    errors = webui._validate_mappings([mapping])
    assert any("type" in e for e in errors)


def test_validate_mappings_flags_unresolvable_note_name():
    mapping = {"name": "m", "trigger": {"type": "note_on", "number": "not-a-note"}}
    errors = webui._validate_mappings([mapping])
    assert any("not a valid MIDI number" in e for e in errors)


def test_validate_mappings_flags_duplicate_triggers_across_mappings():
    mappings = [
        {"name": "a", "trigger": {"type": "note_on", "number": 60}},
        {"name": "b", "trigger": {"type": "note_on", "number": 60}},
    ]
    errors = webui._validate_mappings(mappings)
    assert any("wird mehrfach verwendet" in e for e in errors)


def test_validate_mappings_flags_trigger_undo_trigger_collision_within_one_mapping():
    mappings = [
        {
            "name": "a",
            "trigger": {"type": "note_on", "number": 60},
            "undo_trigger": {"type": "note_on", "number": 60},
        },
    ]
    errors = webui._validate_mappings(mappings)
    assert any("wird mehrfach verwendet" in e for e in errors)


def test_validate_mappings_accepts_opposite_trigger():
    mappings = [
        {
            "name": "fx_mute",
            "trigger": {"type": "note_on", "number": 72},
            "opposite_trigger": {"type": "note_on", "number": 73},
            "actions": [{"path": "/config/mute/3", "value": "toggle"}],
        },
    ]
    assert webui._validate_mappings(mappings) == []


def test_validate_mappings_flags_trigger_opposite_trigger_collision():
    mappings = [
        {
            "name": "a",
            "trigger": {"type": "note_on", "number": 60},
            "opposite_trigger": {"type": "note_on", "number": 60},
        },
    ]
    errors = webui._validate_mappings(mappings)
    assert any("wird mehrfach verwendet" in e for e in errors)


def test_validate_mappings_flags_opposite_trigger_collision_across_mappings():
    mappings = [
        {"name": "a", "trigger": {"type": "note_on", "number": 60}},
        {"name": "b", "trigger": {"type": "note_on", "number": 61}, "opposite_trigger": {"type": "note_on", "number": 60}},
    ]
    errors = webui._validate_mappings(mappings)
    assert any("wird mehrfach verwendet" in e for e in errors)


# ---- PUT /api/config: web_enabled lockout ----

class _FakeBridge:
    def __init__(self, config):
        self.config = config


def _build_app(bridge):
    app = web.Application()
    app["bridge"] = bridge
    webui._add_routes(app)
    return app


def test_put_config_cannot_disable_web_enabled(tmp_path):
    bridge = _FakeBridge({"web_enabled": True, "log_level": "INFO"})
    config_path = tmp_path / "system_config.json"

    async def scenario():
        with patch.object(main, "CONFIG_FILE", config_path):
            app = _build_app(bridge)
            async with TestClient(TestServer(app)) as client:
                resp = await client.put("/api/config", json={"web_enabled": False, "log_level": "INFO"})
                assert resp.status == 200
                body = await resp.json()
                assert body["web_enabled_locked"] is True
                assert bridge.config["web_enabled"] is True

    asyncio.run(scenario())
    assert config_path.exists()
    assert '"web_enabled": true' in config_path.read_text(encoding="utf-8")


def test_put_config_reports_restart_required_keys(tmp_path):
    bridge = _FakeBridge({"web_enabled": True, "web_port": 8090, "log_level": "INFO"})
    config_path = tmp_path / "system_config.json"

    async def scenario():
        with patch.object(main, "CONFIG_FILE", config_path):
            app = _build_app(bridge)
            async with TestClient(TestServer(app)) as client:
                resp = await client.put(
                    "/api/config",
                    json={"web_enabled": True, "web_port": 9090, "log_level": "DEBUG"},
                )
                assert resp.status == 200
                body = await resp.json()
                assert body["restart_required_for"] == ["web_port"]
                assert bridge.config["web_port"] == 9090
                assert bridge.config["log_level"] == "DEBUG"

    asyncio.run(scenario())


def test_put_config_reports_midi_input_restart_required_keys(tmp_path):
    # rtp_local_port (and midi_source/rtp_host_ip/rtp_session_name) no longer need a full
    # bridge restart - see X32MidiBridge.restart_midi_input() - but the web UI still needs to
    # know they changed so it can offer the lightweight MIDI-input-restart action.
    bridge = _FakeBridge({"web_enabled": True, "rtp_local_port": 5004, "log_level": "INFO"})
    config_path = tmp_path / "system_config.json"

    async def scenario():
        with patch.object(main, "CONFIG_FILE", config_path):
            app = _build_app(bridge)
            async with TestClient(TestServer(app)) as client:
                resp = await client.put(
                    "/api/config",
                    json={"web_enabled": True, "rtp_local_port": 5005, "log_level": "DEBUG"},
                )
                assert resp.status == 200
                body = await resp.json()
                assert body["restart_required_for"] == []
                assert body["midi_input_restart_required_for"] == ["rtp_local_port"]
                assert bridge.config["rtp_local_port"] == 5005

    asyncio.run(scenario())


def test_put_config_rejects_invalid_body():
    bridge = _FakeBridge({"web_enabled": True})

    async def scenario():
        app = _build_app(bridge)
        async with TestClient(TestServer(app)) as client:
            resp = await client.put("/api/config", json={"x32_port": "nope"})
            assert resp.status == 400

    asyncio.run(scenario())


# ---- POST /api/midi-input/restart ----

class _FakeBridgeWithMidiInputControl(_FakeBridge):
    def __init__(self, config, restart_should_fail=False):
        super().__init__(config)
        self.restart_called = False
        self._restart_should_fail = restart_should_fail

    async def restart_midi_input(self):
        self.restart_called = True
        if self._restart_should_fail:
            raise RuntimeError("boom")

    def get_midi_input_status(self):
        return "RTP-MIDI server listening; no peers connected"

    async def scan_rtp_midi_network(self, duration_s=4.0):
        return [{"name": "Other Session", "host": "192.168.1.5", "port": 5004}]


def test_restart_midi_input_endpoint_calls_bridge_and_reports_status():
    bridge = _FakeBridgeWithMidiInputControl({"midi_source": "rtp"})

    async def scenario():
        app = _build_app(bridge)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/api/midi-input/restart")
            assert resp.status == 200
            body = await resp.json()
            assert body["ok"] is True
            assert "RTP-MIDI" in body["midi_input_status"]
            assert bridge.restart_called is True

    asyncio.run(scenario())


def test_restart_midi_input_endpoint_reports_failure_as_500():
    bridge = _FakeBridgeWithMidiInputControl({"midi_source": "rtp"}, restart_should_fail=True)

    async def scenario():
        app = _build_app(bridge)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/api/midi-input/restart")
            assert resp.status == 500

    asyncio.run(scenario())


# ---- POST /api/midi-input/scan ----

def test_scan_rtp_midi_endpoint_returns_discovered_sessions():
    bridge = _FakeBridgeWithMidiInputControl({"midi_source": "rtp"})

    async def scenario():
        app = _build_app(bridge)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/api/midi-input/scan")
            assert resp.status == 200
            body = await resp.json()
            assert body["sessions"] == [{"name": "Other Session", "host": "192.168.1.5", "port": 5004}]

    asyncio.run(scenario())
