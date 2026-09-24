"""Unit tests for the raw MQTT packet builders."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from envs import mqtt_packets as P


class TestRemainingLength(unittest.TestCase):
    def test_one_byte(self):
        self.assertEqual(P._remaining_length(0), b"\x00")
        self.assertEqual(P._remaining_length(127), b"\x7f")

    def test_two_bytes(self):
        self.assertEqual(P._remaining_length(128), b"\x80\x01")
        self.assertEqual(P._remaining_length(300), b"\xac\x02")

    def test_roundtrip_boundary(self):
        # 16383 -> 2 bytes max in MQTT; check the encoding math holds
        enc = P._remaining_length(16383)
        self.assertEqual(enc, b"\xff\x7f")


class TestConnect(unittest.TestCase):
    def test_structure(self):
        pkt = P.connect(client_id="abc", keepalive=60)
        self.assertEqual(pkt[0], 0x10)
        body = pkt[2:]
        self.assertIn(b"\x00\x04MQTT", body)
        self.assertIn(bytes([4, 0x02]), body)          # v3.1.1, clean session
        self.assertTrue(body.endswith(b"\x00\x03abc")) # client id

    def test_malformed_level(self):
        pkt = P.connect_malformed()
        self.assertIn(bytes([0x63]), pkt)              # bad protocol level
        self.assertNotIn(bytes([4, 0x02]), pkt)


class TestOthers(unittest.TestCase):
    def test_subscribe_malformed_empty_topic(self):
        pkt = P.subscribe_malformed()
        self.assertEqual(pkt[0], 0x82)
        self.assertIn(b"\x00\x00\x00", pkt)  # zero-length topic + qos byte

    def test_disconnect(self):
        self.assertEqual(P.disconnect(), b"\xe0\x00")

    def test_publish_oversized_size(self):
        pkt = P.publish_oversized(size=100_000)
        self.assertGreater(len(pkt), 100_000)


if __name__ == "__main__":
    unittest.main()
