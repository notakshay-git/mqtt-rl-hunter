"""Replay-verify recorded violation CANDIDATES against a fresh amqtt broker.

Takes a run results JSON (with violation_events containing full action
sequences), replays each candidate's exact episode action list over a raw
socket with 3s reads, and checks whether the claimed violation response
actually occurs at the flagged step.  Only replay-confirmed candidates may
be cited as findings.

Usage: python3 repro/replay_candidates.py results/mqtt_comparison_seed0.json
Writes <input>.replay.json"""
import socket, subprocess, sys, time, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "envs"))
import mqtt_packets as P
from mqtt_classify import RESP, RESP_NAMES, read_resp as _shared_read

PORT, CFG = 18893, "/tmp/amqtt_repro.yaml"
READ_T = 3.0
MAX_PER_TYPE = 20

def read_resp(s, t=READ_T):
    """(name, detail) wrapper over the SHARED classifier
    (envs/mqtt_classify.py) - verifier and detector classify identically."""
    r = _shared_read(s, t)
    name = RESP_NAMES[r]
    detail = {"NONE": "silent", "CLOSED_BY_BROKER": "reset/EOF"}.get(name, name)
    return (name, detail)

PACKETS = {
    "CONNECT_VALID": lambda: P.connect(),
    "CONNECT_MALFORMED": lambda: P.connect_malformed(),
    "CONNECT_DUP": lambda: P.connect(client_id="rl-dup"),
    "AUTH_PACKET": lambda: P.auth_v5(),
    "SUBSCRIBE": lambda: P.subscribe(),
    "SUBSCRIBE_MALFORMED": lambda: P.subscribe_malformed(),
    "PUBLISH": lambda: P.publish(),
    "PUBLISH_OVERSIZED": lambda: P.publish_oversized(),
    "DISCONNECT": lambda: P.disconnect(),
    "GARBAGE": lambda: P.garbage(),
}

def replay(seq, flag_idx, port=PORT):
    """Replay seq on one fresh socket; return resp observed at flag_idx."""
    s = None
    connected = False
    resp_at_flag = None
    try:
        for i, act in enumerate(seq):
            if act == "OPEN_TCP":
                if s is None:
                    try:
                        s = socket.create_connection(("127.0.0.1", port), timeout=3)
                    except OSError:
                        s = None
            elif act == "CLOSE_TCP":
                if s:
                    try: s.close()
                    except OSError: pass
                s = None; connected = False
            elif act in PACKETS:
                if s is None:
                    continue
                try:
                    s.sendall(PACKETS[act]())
                except OSError:
                    r = "CLOSED_BY_BROKER"
                else:
                    # fast reads mid-sequence (fresh broker answers in ms);
                    # long read only at the flag step, where it counts
                    r, det = read_resp(s, t=(READ_T if i == flag_idx else 0.3))
                if r == "CONNACK_OK":
                    connected = True
                if r == "CLOSED_BY_BROKER":
                    connected = False
                    try: s.close()
                    except OSError: pass
                    s = None
                if i == flag_idx:
                    resp_at_flag = (r, connected_before(act, connected, r))
            if i == flag_idx and act in ("OPEN_TCP", "CLOSE_TCP"):
                resp_at_flag = ("N/A", None)
    finally:
        if s:
            try: s.close()
            except OSError: pass
    return resp_at_flag

def connected_before(act, connected, r):
    """connected state BEFORE this action's response was processed."""
    if r == "CONNACK_OK" and act in ("CONNECT_VALID", "CONNECT_DUP"):
        return False if not connected else connected  # already updated; approximate
    return connected

def check(ev, port=PORT):
    """Return (confirmed, note)."""
    v = ev["violation"]; seq = ev["sequence"]
    # flag step = position of the flagged action = len(seq)-1 (flag fires on
    # the action appended last at flag time; env stores path BEFORE current
    # action, so the flagged action is ev['action'] at index len(seq))
    seq_full = seq + [ev["action"]]
    flag_idx = len(seq_full) - 1
    got = replay(seq_full, flag_idx, port=port)
    if not got or got[0] in (None, "N/A"):
        return (False, f"no response captured at flag step (got {got})")
    r, _ = got
    if v == "V1_open_after_malformed_connect":
        return (r == "NONE", f"replay resp at flag: {r}")
    if v == "V2_open_after_second_connect":
        return (r in ("CONNACK_OK", "NONE"), f"replay resp at flag: {r}")
    if v == "V3_suback_before_connect":
        return (r == "SUBACK", f"replay resp at flag: {r}")
    if v == "V4_connack_ok_after_malformed":
        return (r == "CONNACK_OK", f"replay resp at flag: {r}")
    return (False, "unknown violation type")

def main(path, port=PORT, cfg=CFG):
    data = json.load(open(path))
    report = {}
    runs = data["runs"] if "runs" in data else [data]
    results = []
    for run in runs:
        results.extend(run.get("results", []))
    if not results and "violation_events" in data:
        results = [data]
    for res in results:
        events = res.get("violation_events", [])
        per_type = {}
        for ev in events:
            per_type.setdefault(ev["violation"], []).append(ev)
        agent_rep = {}
        for vtype, evs in per_type.items():
            confirmed, tried = 0, 0
            notes = []
            for ev in evs[:MAX_PER_TYPE]:
                ok, note = check(ev, port=port)
                tried += 1
                confirmed += 1 if ok else 0
                if len(notes) < 5:
                    notes.append(("CONFIRMED " if ok else "rejected ") + note)
            agent_rep[vtype] = {"candidates": len(evs), "replayed": tried,
                                "confirmed": confirmed, "samples": notes}
        report[res.get("agent", "?")] = agent_rep
    out_path = path.replace(".json", "") + ".replay.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    kw = {}
    if len(sys.argv) > 2:
        kw["port"] = int(sys.argv[2])
    if len(sys.argv) > 3:
        kw["cfg"] = sys.argv[3]
    main(sys.argv[1], **kw)
