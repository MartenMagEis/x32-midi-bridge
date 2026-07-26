import main


def test_float_to_db_matches_breakpoints_exactly():
    for value, db in main.FADER_CURVE_BREAKPOINTS:
        assert main.x32_float_to_db(value) == db


def test_db_to_float_matches_breakpoints_exactly():
    for value, db in main.FADER_CURVE_BREAKPOINTS:
        assert main.x32_db_to_float(db) == value


def test_float_to_db_interpolates_within_a_segment():
    # Midpoint of the 0.5 (-10dB) .. 0.75 (0dB) segment
    assert main.x32_float_to_db(0.625) == -5.0


def test_round_trip_within_tolerance():
    for value in (0.1, 0.2, 0.4, 0.6, 0.8, 0.9):
        db = main.x32_float_to_db(value)
        assert abs(main.x32_db_to_float(db) - value) < 1e-9


def test_float_to_db_clamps_out_of_range_input():
    assert main.x32_float_to_db(-0.5) == main.FADER_CURVE_BREAKPOINTS[0][1]
    assert main.x32_float_to_db(1.5) == main.FADER_CURVE_BREAKPOINTS[-1][1]


def test_db_to_float_clamps_out_of_range_input():
    assert main.x32_db_to_float(-200) == main.FADER_CURVE_BREAKPOINTS[0][0]
    assert main.x32_db_to_float(50) == main.FADER_CURVE_BREAKPOINTS[-1][0]


def test_curve_is_monotonically_increasing():
    # Both directions must never go "backwards" - a real fader law never dips.
    values = [i / 100.0 for i in range(0, 101)]
    dbs = [main.x32_float_to_db(v) for v in values]
    assert dbs == sorted(dbs)
