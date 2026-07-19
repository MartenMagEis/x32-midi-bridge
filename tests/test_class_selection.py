import asyncio

import main
from conftest import make_event


def test_default_active_class_is_ch(bridge):
    assert bridge.active_class == "ch"


def test_set_channel_class_switches_active_class(bridge):
    bridge.handle_channel_action({"action": "set_channel_class"}, make_event(velocity=2))
    assert bridge.active_class == "bus"
    bridge.handle_channel_action({"action": "set_channel_class"}, make_event(velocity=6))
    assert bridge.active_class == "dca"


def test_set_channel_class_falls_back_to_ch_for_unknown_velocity(bridge):
    bridge.handle_channel_action({"action": "set_channel_class"}, make_event(velocity=99))
    assert bridge.active_class == "ch"


def test_switching_class_does_not_clear_other_classes_selection(bridge):
    # Build a mixed selection: channel 5, then switch to bus and add bus 3,
    # then switch to dca and add dca 2 - each switch must leave the
    # previously-built selections of other classes untouched.
    bridge.handle_channel_action({"action": "add_channel"}, make_event(velocity=5))
    bridge.handle_channel_action({"action": "set_channel_class"}, make_event(velocity=2))  # -> bus
    bridge.handle_channel_action({"action": "add_channel"}, make_event(velocity=3))
    bridge.handle_channel_action({"action": "set_channel_class"}, make_event(velocity=6))  # -> dca
    bridge.handle_channel_action({"action": "add_channel"}, make_event(velocity=2))

    assert bridge.class_selections == {"ch": [5], "bus": [3], "dca": [2]}


def test_set_channel_only_resets_the_currently_active_class(bridge):
    bridge.handle_channel_action({"action": "add_channel"}, make_event(velocity=5))  # ch: [5]
    bridge.handle_channel_action({"action": "set_channel_class"}, make_event(velocity=2))  # -> bus
    bridge.handle_channel_action({"action": "add_channel"}, make_event(velocity=3))  # bus: [3]
    bridge.handle_channel_action({"action": "add_channel"}, make_event(velocity=7))  # bus: [3, 7]

    bridge.handle_channel_action({"action": "set_channel"}, make_event(velocity=1))  # exclusive reset of bus only

    assert bridge.class_selections["ch"] == [5]  # untouched
    assert bridge.class_selections["bus"] == [1]  # reset + replaced


def test_end_to_end_mixed_mute_via_handle_midi_event(bridge_with_mappings):
    bridge = bridge_with_mappings
    mappings = [
        {"name": "global_set_channel", "trigger": {"type": "note_on", "number": 62}, "action": "set_channel"},
        {"name": "global_add_channel", "trigger": {"type": "note_on", "number": 64}, "action": "add_channel"},
        {"name": "global_set_channel_class", "trigger": {"type": "note_on", "number": 65}, "action": "set_channel_class"},
        {
            "name": "generic_mute",
            "trigger": {"type": "note_on", "number": 80},
            "save_state": False,
            "actions": [{"path": "/{active_class}/{active_channels}/mix/on", "value": 1}],
        },
    ]
    bridge.mappings = mappings

    async def scenario():
        await bridge.handle_midi_event(make_event(number=64, velocity=5))   # add ch 5
        await bridge.handle_midi_event(make_event(number=65, velocity=2))   # class -> bus
        await bridge.handle_midi_event(make_event(number=64, velocity=3))   # add bus 3
        await bridge.handle_midi_event(make_event(number=65, velocity=6))   # class -> dca
        await bridge.handle_midi_event(make_event(number=64, velocity=2))   # add dca 2
        await bridge.handle_midi_event(make_event(number=80, velocity=127))  # fire generic mute (group)

    asyncio.run(scenario())

    assert sorted(bridge.sent) == sorted([
        ("/ch/05/mix/on", [1]),
        ("/bus/03/mix/on", [1]),
        ("/dca/2/mix/on", [1]),
    ])


def test_legacy_default_mappings_are_unaffected_by_class_selection(bridge_with_mappings):
    # The project's real, shipped midi_osc_mappings.json only uses hardcoded
    # /ch/ paths - firing them must behave exactly as before the class
    # selection feature existed, no matter what active_class currently is.
    bridge = bridge_with_mappings
    bridge.active_class = "dca"

    asyncio.run(bridge.handle_midi_event(make_event(number=67, velocity=100)))  # vocal_send_mute

    assert bridge.sent == [("/ch/32/mix/01/on", [1])]
