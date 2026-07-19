import asyncio

import main
from conftest import make_event


def test_toggle_sends_on_value_when_currently_off(bridge):
    async def fake_query(path):
        return 0.0
    bridge.query_osc_value = fake_query

    action = {"path": "/ch/{active_channels}/mix/01/on", "value": "toggle"}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False))
    assert bridge.sent == [("/ch/05/mix/01/on", [1])]


def test_toggle_sends_off_value_when_currently_on(bridge):
    async def fake_query(path):
        return 1.0
    bridge.query_osc_value = fake_query

    action = {"path": "/ch/{active_channels}/mix/01/on", "value": "toggle"}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False))
    assert bridge.sent == [("/ch/05/mix/01/on", [0])]


def test_toggle_respects_custom_on_off_values(bridge):
    async def fake_query(path):
        return 10  # closer to custom off_value (10) than on_value (100)
    bridge.query_osc_value = fake_query

    action = {
        "path": "/ch/{active_channels}/mix/01/on",
        "value": "toggle",
        "toggle_on_value": 100,
        "toggle_off_value": 10,
    }
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False))
    assert bridge.sent == [("/ch/05/mix/01/on", [100])]


def test_toggle_defaults_to_on_value_when_query_times_out(bridge):
    async def fake_query(path):
        return None
    bridge.query_osc_value = fake_query

    action = {"path": "/ch/{active_channels}/mix/01/on", "value": "toggle"}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False))
    assert bridge.sent == [("/ch/05/mix/01/on", [1])]


def test_toggle_works_across_group_selection(bridge):
    queried_paths = []

    async def fake_query(path):
        queried_paths.append(path)
        return 1.0 if path == "/ch/03/mix/01/on" else 0.0

    bridge.query_osc_value = fake_query
    bridge.class_selections["ch"] = [3, 4]

    action = {"path": "/ch/{active_channels}/mix/01/on", "value": "toggle"}
    # velocity 127 -> group mode, applies to every selected ch channel
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=127), False))

    assert sorted(bridge.sent) == sorted([
        ("/ch/03/mix/01/on", [0]),  # was on (1.0) -> toggles off
        ("/ch/04/mix/01/on", [1]),  # was off (0.0) -> toggles on
    ])
    assert sorted(queried_paths) == ["/ch/03/mix/01/on", "/ch/04/mix/01/on"]


def test_toggle_still_hybrid_gated_like_fixed_value(bridge):
    # A toggle action must be gated by the same hybrid single/multi rules as
    # a plain fixed value - it's a different "what value to send" strategy,
    # not a different channel-addressing mode.
    assert bridge.is_hybrid_single_channel(50, {"value": "toggle"}) is True
    assert bridge.is_hybrid_multi_channel(127, {"value": "toggle"}) is True
    assert bridge.is_hybrid_single_channel(50, {"value": "midi_value"}) is False
