import asyncio

import main
from conftest import make_event


def test_is_hybrid_single_channel_excludes_group_velocities(bridge):
    assert bridge.is_hybrid_single_channel(1, {"value": 1}) is True
    assert bridge.is_hybrid_single_channel(126, {"value": 1}) is True
    assert bridge.is_hybrid_single_channel(0, {"value": 1}) is False
    assert bridge.is_hybrid_single_channel(127, {"value": 1}) is False


def test_is_hybrid_single_channel_disabled_for_dynamic_value(bridge):
    assert bridge.is_hybrid_single_channel(50, {"value": "midi_value"}) is False


def test_is_hybrid_multi_channel_group_velocities(bridge):
    assert bridge.is_hybrid_multi_channel(127, {"value": 1}) is True
    assert bridge.is_hybrid_multi_channel(1, {"value": 1}) is False
    # Velocity 0 is still "group" at this level - the note_on/note_off
    # ambiguity is resolved earlier, in build_midi_event(), by normalizing a
    # velocity-0 note_on into a note_off before it ever reaches this check.
    # For control_change, a value of 0 is unambiguous and legitimately means
    # "group", so this function must not special-case it away.
    assert bridge.is_hybrid_multi_channel(0, {"value": 1}) is True


def test_handle_channel_action_set_channel_clamps_to_1_32(bridge):
    bridge.handle_channel_action({"action": "set_channel"}, make_event(velocity=200))
    assert bridge.class_selections["ch"] == [main.CHANNEL_MAX]

    bridge.handle_channel_action({"action": "set_channel"}, make_event(velocity=0))
    assert bridge.class_selections["ch"] == [main.CHANNEL_MIN]


def test_handle_channel_action_add_channel_is_additive_and_deduped(bridge):
    bridge.handle_channel_action({"action": "set_channel"}, make_event(velocity=3))
    bridge.handle_channel_action({"action": "add_channel"}, make_event(velocity=5))
    bridge.handle_channel_action({"action": "add_channel"}, make_event(velocity=3))  # duplicate, ignored
    assert bridge.class_selections["ch"] == [3, 5]


def test_execute_mapping_action_legacy_ch_path_uses_two_digit_padding(bridge):
    action = {"path": "/ch/{active_channels}/mix/01/on", "value": 1}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False))
    assert bridge.sent == [("/ch/05/mix/01/on", [1])]


def test_execute_mapping_action_legacy_path_clamps_to_32_regardless_of_active_class(bridge):
    # A hardcoded /ch/ path (no {active_class} placeholder) must ignore
    # whatever class is currently selected via set_channel_class - this is
    # what keeps every pre-existing mapping unaffected by the new feature.
    bridge.active_class = "dca"
    action = {"path": "/ch/{active_channels}/mix/01/on", "value": 1}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=100), False))
    assert bridge.sent == [("/ch/32/mix/01/on", [1])]


def test_execute_mapping_action_active_class_path_uses_per_class_padding(bridge):
    bridge.active_class = "dca"
    action = {"path": "/{active_class}/{active_channels}/mix/on", "value": 1}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False))
    assert bridge.sent == [("/dca/5/mix/on", [1])]  # no zero-padding for dca


def test_execute_mapping_action_active_class_path_clamps_per_class_range(bridge):
    bridge.active_class = "bus"  # range 1-16
    action = {"path": "/{active_class}/{active_channels}/mix/on", "value": 1}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=90), False))
    assert bridge.sent == [("/bus/16/mix/on", [1])]


def test_send_to_active_channels_dynamic_value_uses_ch_selection_only(bridge):
    bridge.class_selections["ch"] = [3, 4]
    action = {"path": "/ch/{active_channels}/mix/pan", "value": 0.5}
    asyncio.run(bridge.send_to_active_channels("/ch/{active_channels}/mix/pan", action, make_event()))
    assert bridge.sent == [("/ch/03/mix/pan", [0.5]), ("/ch/04/mix/pan", [0.5])]


def test_send_to_active_channels_defaults_to_channel_1_when_empty(bridge):
    action = {"path": "/ch/{active_channels}/mix/pan", "value": 0.5}
    asyncio.run(bridge.send_to_active_channels("/ch/{active_channels}/mix/pan", action, make_event()))
    assert bridge.sent == [("/ch/01/mix/pan", [0.5])]
    assert bridge.class_selections["ch"] == [1]  # sticky default, matches pre-existing behavior


def test_send_to_active_channels_active_class_path_covers_every_populated_class(bridge):
    bridge.class_selections["ch"] = [5]
    bridge.class_selections["bus"] = [3]
    bridge.class_selections["dca"] = [2]
    action = {"path": "/{active_class}/{active_channels}/mix/on", "value": 1}
    asyncio.run(bridge.send_to_active_channels("/{active_class}/{active_channels}/mix/on", action, make_event()))
    assert sorted(bridge.sent) == sorted([
        ("/ch/05/mix/on", [1]),
        ("/bus/03/mix/on", [1]),
        ("/dca/2/mix/on", [1]),
    ])
