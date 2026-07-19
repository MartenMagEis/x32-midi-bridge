import asyncio
from unittest.mock import MagicMock, patch

import main


def test_build_midi_event_normalizes_velocity_zero_note_on(bridge):
    event = main.build_midi_event(bridge, "note_on", 67, 0, "peer")
    assert event.type == "note_off"
    assert event.velocity == 0
    assert event.number == "67"


def test_build_midi_event_leaves_real_note_on_alone(bridge):
    event = main.build_midi_event(bridge, "note_on", 67, 100, "peer")
    assert event.type == "note_on"
    assert event.velocity == 100


def test_build_midi_event_leaves_real_note_off_alone(bridge):
    event = main.build_midi_event(bridge, "note_off", 67, 64, "peer")
    assert event.type == "note_off"
    assert event.velocity == 64


def test_build_midi_event_velocity_zero_control_change_is_untouched(bridge):
    # Only note_on/note_off carry the note-off-as-velocity-0 ambiguity - a CC
    # value of 0 is an ordinary, unambiguous controller value.
    event = main.build_midi_event(bridge, "control_change", 10, 0, "peer")
    assert event.type == "control_change"
    assert event.velocity == 0


def test_build_midi_event_logs_velocity_zero_normalization_only_once(bridge):
    assert bridge._warned_velocity_zero_note_on is False
    main.build_midi_event(bridge, "note_on", 1, 0, "peer")
    assert bridge._warned_velocity_zero_note_on is True
    # Second occurrence must not raise or misbehave - flag stays set.
    main.build_midi_event(bridge, "note_on", 2, 0, "peer")
    assert bridge._warned_velocity_zero_note_on is True


class _FakeParams:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _FakeCommand:
    def __init__(self, command, **params):
        self.command = command
        self.params = _FakeParams(**params)


def test_bridge_midi_handler_translates_note_on(bridge):
    handler = main._BridgeMidiHandler(bridge, loop=None)
    event = handler._translate("peer1", _FakeCommand("note_on", key=60, velocity=100))
    assert event.type == "note_on"
    assert event.number == "60"
    assert event.velocity == 100
    assert event.peer == "peer1"


def test_bridge_midi_handler_translates_note_on_velocity_zero_to_note_off(bridge):
    handler = main._BridgeMidiHandler(bridge, loop=None)
    event = handler._translate("peer1", _FakeCommand("note_on", key=60, velocity=0))
    assert event.type == "note_off"


def test_bridge_midi_handler_translates_control_change(bridge):
    handler = main._BridgeMidiHandler(bridge, loop=None)
    event = handler._translate("peer1", _FakeCommand("control_mode_change", controller=10, value=42))
    assert event.type == "control_change"
    assert event.number == "10"
    assert event.velocity == 42


def test_bridge_midi_handler_ignores_unsupported_command(bridge):
    handler = main._BridgeMidiHandler(bridge, loop=None)
    event = handler._translate("peer1", _FakeCommand("pitch_bend", value=8192))
    assert event is None


def test_local_midi_listener_opens_and_translates_messages(bridge):
    fake_midi_in = MagicMock()
    fake_midi_in.get_ports.return_value = ["Fake Device 0"]

    with patch.object(main.rtmidi, "MidiIn", return_value=fake_midi_in):

        async def scenario():
            loop = asyncio.get_running_loop()
            listener = main._LocalMidiListener(bridge, loop, "Fake Device 0")
            listener.start()

            fake_midi_in.open_port.assert_called_once_with(0)
            fake_midi_in.set_callback.assert_called_once()

            listener._on_message(([0x90, 60, 100], 0.0))  # note_on
            listener._on_message(([0x90, 60, 0], 0.0))    # note_on vel=0 -> note_off
            listener._on_message(([0x80, 60, 64], 0.0))   # real note_off
            listener._on_message(([0xB0, 10, 5], 0.0))    # control_change
            listener._on_message(([0xE0, 0, 64], 0.0))    # pitch bend - ignored

            await asyncio.sleep(0.01)
            events = []
            while not bridge.event_queue.empty():
                events.append(bridge.event_queue.get_nowait())

            assert [e.type for e in events] == ["note_on", "note_off", "note_off", "control_change"]
            assert events[0].peer == "local:Fake Device 0"

            listener.stop()
            fake_midi_in.close_port.assert_called_once()

        asyncio.run(scenario())


def test_local_midi_listener_raises_for_unknown_device(bridge):
    fake_midi_in = MagicMock()
    fake_midi_in.get_ports.return_value = ["Some Other Device"]

    with patch.object(main.rtmidi, "MidiIn", return_value=fake_midi_in):
        async def scenario():
            listener = main._LocalMidiListener(bridge, asyncio.get_running_loop(), "Nonexistent Device")
            try:
                listener.start()
                assert False, "expected RuntimeError"
            except RuntimeError as exc:
                assert "Nonexistent Device" in str(exc)
            assert listener.midi_in is None

        asyncio.run(scenario())
