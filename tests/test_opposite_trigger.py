import asyncio

import main
from conftest import make_event


def test_toggle_forced_on_sends_on_value_without_query(bridge):
    queried = []

    async def fake_query(path):
        queried.append(path)
        return 0.0  # would normally mean "currently off" - must be ignored when forced

    bridge.query_osc_value = fake_query

    action = {"path": "/ch/{active_channels}/mix/01/on", "value": "toggle"}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False, toggle_forced=True))

    assert bridge.sent == [("/ch/05/mix/01/on", [1])]
    assert queried == []  # deterministic mode never queries the console


def test_toggle_forced_off_sends_off_value_without_query(bridge):
    async def fake_query(path):
        raise AssertionError("must not query when toggle_forced is set")

    bridge.query_osc_value = fake_query

    action = {"path": "/ch/{active_channels}/mix/01/on", "value": "toggle"}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False, toggle_forced=False))

    assert bridge.sent == [("/ch/05/mix/01/on", [0])]


def test_toggle_forced_respects_custom_on_off_values(bridge):
    action = {
        "path": "/ch/{active_channels}/mix/01/on",
        "value": "toggle",
        "toggle_on_value": 100,
        "toggle_off_value": 10,
    }
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False, toggle_forced=True))
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False, toggle_forced=False))

    assert bridge.sent == [("/ch/05/mix/01/on", [100]), ("/ch/05/mix/01/on", [10])]


def test_no_opposite_trigger_keeps_query_based_toggle_via_handle_midi_event(bridge):
    # Without opposite_trigger configured, firing the same note twice must still
    # behave exactly like the pre-existing single-note toggle (query-based).
    queried = []

    async def fake_query(path):
        queried.append(path)
        return 0.0

    bridge.query_osc_value = fake_query
    bridge.mappings = [
        {
            "name": "fx_mute",
            "trigger": {"type": "note_on", "number": "72"},
            "actions": [{"path": "/config/mute/3", "value": "toggle"}],
        }
    ]

    asyncio.run(bridge.handle_midi_event(make_event(number=72, velocity=100)))

    assert bridge.sent == [("/config/mute/3", [1])]
    assert queried == ["/config/mute/3"]


def test_opposite_trigger_note_sends_off_value_deterministically(bridge):
    async def fake_query(path):
        raise AssertionError("must not query the console once opposite_trigger is configured")

    bridge.query_osc_value = fake_query
    bridge.mappings = [
        {
            "name": "fx_mute",
            "trigger": {"type": "note_on", "number": "72"},
            "opposite_trigger": {"type": "note_on", "number": "73"},
            "actions": [{"path": "/config/mute/3", "value": "toggle"}],
        }
    ]

    async def scenario():
        await bridge.handle_midi_event(make_event(number=72, velocity=100))  # primary -> on
        await bridge.handle_midi_event(make_event(number=73, velocity=100))  # opposite -> off
        await bridge.handle_midi_event(make_event(number=72, velocity=100))  # primary again -> on (not "the other one")

    asyncio.run(scenario())

    assert bridge.sent == [
        ("/config/mute/3", [1]),
        ("/config/mute/3", [0]),
        ("/config/mute/3", [1]),
    ]


def test_opposite_trigger_respects_custom_on_off_values_end_to_end(bridge):
    bridge.mappings = [
        {
            "name": "fx_mute",
            "trigger": {"type": "note_on", "number": "72"},
            "opposite_trigger": {"type": "note_on", "number": "73"},
            "actions": [
                {
                    "path": "/config/mute/3",
                    "value": "toggle",
                    "toggle_on_value": "OFF",
                    "toggle_off_value": "ON",
                }
            ],
        }
    ]

    asyncio.run(bridge.handle_midi_event(make_event(number=73, velocity=100)))

    assert bridge.sent == [("/config/mute/3", ["ON"])]


def test_opposite_trigger_does_not_affect_non_toggle_actions(bridge):
    # A mapping with opposite_trigger but a plain fixed-value action should just
    # fire that fixed value from either note - toggle_forced only changes
    # behavior for "value": "toggle" actions (see _resolve_action_value).
    bridge.mappings = [
        {
            "name": "fx_something",
            "trigger": {"type": "note_on", "number": "72"},
            "opposite_trigger": {"type": "note_on", "number": "73"},
            "actions": [{"path": "/config/mute/3", "value": 5}],
        }
    ]

    asyncio.run(bridge.handle_midi_event(make_event(number=73, velocity=100)))

    assert bridge.sent == [("/config/mute/3", [5])]


def test_find_opposite_mapping(bridge):
    mapping = {
        "name": "m",
        "trigger": {"type": "note_on", "number": "72"},
        "opposite_trigger": {"type": "note_on", "number": "73"},
    }
    bridge.mappings = [mapping]

    assert bridge.find_opposite_mapping(make_event(number=73)) is mapping
    assert bridge.find_opposite_mapping(make_event(number=72)) is None
    assert bridge.find_opposite_mapping(make_event(number=1)) is None


def test_normalize_mappings_resolves_opposite_trigger_note_names():
    mappings = [
        {
            "name": "m",
            "trigger": {"type": "note_on", "number": "C4"},
            "opposite_trigger": {"type": "note_on", "number": "C#4"},
        }
    ]
    main.normalize_mappings(mappings)
    assert mappings[0]["opposite_trigger"]["number"] == str(main.note_name_to_midi_number("C#4"))
