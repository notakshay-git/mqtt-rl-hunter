"""Violation validator: re-verifies each violation TYPE the env can record,
using canonical minimal sequences with 3s timeouts against a fresh amqtt
broker (port 18893).  Writes results/violation_validation.json.
Only CONFIRMED verdicts may be cited as findings in RESULTS.md."""
import socket, subprocess, sys, time, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "envs"))
import mqtt_packets as P

PORT, CFG = 18893, "/tmp/amqtt_repro.yaml"

def read(s, t=3.0):
    s.settimeout(t)
    try:
        d = s.recv(64)
        return ("CLOSED(EOF)", b"") if d == b"" else ("DATA", d)
    except socket.timeout:
        return ("SILENT", None)
    except ConnectionResetError:
        return ("CLOSED(RST)", None)

def conn():
    return socket.create_connection(("127.0.0.1", PORT), timeout=3)

verdicts = {}

# V1/V4: malformed CONNECT (bad protocol level) -> expect CONNACK rc=0x01 + close
s = conn(); s.sendall(P.connect_malformed()); st, d = read(s)
st2, _ = read(s, 1.0); s.close()
ok_reject = st == "DATA" and d is not None and d[:4] == bytes.fromhex("20020001")
closed = st2.startswith("CLOSED")
verdicts["V1_open_after_malformed_connect"] = {
    "confirmed": not (ok_reject and closed),
    "observed": f"first read: {st} {d.hex() if d else ''}; second read: {st2}",
    "expected_if_compliant": "CONNACK 0x20020001 then close [MQTT-3.1.2-2]"}
verdicts["V4_connack_ok_after_malformed"] = {
    "confirmed": st == "DATA" and d is not None and d[:4] == bytes.fromhex("20020000"),
    "observed": f"first read: {st} {d.hex() if d else ''}",
    "expected_if_compliant": "no CONNACK rc=0"}

# V2: second CONNECT on an established session -> expect disconnect
s = conn(); s.sendall(P.connect()); st1, d1 = read(s)
s.sendall(P.connect(client_id="rl-dup")); st2, d2 = read(s); s.close()
accepted = st1 == "DATA" and d1 is not None and d1[:4] == bytes.fromhex("20020000")
verdicts["V2_open_after_second_connect"] = {
    "confirmed": accepted and st2 not in ("CLOSED(EOF)", "CLOSED(RST)"),
    "observed": f"first CONNECT: {st1} {d1.hex() if d1 else ''}; second CONNECT: {st2} {d2.hex() if d2 else ''}",
    "expected_if_compliant": "second CONNECT -> disconnect [MQTT-3.1.0-2]"}

# V3: SUBSCRIBE as first packet -> expect no SUBACK (ideally disconnect)
s = conn(); s.sendall(P.subscribe()); st, d = read(s); s.close()
got_suback = st == "DATA" and d is not None and len(d) > 0 and (d[0] >> 4) == 9
verdicts["V3_suback_before_connect"] = {
    "confirmed": got_suback,
    "observed": f"SUBSCRIBE-first: {st} {d.hex() if d else ''}",
    "expected_if_compliant": "no SUBACK before CONNECT; disconnect preferred"}

os.makedirs("results", exist_ok=True)
out = {"broker": "amqtt 0.12.1", "port": PORT, "read_timeout_s": 3.0,
       "verdicts": verdicts,
       "confirmed": [k for k, v in verdicts.items() if v["confirmed"]]}
with open("results/violation_validation.json", "w") as f:
    json.dump(out, f, indent=2)
print(json.dumps(out, indent=2))
