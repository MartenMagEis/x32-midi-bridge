"""Standalone, throwaway helper for live-verifying FADER_CURVE_BREAKPOINTS
against a real X32 - not part of the bridge itself, not committed/shipped.

Usage:
    uv run python verify_fader_curve.py <x32_ip> [channel]

Polls a channel's fader value once a second and prints both the raw OSC
float and our computed dB (via x32_float_to_db) - move the physical fader
and compare the printed dB against the console's own screen/meter readout.
Ctrl+C to stop.
"""
import socket
import sys
import time

from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder

from main import x32_float_to_db

X32_PORT = 10023


def query_fader(sock: socket.socket, ip: str, path: str) -> float | None:
    builder = OscMessageBuilder(address=path)
    sock.sendto(builder.build().dgram, (ip, X32_PORT))
    sock.settimeout(0.3)
    try:
        data, _ = sock.recvfrom(4096)
    except socket.timeout:
        return None
    msg = OscMessage(data)
    return msg.params[0] if msg.params else None


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <x32_ip> [channel=1]")
        sys.exit(1)
    ip = sys.argv[1]
    channel = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    path = f"/ch/{channel:02d}/mix/fader"

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", 0))

    print(f"Polling {path} on {ip}:{X32_PORT} - move the fader and compare with the console display. Ctrl+C to stop.")
    try:
        while True:
            value = query_fader(sock, ip, path)
            if value is None:
                print("  (no reply - check IP/network)")
            else:
                print(f"  float={value:.4f}  ->  our dB={x32_float_to_db(value):+.1f}")
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
