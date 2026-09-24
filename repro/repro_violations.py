"""Standalone reproducers for V1-V3 against a fresh amqtt broker (port 18893).
Long (3s) read timeouts so slow responses are never misread as silence.
Starts and stops its own broker. Usage: python3 repro/repro_violations.py"""
import socket, subprocess, sys, time, os, signal
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "envs"))
import mqtt_packets as P

PORT = 18893
CFG = "/tmp/amqtt_repro.yaml"

def read(s, t=3.0):
    s.settimeout(t)
    try:
        d = s.recv(64)
        return "CLOSED(EOF)" if d == b"" else "0x" + d.hex()
    except socket.timeout:
        return "SILENT(3s, conn still open)"
    except ConnectionResetError:
        return "CLOSED(RST)"

def conn():
    return socket.create_connection(("127.0.0.1", PORT), timeout=3)

def start_broker():
    p = subprocess.Popen([sys.executable, "envs/broker_runner.py", CFG],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         preexec_fn=os.setsid)
    t0 = time.time()
    while time.time() - t0 < 10:
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=0.5); s.close()
            return p
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("repro broker failed to start")

print("== V1: malformed CONNECT (bad protocol level 0x63) ==")
print("   spec: MQTT 3.1.1 [MQTT-3.1.2-2] Server MUST send CONNACK rc=0x01 then close")
s = conn(); s.sendall(P.connect_malformed())
print("   after malformed CONNECT, broker replied:", read(s))
print("   conn still usable?", read(s, 1.0))
s.close()

print("== V2: second CONNECT on one connection ==")
print("   spec: MQTT 3.1.1 [MQTT-3.1.0-2] Server MUST treat second CONNECT as protocol violation and disconnect")
s = conn(); s.sendall(P.connect())
print("   first CONNECT reply:", read(s))
s.sendall(P.connect(client_id="rl-dup"))
print("   second CONNECT reply:", read(s))
s.close()

print("== V3: SUBSCRIBE before any CONNECT ==")
print("   spec: MQTT 3.1.1 [MQTT-3.1.0-1] first packet after TCP connect MUST be CONNECT; else disconnect")
s = conn(); s.sendall(P.subscribe())
print("   SUBSCRIBE-first reply:", read(s))
s.close()

print("== control: valid CONNECT ==")
s = conn(); s.sendall(P.connect())
print("   valid CONNECT reply:", read(s))
s.close()
