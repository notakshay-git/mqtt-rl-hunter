"""MQTT broker state-machine hunting environment (the real target).

Drives a LIVE amqtt broker subprocess over raw TCP. The agent picks
MQTT-flavored operations (valid/malformed/sequenced); rewards fire on
framework-level violations of the MQTT spec and on broker crashes.

Violations hunted:
  V1 broker leaves TCP open after malformed CONNECT (must close)
  V2 broker leaves TCP open after a second CONNECT on one connection
  V3 SUBACK before any successful CONNECT (subscribe pre-auth accepted)
  V4 CONNACK success after malformed CONNECT
  CRASH broker process dies / port stops accepting (+100, terminal)
"""
import gymnasium as gym
from gymnasium import spaces
import numpy as np
import socket, subprocess, time, os, sys, signal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from envs import mqtt_packets as P

ACTIONS = ["OPEN_TCP", "CONNECT_VALID", "CONNECT_MALFORMED", "CONNECT_DUP",
           "AUTH_PACKET", "SUBSCRIBE", "SUBSCRIBE_MALFORMED", "PUBLISH",
           "PUBLISH_OVERSIZED", "DISCONNECT", "GARBAGE", "CLOSE_TCP"]
(OPEN_TCP, CONNECT_VALID, CONNECT_MALFORMED, CONNECT_DUP, AUTH_PACKET,
 SUBSCRIBE, SUBSCRIBE_MALFORMED, PUBLISH, PUBLISH_OVERSIZED, DISCONNECT,
 GARBAGE, CLOSE_TCP) = range(12)

RESP = {"NONE": 0, "CONNACK_OK": 1, "CONNACK_ERR": 2, "SUBACK": 3,
        "PINGRESP": 4, "CLOSED_BY_BROKER": 5, "ERROR": 6, "OTHER": 7}
MAX_STEPS = 60
PORT = 18883

BROKER_CONFIG = """\
listeners:
  default:
    type: tcp
    bind: 127.0.0.1:%d
  ws:
    type: ws
    bind: 127.0.0.1:%d
    max_connections: 10
sys_interval: 0
auth:
  allow-anonymous: true
""" % (PORT, PORT + 1)


