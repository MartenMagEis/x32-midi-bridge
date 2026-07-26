import asyncio

import main
from conftest import make_event


def test_relative_db_fixed_delta_raises_level(bridge):
    async def fake_query(path):
        return 0.75  # 0dB (unity), see FADER_CURVE_BREAKPOINTS
    bridge.query_osc_value = fake_query

    action = {"path": "/ch/{active_channels}/mix/fader", "value": "relative_db", "db_delta": 10}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False))
    # 0dB + 10dB = 10dB -> float 1.0 (top breakpoint)
    assert bridge.sent == [("/ch/05/mix/fader", [1.0])]


def test_relative_db_fixed_delta_lowers_level(bridge):
    async def fake_query(path):
        return 0.75  # 0dB
    bridge.query_osc_value = fake_query

    action = {"path": "/ch/{active_channels}/mix/fader", "value": "relative_db", "db_delta": -10}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False))
    assert bridge.sent == [("/ch/05/mix/fader", [0.5])]  # -10dB -> float 0.5


def test_relative_db_clamps_at_the_top():
    # Already near the top, +50dB must clamp to the curve's max (float 1.0), not overshoot.
    assert main.x32_db_to_float(main.x32_float_to_db(0.9) + 50) == main.FADER_CURVE_BREAKPOINTS[-1][0]


def test_relative_db_skips_sending_when_query_times_out(bridge):
    async def fake_query(path):
        return None
    bridge.query_osc_value = fake_query

    action = {"path": "/ch/{active_channels}/mix/fader", "value": "relative_db", "db_delta": 10}
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=5), False))
    # Unlike toggle (which has a safe on-value fallback), a failed query must
    # never guess a level - nothing gets sent at all.
    assert bridge.sent == []


def test_relative_db_still_hybrid_gated_like_a_fixed_value(bridge):
    # Fixed db_delta has no velocity conflict, same hybrid single/group rules as toggle.
    action = {"value": "relative_db", "db_delta": 10}
    assert bridge.is_hybrid_single_channel(50, action) is True
    assert bridge.is_hybrid_multi_channel(127, action) is True


def test_relative_db_velocity_scaled_delta(bridge):
    async def fake_query(path):
        return 0.75  # 0dB
    bridge.query_osc_value = fake_query
    bridge.class_selections["ch"] = [7]

    action = {
        "path": "/ch/{active_channels}/mix/fader",
        "value": "relative_db",
        "db_delta": "midi_value",
        "db_scale": {"max_velocity": 100, "max_db": 20},
    }
    # velocity 50 of max_velocity 100 -> half of max_db (20) -> +10dB -> float 1.0
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=50), False))
    assert bridge.sent == [("/ch/07/mix/fader", [1.0])]


def test_relative_db_velocity_scaled_delta_clamps_above_max_velocity(bridge):
    async def fake_query(path):
        return 0.75  # 0dB
    bridge.query_osc_value = fake_query
    bridge.class_selections["ch"] = [7]

    action = {
        "path": "/ch/{active_channels}/mix/fader",
        "value": "relative_db",
        "db_delta": "midi_value",
        "db_scale": {"max_velocity": 100, "max_db": 20},
    }
    # velocity 127 > max_velocity 100 -> clamped to the full max_db (20), not overshot
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=127), False))
    assert bridge.sent == [("/ch/07/mix/fader", [main.x32_db_to_float(20)])]


def test_relative_db_velocity_scaled_delta_uses_active_channels_group_not_hybrid_addressing(bridge):
    # A velocity-scaled delta "spends" the velocity on the dB amount, same as
    # a plain midi_value action - it must apply to the whole active_channels
    # selection, never single-channel-by-velocity addressing, even for a
    # velocity (50) that would normally pick a single channel for a fixed value.
    async def fake_query(path):
        return 0.75
    bridge.query_osc_value = fake_query
    bridge.class_selections["ch"] = [3, 4]

    action = {
        "path": "/ch/{active_channels}/mix/fader",
        "value": "relative_db",
        "db_delta": "midi_value",
        "db_scale": {"max_velocity": 100, "max_db": 20},
    }
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=50), False))
    sent_paths = sorted(path for path, _ in bridge.sent)
    assert sent_paths == ["/ch/03/mix/fader", "/ch/04/mix/fader"]


def test_relative_db_velocity_scaled_delta_handles_zero_max_velocity(bridge):
    async def fake_query(path):
        return 0.75  # 0dB
    bridge.query_osc_value = fake_query
    bridge.class_selections["ch"] = [7]

    action = {
        "path": "/ch/{active_channels}/mix/fader",
        "value": "relative_db",
        "db_delta": "midi_value",
        "db_scale": {"max_velocity": 0, "max_db": 20},
    }
    asyncio.run(bridge.execute_mapping_action(action, make_event(velocity=100), False))
    # max_velocity 0 -> no sensible scale -> 0dB delta, not a ZeroDivisionError
    assert bridge.sent == [("/ch/07/mix/fader", [0.75])]
