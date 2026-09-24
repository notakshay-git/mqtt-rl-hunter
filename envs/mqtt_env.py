"""MQTT broker state-machine hunting environment (the real target).

Drives a LIVE amqtt broker subprocess over raw TCP. The agent picks
MQTT-flavored operations (valid/malformed/sequenced); rewards fire on
framework-level violations of the MQTT spec and on broker crashes.

Violation CANDIDATES hunted (each flags only after a 1.5s confirmation
read, so a slow-but-compliant broker under load is not misread as silence;
every candidate must then survive replay verification against a fresh broker
before it counts as a finding, and there is deliberately NO reward for
violation flags - unverified flags are reward-hacking bait; verified against
amqtt 0.12.1 source, see repro/repro_violations.py):
  V1 malformed CONNECT: no CONNACK at all and connection still open after
     confirmation ([MQTT-3.1.2-2] requires CONNACK rc=0x01 then close)
  V2 second CONNECT on an ALREADY-CONNECTED socket answered with CONNACK_OK
     or silence instead of disconnect ([MQTT-3.1.0-2])
  V3 SUBACK received with no prior successful CONNECT on this socket
  V4 CONNACK success after malformed CONNECT
  CRASH broker process dies / port stops accepting (+100, terminal)
"""
import gymnasium as gym
from gymnasium import spaces
import numpy as np
import socket, subprocess, time, os, sys, signal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from envs import mqtt_packets as P
from envs.mqtt_classify import RESP, RESP_NAMES, read_resp as _shared_read

ACTIONS = ["OPEN_TCP", "CONNECT_VALID", "CONNECT_MALFORMED", "CONNECT_DUP",
           "AUTH_PACKET", "SUBSCRIBE", "SUBSCRIBE_MALFORMED", "PUBLISH",
           "PUBLISH_OVERSIZED", "DISCONNECT", "GARBAGE", "CLOSE_TCP"]
(OPEN_TCP, CONNECT_VALID, CONNECT_MALFORMED, CONNECT_DUP, AUTH_PACKET,
 SUBSCRIBE, SUBSCRIBE_MALFORMED, PUBLISH, PUBLISH_OVERSIZED, DISCONNECT,
 GARBAGE, CLOSE_TCP) = range(12)

MAX_STEPS = 60
PORT = 18883  # default only; pass port= to run parallel envs on other ports

def broker_config(port):
    return """\
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
""" % (port, port + 1)


