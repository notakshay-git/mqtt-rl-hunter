"""Minimal raw MQTT 3.1.1/5 packet builders - full control over bytes,
including deliberately malformed packets."""
import struct


def _remaining_length(n):
    out = b""
    while True:
        d = n % 128
        n //= 128
        if n > 0:
            d |= 0x80
        out += bytes([d])
        if n == 0:
            return out


def _str(s):
    b = s.encode() if isinstance(s, str) else s
    return struct.pack("!H", len(b)) + b


def connect(client_id="rl-hunter", keepalive=60, clean=True,
            proto_level=4, proto_name="MQTT"):
    flags = 0x02 if clean else 0x00
    vh = _str(proto_name) + bytes([proto_level, flags]) + \
        struct.pack("!H", keepalive)
    payload = _str(client_id)
    body = vh + payload
    return b"\x10" + _remaining_length(len(body)) + body


def connect_malformed(client_id="rl-hunter"):
    # Bad protocol level (0x63) - broker must reject and close
    return connect(client_id=client_id, proto_level=0x63)


def subscribe(packet_id=1, topic="rl/test", qos=0):
    body = struct.pack("!H", packet_id) + _str(topic) + bytes([qos])
    return b"\x82" + _remaining_length(len(body)) + body


def subscribe_malformed(packet_id=1):
    # Empty topic filter - protocol violation
    body = struct.pack("!H", packet_id) + _str("") + bytes([0])
    return b"\x82" + _remaining_length(len(body)) + body


def publish(topic="rl/test", payload=b"x", qos=0):
    body = _str(topic) + payload
    return bytes([0x30 | (qos << 1)]) + _remaining_length(len(body)) + body


def publish_oversized(topic="rl/test", size=2_000_000):
    return publish(topic=topic, payload=b"A" * size)


def disconnect():
    return b"\xe0\x00"


def auth_v5():
    # MQTT5 AUTH packet (0xF0) on a v3.1.1 connection - unexpected type
    return b"\xf0\x02\x00\x00"


def garbage():
    return b"\xff\xff\xde\xad\xbe\xef"
