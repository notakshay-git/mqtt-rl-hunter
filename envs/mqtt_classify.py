"""THE one MQTT response classifier, shared by the fuzz env AND the replay
validator.  Round-1 architect review: env and replay each had a hand-synced
copy, so the verifier could check a different predicate than the detector.
Now there is a single source of truth for response classification."""
import socket

RESP = {"NONE": 0, "CONNACK_OK": 1, "CONNACK_ERR": 2, "SUBACK": 3,
        "PINGRESP": 4, "CLOSED_BY_BROKER": 5, "ERROR": 6, "OTHER": 7}
RESP_NAMES = {v: k for k, v in RESP.items()}


def classify_head(head):
    """Classify the first 4 bytes of an MQTT control packet response."""
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


def read_resp(sock, timeout, reset_timeout=None):
    """Read one response head from sock within `timeout` s and classify it.

    timeout          -> RESP.NONE means silence with the socket still open
    EOF/reset/OSError -> RESP.CLOSED_BY_BROKER
    reset_timeout    -> if given, restore this socket timeout afterwards
    """
    if sock is None:
        return RESP["ERROR"]
    try:
        sock.settimeout(timeout)
        return classify_head(sock.recv(4))
    except socket.timeout:
        return RESP["NONE"]
    except OSError:
        return RESP["CLOSED_BY_BROKER"]
    finally:
        if reset_timeout is not None:
            try:
                sock.settimeout(reset_timeout)
            except OSError:
                pass
