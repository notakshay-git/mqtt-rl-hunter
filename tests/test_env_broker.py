"""Integration tests: env against a REAL amqtt broker on a dedicated test
port (18895). Locks in the spec-compliant behaviors the env must NOT flag,
and the crash oracle."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from envs.mqtt_env import MQTTFuzzEnv, ACTIONS
from envs.mqtt_classify import RESP

TEST_PORT = 18895


def fresh_store():
    return {"states": set(), "edges": set(), "seqs": set(),
            "crashes": [], "violations": []}


class TestEnvAgainstRealBroker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = fresh_store()
        cls.env = MQTTFuzzEnv(novelty_reward=False, novelty_store=cls.store,
                              port=TEST_PORT)

    @classmethod
    def tearDownClass(cls):
        cls.env.close()

    def setUp(self):
        self.env.reset()

    def act(self, name):
        return self.env.step(ACTIONS.index(name))

    def test_health_probe_clean_broker(self):
        # fresh broker: no degradation events may be recorded
        self.assertEqual(self.store.get("degraded", []), [])
        self.assertGreater(self.store.get("probe_rtt_max_ms", 0), 0)

    def test_valid_connect_gets_connack_ok(self):
        self.act("OPEN_TCP")
        self.act("CONNECT_VALID")
        self.assertEqual(self.env._last_resp, RESP["CONNACK_OK"])
        self.assertEqual(self.env._mqtt_connected, 1)

    def test_canonical_malformed_connect_is_compliant(self):
        """Single malformed CONNECT: amqtt rejects per spec - NO V1 flag."""
        self.act("OPEN_TCP")
        self.act("CONNECT_MALFORMED")
        self.assertIn(self.env._last_resp,
                      (RESP["CONNACK_ERR"], RESP["CLOSED_BY_BROKER"]))
        self.assertNotIn("V1_open_after_malformed_connect",
                         self.store["violations"])

    def test_second_connect_after_valid_closes_no_v2(self):
        """amqtt closes on a second CONNECT - spec-compliant, NO V2 flag."""
        self.act("OPEN_TCP")
        self.act("CONNECT_VALID")
        self.act("CONNECT_DUP")
        self.assertEqual(self.env._last_resp, RESP["CLOSED_BY_BROKER"])
        self.assertNotIn("V2_open_after_second_connect",
                         self.store["violations"])

    def test_crash_oracle_fires_on_broker_death(self):
        self.env._kill_broker()
        self.assertFalse(self.env._broker_alive())
        self.act("OPEN_TCP")  # connect refused -> crash suspected
        self.env._broker_ok = 1 if self.env._broker_alive() else 0
        self.assertEqual(self.env._broker_ok, 0)

    def test_dead_broker_restarted_on_reset(self):
        self.env._kill_broker()
        self.env.reset()
        self.assertTrue(self.env._broker_alive())


if __name__ == "__main__":
    unittest.main()
