"""Unit tests for the single shared MQTT response classifier."""
import os, socket, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from envs.mqtt_classify import RESP, RESP_NAMES, classify_head, read_resp


class FakeSocket:
    def __init__(self, script):
        self.script = list(script)
        self.timeout = None

    def settimeout(self, t):
        self.timeout = t

    def recv(self, n):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestClassifyHead(unittest.TestCase):
    def test_connack_ok(self):
        self.assertEqual(classify_head(b"\x20\x02\x00\x00"), RESP["CONNACK_OK"])

    def test_connack_err(self):
        for rc in (1, 2, 5):
            self.assertEqual(classify_head(bytes([0x20, 0x02, 0x00, rc])),
                             RESP["CONNACK_ERR"])

    def test_suback(self):
        self.assertEqual(classify_head(b"\x90\x03\x00\x01\x00"), RESP["SUBACK"])

    def test_pingresp(self):
        self.assertEqual(classify_head(b"\xd0\x00"), RESP["PINGRESP"])

    def test_eof_is_closed(self):
        self.assertEqual(classify_head(b""), RESP["CLOSED_BY_BROKER"])

    def test_unknown_type(self):
        self.assertEqual(classify_head(b"\x40\x02\x00\x01"), RESP["OTHER"])

    def test_every_code_has_a_name(self):
        for code in RESP.values():
            self.assertIn(code, RESP_NAMES)


class TestReadResp(unittest.TestCase):
    def test_timeout_means_silence_not_close(self):
        s = FakeSocket([socket.timeout()])
        self.assertEqual(read_resp(s, 0.1), RESP["NONE"])

    def test_oserror_means_closed(self):
        s = FakeSocket([ConnectionResetError()])
        self.assertEqual(read_resp(s, 0.1), RESP["CLOSED_BY_BROKER"])

    def test_none_socket_is_error(self):
        self.assertEqual(read_resp(None, 0.1), RESP["ERROR"])

    def test_reset_timeout_restored(self):
        s = FakeSocket([b"\x20\x02\x00\x00"])
        self.assertEqual(read_resp(s, 1.5, reset_timeout=0.1),
                         RESP["CONNACK_OK"])
        self.assertEqual(s.timeout, 0.1)


if __name__ == "__main__":
    unittest.main()