class MQTTFuzzEnv(gym.Env):
    metadata = {"name": "mqtt-amqtt-v1"}

    def __init__(self, novelty_reward=True, novelty_store=None,
                 broker_start_timeout=15.0, port=PORT, config_path=None):
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
        self.port = port
        self._cfg_path = config_path or "/tmp/amqtt_rl_%d.yaml" % port
        with open(self._cfg_path, "w") as f:
            f.write(broker_config(port))
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
                s = socket.create_connection(("127.0.0.1", self.port), timeout=0.5)
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
                s = socket.create_connection(("127.0.0.1", self.port), timeout=0.5)
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
            self._sock = socket.create_connection(("127.0.0.1", self.port),
                                                  timeout=2.0)
            self._sock.settimeout(0.1)
            return True
        except OSError:
            self._sock = None
            return False

    def _read_resp(self, timeout):
        """Read and classify one 4-byte response head within `timeout` s.

        Classification lives in envs/mqtt_classify.py - the SAME module the
        replay validator uses, so detector and verifier cannot diverge."""
        return _shared_read(self._sock, timeout, reset_timeout=0.1)

    def _send_recv(self, data, timeout=0.1):
        """Send bytes, return RESP class for the broker's response."""
        if self._sock is None:
            return RESP["ERROR"]
        try:
            self._sock.sendall(data)
        except OSError:
            return RESP["CLOSED_BY_BROKER"]
        return self._read_resp(timeout)

    def _flag(self, new_violations, name, action, resp):
        """Record a violation with evidence (action, response, broker load).

        Every flag carries the context needed to re-verify it later, so no
        claimed finding is ever a bare string."""
        new_violations.append(name)
        try:
            fds = len(os.listdir(f"/proc/{self._broker.pid}/fd"))
        except Exception:
            fds = -1
        self.store.setdefault("violation_events", []).append({
            "violation": name, "episode_step": self._steps,
            "action": ACTIONS[action], "resp": resp,
            "wall": round(time.time(), 1), "broker_fds": fds,
            "sequence": [ACTIONS[x[1]] for x in self._path]})

    def _confirm_read(self):
        """Long (1.5s) confirmation read before any violation may flag.

        The 0.1s base timeout keeps throughput high, but a broker under load
        can take longer than 0.1s to answer.  Every violation path confirms
        with this read first so slow-but-compliant responses (e.g. amqtt's
        CONNACK rc=0x01 + close after a bad protocol level) are never
        misread as silence."""
        return self._read_resp(1.5)

    # ------------------------------------------------ DoS / hang oracle
    def _probe_broker_health(self):
        """Episode-start health probe: time a fresh CONNECT->CONNACK round
        trip on a side connection and sample the broker fd count.  A broker
        that is ALIVE but degraded (fd exhaustion, wedged handlers, pinned
        CPU) shows up here as a slow/failed probe - the process-death crash
        oracle alone misses that whole DoS class (we watched amqtt sit at
        375+ CLOSE-WAIT fds with CPU pinned while still alive)."""
        if self._broker.poll() is not None:
            return
        t0 = time.time()
        resp = RESP["ERROR"]
        try:
            s = socket.create_connection(("127.0.0.1", self.port), timeout=2.0)
            s.sendall(P.connect(client_id="rl-health"))
            resp = _shared_read(s, 2.0)
            s.close()
        except OSError:
            pass
        rtt_ms = (time.time() - t0) * 1000.0
        try:
            fds = len(os.listdir("/proc/%d/fd" % self._broker.pid))
        except Exception:
            fds = -1
        self.store["broker_fds_max"] = max(
            self.store.get("broker_fds_max", 0), fds)
        self.store["probe_rtt_max_ms"] = max(
            self.store.get("probe_rtt_max_ms", 0.0), rtt_ms)
        if resp != RESP["CONNACK_OK"] or rtt_ms > 2000.0:
            self.store.setdefault("degraded", []).append({
                "episode": self._episodes, "resp": RESP_NAMES[resp],
                "rtt_ms": round(rtt_ms, 1), "broker_fds": fds,
                "wall": round(time.time(), 1)})

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
        self._episodes = getattr(self, "_episodes", 0) + 1
        if not self._broker_alive() or self._episodes % 250 == 0:
            self._kill_broker()
            self._start_broker()
        self._broker_ok = True
        self._close_sock()
        self._probe_broker_health()
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
                    if r == RESP["NONE"]:
                        r = self._confirm_read()
                    if r == RESP["CONNACK_OK"]:
                        self._flag(new_violations, "V4_connack_ok_after_malformed", a, r)
                    elif r == RESP["NONE"]:
                        # no CONNACK of any kind even after 1.5s, conn open
                        self._flag(new_violations, "V1_open_after_malformed_connect", a, r)
                    # CONNACK_ERR (rc=0x01) or CLOSED_BY_BROKER = spec-compliant
                elif a == CONNECT_DUP:
                    # A valid CONNECT with a different client id.  V2 only
                    # applies when a session was ALREADY established on this
                    # socket; otherwise this is just a first connect.
                    r = self._send_recv(P.connect(client_id="rl-dup"))
                    if r == RESP["NONE"] and was_connected:
                        r = self._confirm_read()
                    if r == RESP["CONNACK_OK"]:
                        if was_connected:
                            # spec [MQTT-3.1.0-2]: second CONNECT must close
                            self._flag(new_violations,
                                       "V2_open_after_second_connect", a, r)
                        else:
                            self._mqtt_connected = 1
                    elif r == RESP["NONE"] and was_connected:
                        # connected session, second CONNECT met with silence
                        # and an open connection instead of a disconnect
                        self._flag(new_violations,
                                   "V2_open_after_second_connect", a, r)
                    elif r == RESP["CLOSED_BY_BROKER"] and was_connected:
                        # compliant disconnect; session is gone
                        self._mqtt_connected = 0
                        self._subscribed = 0
                elif a == AUTH_PACKET:
                    r = self._send_recv(P.auth_v5())
                elif a == SUBSCRIBE:
                    r = self._send_recv(P.subscribe())
                    if r == RESP["CONNACK_OK"]:
                        # delayed CONNACK from an earlier CONNECT: the broker
                        # session WAS established; our flag was stale
                        self._mqtt_connected = 1
                        was_connected = True
                        r = self._confirm_read()
                    if r == RESP["SUBACK"]:
                        self._subscribed = 1
                        if not was_connected:
                            self._flag(new_violations,
                                       "V3_suback_before_connect", a, r)
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
                if r == RESP["CONNACK_OK"]:
                    self._mqtt_connected = 1
                if r == RESP["CLOSED_BY_BROKER"]:
                    # broker tore the session down; keep our state honest
                    self._mqtt_connected = 0
                    self._subscribed = 0
                    self._close_sock()
                    self._tcp_open = 0
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
                info.setdefault("new_violations", []).append(v)
                # NOTE: no reward. Candidates are replay-verified offline
                # (repro/validate_violations.py) before counting as findings.

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