class MQTTFuzzEnv(gym.Env):
    metadata = {"name": "mqtt-amqtt-v1"}

    def __init__(self, novelty_reward=True, novelty_store=None,
                 broker_start_timeout=15.0):
        super().__init__()
        self.action_space = spaces.Discrete(12)
        # obs: [tcp_open, mqtt_connected, subscribed, last_resp/8,
        #       broker_alive, steps/max, n_opens/8, n_connects/8]
        self.observation_space = spaces.Box(low=0.0, high=1.0, shape=(8,),
                                            dtype=np.float32)
        self.novelty_reward = novelty_reward
        self.store = novelty_store if novelty_store is not None else {
            "states": set(), "edges": set(), "seqs": set(),
            "crashes": [], "violations": []}
        self._cfg_path = "/tmp/amqtt_rl.yaml"
        with open(self._cfg_path, "w") as f:
            f.write(BROKER_CONFIG)
        self._broker_timeout = broker_start_timeout
        self._start_broker()

    # ----------------------------------------------------- broker mgmt
    def _start_broker(self):
        self._broker = subprocess.Popen(
            [sys.executable, os.path.join(os.path.dirname(__file__), "broker_runner.py"), self._cfg_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid)
        t0 = time.time()
        while time.time() - t0 < self._broker_timeout:
            if self._broker.poll() is not None:
                break
            try:
                s = socket.create_connection(("127.0.0.1", PORT), timeout=0.5)
                s.close()
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("broker failed to start")

    def _broker_alive(self):
        # Ground truth = the broker process we spawned. poll() first: a dead
        # process is a real crash. The port probe is retried so a transient
        # connect failure under load is not misread as broker death.
        if self._broker.poll() is not None:
            return False
        for _ in range(3):
            try:
                s = socket.create_connection(("127.0.0.1", PORT), timeout=0.5)
                s.close()
                return True
            except OSError:
                time.sleep(0.2)
        return False

    def _kill_broker(self):
        try:
            os.killpg(os.getpgid(self._broker.pid), signal.SIGKILL)
        except Exception:
            pass
        try:
            self._broker.wait(timeout=3)
        except Exception:
            pass

    def close(self):
        self._kill_broker()
        self._close_sock()

    # --------------------------------------------------------- socket
    def _close_sock(self):
        if getattr(self, "_sock", None):
            try:
                self._sock.close()
            except Exception:
                pass
        self._sock = None

    def _open_sock(self):
        self._close_sock()
        try:
            self._sock = socket.create_connection(("127.0.0.1", PORT),
                                                  timeout=2.0)
            self._sock.settimeout(0.1)
            return True
        except OSError:
            self._sock = None
            return False

    def _send_recv(self, data):
        """Returns RESP class for the broker's response."""
        if self._sock is None:
            return RESP["ERROR"]
        try:
            self._sock.sendall(data)
        except OSError:
            return RESP["CLOSED_BY_BROKER"]
        try:
            head = self._sock.recv(4)
            if not head:
                return RESP["CLOSED_BY_BROKER"]
            ptype = head[0] >> 4
            if ptype == 2:  # CONNACK
                rc = head[3] if len(head) >= 4 else 99
                return RESP["CONNACK_OK"] if rc == 0 else RESP["CONNACK_ERR"]
            if ptype == 9:
                return RESP["SUBACK"]
            if ptype == 13:
                return RESP["PINGRESP"]
            return RESP["OTHER"]
        except socket.timeout:
            return RESP["NONE"]
        except OSError:
            return RESP["CLOSED_BY_BROKER"]

    # ------------------------------------------------------------ gym
    @property
    def state(self):
        return (self._tcp_open, self._mqtt_connected, self._subscribed,
                self._last_resp, self._broker_ok)

    def _obs(self):
        return np.array([self._tcp_open, self._mqtt_connected,
                         self._subscribed, self._last_resp / 8.0,
                         self._broker_ok, self._steps / MAX_STEPS,
                         min(self._n_opens, 8) / 8.0,
                         min(self._n_connects, 8) / 8.0],
                        dtype=np.float32)

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        if not self._broker_alive():
            self._kill_broker()
            self._start_broker()
        self._broker_ok = True
        self._close_sock()
        self._tcp_open = 0
        self._mqtt_connected = 0
        self._subscribed = 0
        self._last_resp = RESP["NONE"]
        self._steps = 0
        self._n_opens = 0
        self._n_connects = 0
        self._path = []
        return self._obs(), {"state": self.state}

    def step(self, action):
        a = int(action)
        prev = self.state
        reward = 0.0
        info = {"valid": True}
        new_violations = []

        if a == OPEN_TCP:
            ok = self._open_sock()
            self._tcp_open = 1 if ok else 0
            self._n_opens += 1
            if not ok:
                # broker not accepting -> crash suspected
                if not self._broker_alive():
                    info["crash"] = True
            self._last_resp = RESP["NONE"]
        elif a in (CONNECT_VALID, CONNECT_MALFORMED, CONNECT_DUP,
                   AUTH_PACKET, SUBSCRIBE, SUBSCRIBE_MALFORMED, PUBLISH,
                   PUBLISH_OVERSIZED, DISCONNECT, GARBAGE):
            if self._sock is None:
                info["valid"] = False
                reward -= 0.2
                self._last_resp = RESP["ERROR"]
            else:
                was_connected = self._mqtt_connected
                if a == CONNECT_VALID:
                    r = self._send_recv(P.connect())
                    self._n_connects += 1
                    if r == RESP["CONNACK_OK"]:
                        self._mqtt_connected = 1
                elif a == CONNECT_MALFORMED:
                    r = self._send_recv(P.connect_malformed())
                    if r == RESP["CONNACK_OK"]:
                        new_violations.append("V4_connack_ok_after_malformed")
                    elif r in (RESP["NONE"],):
                        # tolerated malformed CONNECT, conn still open
                        new_violations.append("V1_open_after_malformed_connect")
                elif a == CONNECT_DUP:
                    r = self._send_recv(P.connect(client_id="rl-dup"))
                    if r != RESP["CLOSED_BY_BROKER"]:
                        # spec: second CONNECT must close the connection
                        if r in (RESP["CONNACK_OK"], RESP["NONE"]):
                            new_violations.append(
                                "V2_open_after_second_connect")
                elif a == AUTH_PACKET:
                    r = self._send_recv(P.auth_v5())
                elif a == SUBSCRIBE:
                    r = self._send_recv(P.subscribe())
                    if r == RESP["SUBACK"]:
                        self._subscribed = 1
                        if not was_connected:
                            new_violations.append(
                                "V3_suback_before_connect")
                elif a == SUBSCRIBE_MALFORMED:
                    r = self._send_recv(P.subscribe_malformed())
                elif a == PUBLISH:
                    r = self._send_recv(P.publish())
                elif a == PUBLISH_OVERSIZED:
                    r = self._send_recv(P.publish_oversized())
                elif a == DISCONNECT:
                    r = self._send_recv(P.disconnect())
                    self._mqtt_connected = 0
                    self._subscribed = 0
                else:
                    r = self._send_recv(P.garbage())
                self._last_resp = r
        elif a == CLOSE_TCP:
            self._close_sock()
            self._tcp_open = 0
            self._mqtt_connected = 0
            self._subscribed = 0
            self._last_resp = RESP["NONE"]

        self._steps += 1
        self._path.append((prev, a))
        self._broker_ok = 1 if self._broker_alive() else 0

        terminated = False
        if not self._broker_ok and not info.get("crash"):
            # Only count as crash if the broker died under our traffic
            if self._tcp_open or self._n_connects > 0:
                info["crash"] = True

        if info.get("crash"):
            reward += 100.0
            terminated = True
            self.store["crashes"].append({
                "episode_step": self._steps,
                "sequence": [ACTIONS[x[1]] for x in self._path]})
        for v in new_violations:
            if v not in self.store["violations"]:
                self.store["violations"].append(v)
                reward += 25.0
                info.setdefault("new_violations", []).append(v)

        nxt = self.state
        if self.novelty_reward:
            if nxt not in self.store["states"]:
                reward += 2.0
            if (prev, a, nxt) not in self.store["edges"]:
                reward += 1.0
        self.store["states"].add(nxt)
        self.store["edges"].add((prev, a, nxt))
        tail = tuple(x[1] for x in self._path[-6:])
        self.store["seqs"].add(tail)

        info["edge"] = (prev, a, nxt)
        truncated = self._steps >= MAX_STEPS
        return self._obs(), reward, terminated, truncated, info
