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

def test_validate_mappings_accepts_the_real_shipped_mappings():
    mappings = main.load_json(main.MAPPINGS_FILE)
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
                assert body["restart_required_for"] == ["rtp_local_port"]
                assert bridge.config["rtp_local_port"] == 5005
                assert bridge.config["log_level"] == "DEBUG"

    asyncio.run(scenario())


def test_put_config_rejects_invalid_body():
    bridge = _FakeBridge({"web_enabled": True})

    async def scenario():
        app = _build_app(bridge)
        async with TestClient(TestServer(app)) as client:
            resp = await client.put("/api/config", json={"x32_port": "nope"})
            assert resp.status == 400

    asyncio.run(scenario())
