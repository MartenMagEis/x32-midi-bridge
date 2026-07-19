import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import main


@pytest.fixture
def bridge():
    """A bare X32MidiBridge with no real network I/O: send_osc_message is
    replaced with a recorder so tests can assert on what would have been
    sent, without touching a real X32 or socket."""
    b = main.X32MidiBridge(config={}, mappings=[])
    sent = []

    async def fake_send(path, args):
        sent.append((path, list(args)))

    b.send_osc_message = fake_send
    b.sent = sent
    return b


@pytest.fixture
def bridge_with_mappings():
    """Same as `bridge`, but loaded with the project's real, shipped
    midi_osc_mappings.json - useful for tests that want to exercise the
    actual default mapping set (set_channel/add_channel/set_channel_class
    plus the example OSC-action mappings)."""
    mappings = main.load_json(main.MAPPINGS_FILE)
    b = main.X32MidiBridge(config={}, mappings=mappings)
    sent = []

    async def fake_send(path, args):
        sent.append((path, list(args)))

    b.send_osc_message = fake_send
    b.sent = sent
    return b


def make_event(type_="note_on", number="60", velocity=100):
    return main.MidiEvent(type=type_, number=str(number), velocity=velocity, timestamp=0.0, peer="test", raw=None)
