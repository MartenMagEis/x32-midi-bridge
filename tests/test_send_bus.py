import asyncio

import main
from conftest import make_event


def test_set_send_bus_stores_velocity_as_bus_number(bridge):
    bridge.handle_channel_action({"action": "set_send_bus"}, make_event(velocity=10))
    assert bridge.active_send_bus == 10


def test_set_send_bus_clamps_to_valid_bus_range(bridge):
    bridge.handle_channel_action({"action": "set_send_bus"}, make_event(velocity=0))
    assert bridge.active_send_bus == 1  # clamped to CLASS_ADDRESS_INFO["bus"] min

    bridge.handle_channel_action({"action": "set_send_bus"}, make_event(velocity=127))
    assert bridge.active_send_bus == 16  # clamped to CLASS_ADDRESS_INFO["bus"] max


def test_active_send_bus_defaults_to_none(bridge):
    assert bridge.active_send_bus is None


def test_send_bus_placeholder_resolved_in_hybrid_single_channel_path(bridge):
    bridge.active_send_bus = 10
    action = {"path": "/ch/{active_channels}/mix/{active_send_bus}/on", "value": 1}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=2), False))
    assert bridge.sent == [("/ch/02/mix/10/on", [1])]


def test_send_bus_placeholder_resolved_in_group_mode(bridge):
    bridge.active_send_bus = 3
    bridge.class_selections["ch"] = [5, 6]
    action = {"path": "/ch/{active_channels}/mix/{active_send_bus}/on", "value": 1}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=127), False))
    assert sorted(bridge.sent) == sorted([
        ("/ch/05/mix/03/on", [1]),
        ("/ch/06/mix/03/on", [1]),
    ])


def test_send_bus_placeholder_defaults_to_bus_1_when_never_selected(bridge):
    action = {"path": "/ch/{active_channels}/mix/{active_send_bus}/on", "value": 1}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=2), False))
    assert bridge.sent == [("/ch/02/mix/01/on", [1])]


def test_end_to_end_mute_channel_2_send_to_bus_10_via_handle_midi_event(bridge):
    bridge.mappings = [
        {"name": "global_set_channel", "trigger": {"type": "note_on", "number": 62}, "action": "set_channel"},
        {"name": "global_add_channel", "trigger": {"type": "note_on", "number": 64}, "action": "add_channel"},
        {"name": "global_set_channel_class", "trigger": {"type": "note_on", "number": 65}, "action": "set_channel_class"},
        {"name": "global_set_send_bus", "trigger": {"type": "note_on", "number": 66}, "action": "set_send_bus"},
        {
            "name": "mute_send",
            "trigger": {"type": "note_on", "number": 80},
            "actions": [{"path": "/ch/{active_channels}/mix/{active_send_bus}/on", "value": 1}],
        },
    ]

    async def scenario():
        await bridge.handle_midi_event(make_event(number=66, velocity=10))  # send target -> bus 10
        await bridge.handle_midi_event(make_event(number=62, velocity=2))   # select channel 2
        await bridge.handle_midi_event(make_event(number=80, velocity=127))  # fire mute (group mode, uses selection)

    asyncio.run(scenario())

    assert bridge.sent == [("/ch/02/mix/10/on", [1])]


def test_undo_cache_pattern_matches_send_bus_placeholder(bridge):
    pattern = bridge._resolved_path_pattern("/ch/{active_channels}/mix/{active_send_bus}/on")
    assert pattern.match("/ch/02/mix/10/on")
    assert not pattern.match("/ch/02/mix/10/level")
