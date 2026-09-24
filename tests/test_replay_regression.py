"""Regression tests for the replay VERDICT logic against a fresh broker
(port 18893). These lock in the run's central finding:

  [OPEN_TCP, SUBSCRIBE, CONNECT_MALFORMED]      -> V1 CONFIRMED
      (non-CONNECT first packet wedges amqtt's init_from_connect parse;
       the later malformed CONNECT is met with silence + open socket)
  [OPEN_TCP, CONNECT_MALFORMED]                 -> V1 REJECTED (canonical
       single-packet probe: amqtt answers CONNACK rc=0x01 and closes)
  [OPEN_TCP, CONNECT_VALID, CONNECT_MALFORMED]  -> V1 REJECTED (session
       established; broker closes on the bad second packet)

Both the 'real' and the 'false positive' conclusions were wrong at
different depths earlier in this project; these tests make the correct
verdicts executable.
"""
import os, subprocess, sys, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "repro"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import replay_candidates as R

PORT = 18893
CFG = "/tmp/amqtt_repro_test.yaml"


def V1(seq):
    return {"violation": "V1_open_after_malformed_connect",
            "sequence": seq, "action": "CONNECT_MALFORMED"}


class TestReplayVerdicts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg_src = "/tmp/amqtt_rl_18883.yaml"
        base = open(cfg_src).read() if os.path.exists(cfg_src) else None
        if base is None:
            from envs.mqtt_env import broker_config
            base = broker_config(18883)
        with open(CFG, "w") as f:
            f.write(base.replace("18883", str(PORT)).replace("18884", str(PORT + 1)))
        cls.proc = subprocess.Popen(
            [sys.executable, "envs/broker_runner.py", CFG],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid)
        import socket
        for _ in range(75):
            try:
                s = socket.create_connection(("127.0.0.1", PORT), timeout=0.5)
                s.close()
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("test broker failed to start")

    @classmethod
    def tearDownClass(cls):
        try:
            os.killpg(os.getpgid(cls.proc.pid), 9)
        except Exception:
            pass

    def test_known_context_sequence_confirms(self):
        ok, note = R.check(V1(["OPEN_TCP", "SUBSCRIBE"]), port=PORT)
        self.assertTrue(ok, f"must CONFIRM, got: {note}")

    def test_canonical_single_packet_rejects(self):
        ok, note = R.check(V1(["OPEN_TCP"]), port=PORT)
        self.assertFalse(ok, f"must REJECT, got: {note}")

    def test_after_valid_connect_rejects(self):
        ok, note = R.check(V1(["OPEN_TCP", "CONNECT_VALID"]), port=PORT)
        self.assertFalse(ok, f"must REJECT, got: {note}")


if __name__ == "__main__":
    unittest.main()
